#!/usr/bin/env bash
# MRK-120 - recreate ONLY the production backend after a change of backend/.env.production: same image, same commit.
# Use only through the shared maintenance lock:
#   sudo /usr/local/lib/standa-hub/with-deployment-lock.sh /usr/local/lib/standa-hub/restart-v3.sh --check|--apply|--recover
#
# Why: Compose reads env_file only when it creates the container and inlines its values into the service config, so an
# edited .env.production is not used until the container is recreated, and it also changes the config-hash:
# deploy-transaction-v3.sh then stops on BACKEND_COMPOSE_DRIFT. A manual `docker compose up` bypasses the lock, the
# journal, the health check and the rollback.
#
# Safety:
# - The previous environment is reconstructed from the running container (its env minus the image's own env and
#   APP_COMMIT) and accepted only when the managed template rendered with it gives exactly the running config-hash.
#   That file is the rollback source - correct even when .env.production was already edited in place.
# - Before any change the new file is rendered by Compose and validated by production.validate_environment in a
#   throwaway container of the running image without network; Web Push switched on requires its VAPID keys.
# - The new file is copied into the transaction (root, 0600) and the container is created from that copy, so an edit
#   during the restart cannot slip in unvalidated.
# - Output and journal name changed variables only, never values.
# - Journal prepared -> recreating -> verifying -> restarted; on failure rollback_required -> rolled_back (previous
#   environment, same image); after a crash --recover. A pending restart blocks deploy-transaction-v3 and
#   deploy-migration-v3, and a pending deployment or migration blocks the restart.
# - Configuration via DEPLOY_* variables with the production defaults (isolated tests: backend/tests/test_restart_v3.py).
set -Eeuo pipefail
umask 077

TRUSTED=${DEPLOY_TRUSTED:-/usr/local/lib/standa-hub/mrk108}
STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/standa-hub/deployments}
BACKEND_ENV_FILE=${DEPLOY_BACKEND_ENV_FILE:-/srv/standa-hub/backend/.env.production}
REQUIRED_UID=${DEPLOY_REQUIRED_UID:-0}
HEALTH_TRIES=${DEPLOY_HEALTH_TRIES:-24}
HEALTH_SLEEP=${DEPLOY_HEALTH_SLEEP:-5}
BACKEND_MANAGED="$TRUSTED/backend-managed.yaml"

[[ $# == 1 && ($1 == --check || $1 == --apply || $1 == --recover) ]] || {
  echo 'Usage: restart-v3.sh --check|--apply|--recover' >&2; exit 2; }
MODE=$1
[[ $EUID == "$REQUIRED_UID" && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ -d $STATE_DIR && ! -L $STATE_DIR && $(stat -c '%u:%a' "$STATE_DIR") == "$REQUIRED_UID:700" ]] || { echo 'INSECURE_STATE_DIR' >&2; exit 1; }
trusted_path() {
  local path=$1 mode
  [[ -e $path && ! -L $path && $(stat -c %u -- "$path") == "$REQUIRED_UID" ]] || return 1
  mode=$(stat -c %a -- "$path") || return 1
  (( (8#$mode & 0022) == 0 ))
}
for p in "$TRUSTED" "$TRUSTED/restart-journal.py" "$BACKEND_MANAGED" "$0"; do
  trusted_path "$p" || { echo "UNTRUSTED_PATH: $p" >&2; exit 1; }
done
# The env file holds every production secret and decides what runs: root-owned regular file, no group/other write.
[[ -f $BACKEND_ENV_FILE ]] && trusted_path "$BACKEND_ENV_FILE" || { echo 'UNTRUSTED_ENV_FILE' >&2; exit 1; }

TX='' JOURNAL=''
advance() { python3 -I "$TRUSTED/restart-journal.py" "$JOURNAL" "$1"; }
jget() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$JOURNAL" "$1"; }
image_id() { docker image inspect "$1" --format '{{.Id}}'; }
running_id() { docker inspect standa-hub-backend --format '{{.Image}}'; }
running_hash() { docker inspect standa-hub-backend --format '{{index .Config.Labels "com.docker.compose.config-hash"}}'; }
fsync_dir() { python3 -I -c 'import os,sys; fd=os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)' "$1"; }
utc_stamp() { date -u +%Y%m%dT%H%M%SZ; }

# Config-hash of the managed backend for an env file, with the running image reference and commit (as prepare_snapshot
# in deploy-transaction-v3.sh computes it: the hash of the fully resolved service).
render_hash() {
  env BACKEND_IMAGE="$IMAGE_REF" BACKEND_ENV_FILE="$1" APP_COMMIT="$COMMIT" \
    bash -o pipefail -c 'docker compose -p backend -f "$1" config --format json |
      docker compose -p backend -f - config --hash backend' _ "$BACKEND_MANAGED" | awk '{print $NF}'
}
up_backend() {
  env BACKEND_IMAGE="$IMAGE_REF" BACKEND_ENV_FILE="$1" APP_COMMIT="$COMMIT" \
    docker compose -p backend -f "$BACKEND_MANAGED" up -d --no-deps --no-build --pull never --force-recreate \
      --wait --wait-timeout 120 backend
}
check_backend() {
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null |
      python3 -I -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="healthy" and d["database"]["status"]=="reachable" and d["migrations"]["status"]=="current"' 2>/dev/null; then return 0; fi
    sleep "$HEALTH_SLEEP"
  done
  echo 'BACKEND_HEALTH_FAILED' >&2; return 1
}

# Any unfinished deployment, migration or restart blocks a new restart (--recover handles its own pending restart).
pending() {
  python3 -I - "$STATE_DIR" "$1" <<'PY'
import json,sys
from pathlib import Path
root, mode = Path(sys.argv[1]), sys.argv[2]
terminal={'transaction':('deployed','rolled_back','aborted'),'migration':('deployed','aborted','rolled_back_app'),
          'restart':('restarted','rolled_back','aborted'),'template':('restarted','rolled_back','aborted')}
own=[]
for kind, pattern in (('transaction','transaction-v2-*'),('transaction','transaction-v3-*'),
                      ('migration','migration-v3-*'),('restart','restart-v3-*'),('template','template-v3-*')):
    for d in sorted(root.glob(pattern)):
        if not d.is_dir():
            continue
        try: state=json.loads((d/'journal.json').read_text())['state']
        except (ValueError,KeyError,OSError): raise SystemExit('INCOMPLETE_OR_INVALID_JOURNAL: '+str(d))
        if state in terminal[kind]:
            continue
        if kind == 'restart' and mode == '--recover':
            own.append(str(d)); continue
        raise SystemExit('PENDING_'+kind.upper()+': '+str(d)+' (run --recover of its script)')
if len(own) > 1:
    raise SystemExit('SEVERAL_PENDING_RESTARTS: MANUAL_RECOVERY_REQUIRED')
print(own[0] if own else 'NO_PENDING_TRANSACTIONS')
PY
}

# Staging directories never reached "prepared" in a visible directory, so no container was touched while they existed:
# removing them (and the secrets in them) is always safe. The maintenance lock rules out a concurrent run.
remove_stale_staging() {
  local d
  for d in "$STATE_DIR"/.staging-restart-v3-*; do
    [[ -d $d && ! -L $d ]] || continue
    rm -rf -- "$d"
    echo "STALE_STAGING_REMOVED: ${d##*/}"
  done
}

read_current() {
  python3 -I - <<'PY'
import json,subprocess
c=json.loads(subprocess.check_output(['docker','inspect','standa-hub-backend'],text=True))[0]
l=c['Config'].get('Labels') or {}
assert c['State']['Running'] and l.get('com.docker.compose.project')=='backend' and l.get('com.docker.compose.service')=='backend'
print('PRODUCTION_BACKEND_VERIFIED')
PY
  COMMIT=$(docker inspect standa-hub-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^APP_COMMIT=//p' | head -n1)
  [[ $COMMIT =~ ^[a-f0-9]{40}$ ]] || { echo 'CURRENT_COMMIT_UNKNOWN' >&2; exit 1; }
  IMAGE_REF=$(docker inspect standa-hub-backend --format '{{.Config.Image}}')
  IMAGE_ID=$(running_id)
  [[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ && $(image_id "$IMAGE_REF") == "$IMAGE_ID" ]] || { echo 'CURRENT_IMAGE_TAG_DRIFT' >&2; exit 1; }
  RUNNING_HASH=$(running_hash)
  [[ -n $RUNNING_HASH ]] || { echo 'RUNNING_CONFIG_HASH_MISSING' >&2; exit 1; }
}

# Container env minus the image's own env minus APP_COMMIT (set by the template) = what came from the env file.
# Secrets travel through files in the 0700 transaction directory, never through process arguments (/proc/*/cmdline).
reconstruct_previous() {
  docker inspect standa-hub-backend --format '{{range .Config.Env}}{{println .}}{{end}}' > "$TX/.container.env"
  docker image inspect "$IMAGE_ID" --format '{{range .Config.Env}}{{println .}}{{end}}' > "$TX/.image.env"
  python3 -I -c '
import os,sys
out, container, image = sys.argv[1], open(sys.argv[2]).read().splitlines(), set(open(sys.argv[3]).read().splitlines())
lines=[l for l in container if l and l not in image and not l.startswith("APP_COMMIT=")]
fd=os.open(out, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
with os.fdopen(fd,"w") as f:
    f.write("".join(l+"\n" for l in lines))
' "$1" "$TX/.container.env" "$TX/.image.env"
  rm -f -- "$TX/.container.env" "$TX/.image.env"
}

# Names only: which variables the new file adds, removes or changes against the running environment.
env_changes() {
  python3 -I - "$1" "$2" <<'PY'
import sys
def parse(path):
    out={}
    for line in open(path, encoding='utf-8'):
        line=line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        k,v=line.split('=',1); out[k.strip()]=v
    return out
old,new=parse(sys.argv[1]),parse(sys.argv[2])
for label,names in (('ADDED',sorted(new.keys()-old.keys())),('REMOVED',sorted(old.keys()-new.keys())),
                    ('CHANGED',sorted(k for k in old.keys()&new.keys() if old[k]!=new[k]))):
    print(f'ENV_{label}: '+(', '.join(names) if names else '-'))
PY
}

# Runs inside a throwaway container of the running image (WORKDIR /app), without network. Prints only ENV_VALID or
# ENV_INVALID with a message that never contains a value (production.validate_environment messages are value-free).
VALIDATE_PY='
import os, sys
try:
    import production
    production.validate_environment(os.environ)
    if os.environ.get("EXTERNAL_DELIVERY_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}:
        missing = [k for k in ("WEB_PUSH_VAPID_PRIVATE_KEY", "WEB_PUSH_VAPID_PUBLIC_KEY", "WEB_PUSH_CONTACT")
                   if not os.environ.get(k, "").strip()]
        if missing:
            raise ValueError("EXTERNAL_DELIVERY_ENABLED=true requires " + ", ".join(missing))
except ValueError as error:
    print("ENV_INVALID: " + str(error)); sys.exit(1)
except BaseException as error:
    print("ENV_INVALID: " + type(error).__name__); sys.exit(1)
print("ENV_VALID")
'
validate_candidate() {
  local result
  result=$(docker run --rm --network none --pull never --env-file "$1" --entrypoint python "$IMAGE_ID" -c "$VALIDATE_PY" 2>/dev/null) || true
  result=$(printf '%s\n' "$result" | grep -E '^ENV_(VALID|INVALID)' | tail -n1 || true)
  if [[ $result != ENV_VALID ]]; then
    echo "${result:-ENV_INVALID: validation did not run}" >&2
    return 1
  fi
  echo 'ENV_VALID'
}

# Rollback: the previous environment (reconstructed and hash-proven before the change) with the same image.
rollback() {
  local expected_id prev_hash failures=0
  IMAGE_REF=$(jget image_reference); COMMIT=$(jget app_commit)
  expected_id=$(jget image_id); prev_hash=$(jget previous_hash)
  [[ -f $TX/env.previous ]] || { echo 'ROLLBACK_ENV_MISSING: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  [[ $(image_id "$IMAGE_REF") == "$expected_id" ]] || { echo 'ROLLBACK_IMAGE_ID_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  [[ $(render_hash "$TX/env.previous") == "$prev_hash" ]] || {
    echo 'MANAGED_CONFIG_CHANGED_SINCE_RESTART: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  echo '=== RESTORE PREVIOUS ENVIRONMENT ===' >&2
  up_backend "$TX/env.previous" || failures=1
  [[ $(running_id) == "$expected_id" ]] || failures=1
  [[ $(running_hash) == "$prev_hash" ]] || failures=1
  check_backend || failures=1
  if (( failures )); then echo 'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  advance rolled_back
  echo 'ROLLBACK_VERIFIED'
  echo 'RESTART_ROLLED_BACK: the backend runs the previous environment again; .env.production still holds the new' \
       'values - fix them, then --check and --apply again' >&2
}
abort_prepared() {
  [[ $(running_id) == "$(jget image_id)" && $(running_hash) == "$(jget previous_hash)" ]] || {
    echo 'PREPARED_BUT_BACKEND_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  advance aborted
  echo 'RESTART_ABORTED_NO_PRODUCTION_CHANGE'
}

on_exit() {
  local rc=$? state
  trap - EXIT INT TERM
  if (( rc != 0 )) && [[ $MODE == --apply && -n $JOURNAL && -f $JOURNAL ]]; then
    state=$(jget state) || state=invalid
    case "$state" in
      prepared) abort_prepared || echo 'MANUAL_RECOVERY_REQUIRED' >&2 ;;
      recreating|verifying) { advance rollback_required && rollback; } || echo 'MANUAL_RECOVERY_REQUIRED' >&2 ;;
    esac
  fi
  # A staging directory that was not published (every --check, a failed preflight) holds secrets: remove it.
  if [[ -n $TX && ${TX##*/} == .staging-restart-v3-* && -d $TX ]]; then rm -rf -- "$TX"; fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

remove_stale_staging

if [[ $MODE == --recover ]]; then
  found=$(pending --recover)
  if [[ $found == NO_PENDING_TRANSACTIONS ]]; then echo 'NO_PENDING_RESTART'; exit 0; fi
  TX=$found JOURNAL="$found/journal.json"
  state=$(jget state)
  case "$state" in
    prepared) abort_prepared; exit 0 ;;
    recreating|verifying) advance rollback_required ;;
    rollback_required) ;;
    *) echo "NOT_RECOVERABLE: $state" >&2; exit 1 ;;
  esac
  rollback
  exit 0
fi

pending "$MODE"
read_current
check_backend

TX=$(mktemp -d "$STATE_DIR/.staging-restart-v3-XXXXXXXX")
chmod 700 "$TX"
reconstruct_previous "$TX/env.previous"
[[ $(render_hash "$TX/env.previous") == "$RUNNING_HASH" ]] || {
  echo 'PREVIOUS_ENV_NOT_RECONSTRUCTABLE: MANUAL_REVIEW_REQUIRED' >&2; exit 1; }
echo 'PREVIOUS_ENV_RECONSTRUCTED'
cp -- "$BACKEND_ENV_FILE" "$TX/env.target"
chmod 600 "$TX/env.target"
TARGET_HASH=$(render_hash "$TX/env.target")
[[ -n $TARGET_HASH ]] || { echo 'ENV_RENDER_FAILED' >&2; exit 1; }
env_changes "$TX/env.previous" "$TX/env.target"
if [[ $TARGET_HASH == "$RUNNING_HASH" ]]; then
  echo 'NOTHING_TO_RESTART: the backend already runs this environment'
  exit 0
fi
validate_candidate "$TX/env.target"
echo 'RESTART_PREFLIGHT_OK'
if [[ $MODE == --check ]]; then echo 'NO_PRODUCTION_CHANGES'; exit 0; fi

# --- apply: journal in the staging directory, published by one atomic rename before the container is touched ---
python3 -I - "$TX" "$COMMIT" "$IMAGE_REF" "$IMAGE_ID" "$RUNNING_HASH" "$TARGET_HASH" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1])
d={'state':'prepared','created_at':datetime.now(timezone.utc).isoformat(),'app_commit':sys.argv[2],
   'image_reference':sys.argv[3],'image_id':sys.argv[4],'previous_hash':sys.argv[5],'target_hash':sys.argv[6]}
fd,tmp=tempfile.mkstemp(prefix='.journal.',dir=p)
try:
    with os.fdopen(fd,'w') as f:
        json.dump(d,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,p/'journal.json')
    dfd=os.open(p,os.O_RDONLY)
    try: os.fsync(dfd)
    finally: os.close(dfd)
finally:
    if os.path.exists(tmp):os.unlink(tmp)
PY
FINAL="$STATE_DIR/restart-v3-$(utc_stamp)-$$"
[[ ! -e $FINAL ]] || { echo 'RESTART_DIRECTORY_COLLISION' >&2; exit 1; }
mv -T -- "$TX" "$FINAL"
fsync_dir "$STATE_DIR"
TX=$FINAL JOURNAL="$FINAL/journal.json"
advance recreating

echo '=== RECREATE BACKEND (same image, same commit, new environment) ==='
up_backend "$TX/env.target"
[[ $(running_id) == "$IMAGE_ID" ]] || { echo 'IMAGE_MISMATCH: standa-hub-backend' >&2; exit 1; }
[[ $(running_hash) == "$TARGET_HASH" ]] || { echo 'CONFIG_HASH_MISMATCH: standa-hub-backend' >&2; exit 1; }
check_backend
advance verifying
check_backend
advance restarted
# The updater compares the live file with the running container: an edit during the restart shows up there as drift.
[[ $(render_hash "$BACKEND_ENV_FILE") == "$TARGET_HASH" ]] ||
  echo 'WARNING_ENV_FILE_CHANGED_DURING_RESTART: run restart-v3.sh --check again' >&2
echo 'RESTART_OK'
