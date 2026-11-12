#!/usr/bin/env bash
# MRK-108 - transaction for future commits. Use only through the shared maintenance lock.
#
# Review fixes on top of the audited production copy (deploy/v3/SHA256SUMS.original, PR #65):
# - The transaction is assembled in a hidden staging directory (snapshots, rollback tags, journal "prepared") and only
#   then renamed atomically to transaction-v3-<SHA>. A visible transaction directory therefore always has a journal;
#   a leftover staging directory means no container was touched and is removed by --apply / --recover.
# - "prepared" is recoverable: containers still run the journal's previous image IDs -> state "aborted", the directory
#   is renamed to transaction-v3-<SHA>.aborted-<UTC> and the target can be tried again. Anything else -> manual.
# - A transaction-v3-<SHA> directory without journal (left by the pre-review script) is removed by --recover only after
#   the running containers are verified unchanged (the old script also wrote the journal before "deploying").
# - Target images are trusted by image ID from the root-only provenance record written by the updater when it built
#   them from the verified release (auto-update-v3.sh), not by the revision label alone.
# - Configuration comes from DEPLOY_* variables with the production defaults. They exist for the isolated tests
#   (backend/tests/test_deploy_v3.py); the systemd unit sets only DEPLOY_NEXT_PUBLIC_API_URL (local drop-in, not in Git).
set -Eeuo pipefail
umask 077

ROOT=${DEPLOY_ROOT:-/home/standa/projects/jarvis-mrk101}
TRUSTED=${DEPLOY_TRUSTED:-/usr/local/lib/standa-hub/mrk108}
STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/standa-hub/deployments}
BACKEND_ENV_FILE=${DEPLOY_BACKEND_ENV_FILE:-/srv/standa-hub/backend/.env.production}
NEXT_PUBLIC_API_URL=${DEPLOY_NEXT_PUBLIC_API_URL:-https://<tailnet-host>:8443}
REQUIRED_UID=${DEPLOY_REQUIRED_UID:-0}
GIT_USER=${DEPLOY_GIT_USER-standa}
HEALTH_TRIES=${DEPLOY_HEALTH_TRIES:-24}
HEALTH_SLEEP=${DEPLOY_HEALTH_SLEEP:-5}
BACKEND_MANAGED="$TRUSTED/backend-managed.yaml"
FRONTEND_MANAGED="$TRUSTED/frontend-managed.yaml"

[[ $# == 2 && ($1 == --check || $1 == --apply || $1 == --recover) && $2 =~ ^[a-f0-9]{40}$ ]] || {
  echo 'Usage: deploy-transaction-v3.sh --check|--apply|--recover SHA' >&2; exit 2;
}
MODE=$1 TARGET=$2
[[ $EUID == "$REQUIRED_UID" && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ $NEXT_PUBLIC_API_URL == https://* && $NEXT_PUBLIC_API_URL != *'<'* ]] || { echo 'NEXT_PUBLIC_API_URL_NOT_CONFIGURED' >&2; exit 1; }
[[ -d $STATE_DIR && ! -L $STATE_DIR && $(stat -c '%u:%a' "$STATE_DIR") == "$REQUIRED_UID:700" ]] || { echo 'INSECURE_STATE_DIR' >&2; exit 1; }
for p in "$TRUSTED" "$TRUSTED/deployment-journal.py" "$TRUSTED/check-backup.py" "$TRUSTED/verify-release.py" "$TRUSTED/check-ci.sh" "$BACKEND_MANAGED" "$FRONTEND_MANAGED"; do
  [[ -e $p && ! -L $p && $(stat -c '%u' "$p") == "$REQUIRED_UID" ]] || { echo "UNTRUSTED_PATH: $p" >&2; exit 1; }
done

FINAL="$STATE_DIR/transaction-v3-$TARGET"
PROVENANCE="$STATE_DIR/provenance/$TARGET.json"
BACKEND_NEW="standa-hub-backend:$TARGET"
FRONTEND_NEW="standa-hub-frontend:$TARGET"
set_tx() { TX=$1; JOURNAL="$TX/journal.json"; OLD_B="$TX/backend.json"; OLD_F="$TX/frontend.json"; }
set_tx "$FINAL"

as_git_user() { if [[ -n $GIT_USER ]]; then runuser -u "$GIT_USER" -- "$@"; else "$@"; fi; }

jval() {
  python3 -I - "$JOURNAL" "$1" <<'PY'
import json,sys
j=json.load(open(sys.argv[1])); field=sys.argv[2]
if field == 'state': print(j['state'])
elif field in ('backend','frontend'): print(j['previous'][field]['image_id'])
elif field in ('target_backend','target_frontend'): print(j['target'][field.split('_')[1]]['image_id'])
elif field == 'previous_commit': print(j['previous']['backend']['app_commit'])
else: raise ValueError(field)
PY
}
advance() { python3 -I "$TRUSTED/deployment-journal.py" "$JOURNAL" "$1"; }
image_id() { docker image inspect "$1" --format '{{.Id}}'; }
running_id() { docker inspect "$1" --format '{{.Image}}'; }
check_running() { [[ $(running_id "$1") == "$2" ]] || { echo "IMAGE_MISMATCH: $1" >&2; return 1; }; }
fsync_dir() { python3 -I -c 'import os,sys; fd=os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)' "$1"; }
utc_stamp() { date -u +%Y%m%dT%H%M%SZ; }

check_backend() {
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null |
      python3 -I -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="healthy" and d["database"]["status"]=="reachable" and d["migrations"]["status"]=="current"' 2>/dev/null; then return 0; fi
    sleep "$HEALTH_SLEEP"
  done
  echo 'BACKEND_HEALTH_FAILED' >&2; return 1
}
check_frontend() {
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:3000/login 2>/dev/null; then return 0; fi
    sleep "$HEALTH_SLEEP"
  done
  echo 'FRONTEND_HEALTH_FAILED' >&2; return 1
}

check_transactions() {
  python3 -I - "$STATE_DIR" "$TARGET" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); target=sys.argv[2]
for p in list(root.glob('transaction-v2-*/journal.json')) + list(root.glob('transaction-v3-*/journal.json')):
    if p.parent.name == 'transaction-v3-'+target:
        continue
    try: state=json.loads(p.read_text())['state']
    except (ValueError,KeyError,OSError): raise SystemExit('INVALID_JOURNAL: '+str(p))
    if state not in ('deployed','rolled_back','aborted'):
        raise SystemExit('PENDING_TRANSACTION: '+str(p)+' (run --recover for its target)')
for p in root.glob('transaction-v3-*'):
    if p.name != 'transaction-v3-'+target and p.is_dir() and not (p/'journal.json').exists():
        raise SystemExit('INCOMPLETE_TRANSACTION_DIRECTORY: '+str(p)+' (run --recover for its target)')
staging=sorted(p.name for p in root.glob('.staging-v3-*'))
if staging:
    print('STALE_STAGING_DIRECTORIES: '+str(len(staging))+' (removed by the next --apply or --recover)')
print('NO_PENDING_TRANSACTIONS')
PY
}

# Staging directories never reach "deploying" (the rename to transaction-v3-<SHA> comes first), so no container was
# touched while they existed: removing them (and the secrets in their snapshots) is always safe.
remove_stale_staging() {
  local d
  for d in "$STATE_DIR"/.staging-v3-*; do
    [[ -d $d && ! -L $d ]] || continue
    rm -rf -- "$d"
    echo "STALE_STAGING_REMOVED: ${d##*/}"
  done
}

# Snapshot complete, resolved Compose service configurations (including secrets) in root-only JSON.
# Verify their Compose hashes match those actually used to create running containers.
# If anyone changed managed config since deployment, refuse to deploy rather than snapshot a lie.
prepare_snapshot() {
  local old_commit=$1 old_backend=$2 old_frontend=$3
  local bh fh
  bh=$(env BACKEND_IMAGE="$old_backend" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$old_commit" \
       docker compose -p backend -f "$BACKEND_MANAGED" config --hash backend | awk '{print $NF}')
  fh=$(env FRONTEND_IMAGE="$old_frontend" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
       docker compose -p frontend -f "$FRONTEND_MANAGED" config --hash frontend | awk '{print $NF}')
  [[ -n $bh && -n $fh ]] || { echo 'COMPOSE_HASH_MISSING' >&2; return 1; }
  [[ $bh == "$(docker inspect standa-hub-backend --format '{{index .Config.Labels "com.docker.compose.config-hash"}}')" ]] || { echo 'BACKEND_COMPOSE_DRIFT' >&2; return 1; }
  [[ $fh == "$(docker inspect standa-hub-frontend --format '{{index .Config.Labels "com.docker.compose.config-hash"}}')" ]] || { echo 'FRONTEND_COMPOSE_DRIFT' >&2; return 1; }
  if [[ ${4:-0} == 1 ]]; then
    env BACKEND_IMAGE="$old_backend" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$old_commit" \
      docker compose -p backend -f "$BACKEND_MANAGED" config --format json > "$OLD_B"
    env FRONTEND_IMAGE="$old_frontend" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
      docker compose -p frontend -f "$FRONTEND_MANAGED" config --format json > "$OLD_F"
    chmod 600 "$OLD_B" "$OLD_F"
    python3 -I - "$OLD_B" "$OLD_F" "$old_backend" "$old_frontend" <<'PY'
import json,sys
for path, service, expected in ((sys.argv[1],'backend',sys.argv[3]),(sys.argv[2],'frontend',sys.argv[4])):
    s=json.load(open(path))['services'][service]
    assert s['image']==expected and s['container_name']=='standa-hub-'+service
print('EXACT_COMPOSE_SNAPSHOTS_SAVED')
PY
  fi
  echo 'COMPOSE_HASHES_MATCH_RUNNING'
}

check_migrations() {
  local oldhead newhead
  oldhead=$(docker run --rm --network none --pull never --entrypoint alembic "$1" heads)
  newhead=$(docker run --rm --network none --pull never --entrypoint alembic "$2" heads)
  [[ -n $oldhead && $oldhead == "$newhead" ]] || { echo 'MIGRATION_HEAD_CHANGED: MANUAL_REVIEW_REQUIRED' >&2; return 1; }
  echo 'MIGRATION_HEAD_UNCHANGED'
}

# Target images: the root-only provenance record (written by the updater from its own `docker build --iidfile` of the
# verified release) must name exactly the image IDs the target tags point at now, and the IDs must carry the revision.
verify_provenance() {
  [[ -f $PROVENANCE && ! -L $PROVENANCE && $(stat -c '%u:%a' "$PROVENANCE") == "$REQUIRED_UID:600" ]] || {
    echo "TARGET_IMAGE_PROVENANCE_MISSING: $TARGET" >&2; return 1; }
  local service expected actual
  for service in backend frontend; do
    expected=$(python3 -I - "$PROVENANCE" "$TARGET" "$service" <<'PY'
import json,re,sys
d=json.load(open(sys.argv[1]))
assert d['target_commit']==sys.argv[2] and d.get('release_verified') is True
i=d['images'][sys.argv[3]]['image_id']
assert re.fullmatch(r'sha256:[0-9a-f]{64}', i)
print(i)
PY
) || { echo "TARGET_IMAGE_PROVENANCE_INVALID: $service" >&2; return 1; }
    actual=$(image_id "standa-hub-$service:$TARGET") || actual=''
    [[ $actual == "$expected" ]] || { echo "TARGET_IMAGE_NOT_FROM_VERIFIED_BUILD: $service" >&2; return 1; }
    [[ $(docker image inspect "$expected" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || {
      echo "TARGET_IMAGE_UNVERIFIED: $service" >&2; return 1; }
  done
  echo 'TARGET_IMAGE_PROVENANCE_VERIFIED'
}

# Image IDs, not mutable release names, are the authority for rollback.
# A unique per-transaction rollback tag whose ID is checked before use is started through the SAME managed templates as
# every deployment, with the previous values. The audited copy started the saved snapshot plus an override
# (pull_policy: never); that changed the Compose config-hash, so the next update stopped on *_COMPOSE_DRIFT for good.
# The snapshot stays the proof: the template rendered with the previous values must equal it (image aside), otherwise
# the managed config changed since the snapshot and the rollback stops for manual recovery.
# Safe to repeat: an interrupted rollback stays in rollback_required and --recover runs it again.
rollback_env() {  # service rollback-ref -> env assignments for the managed template
  if [[ $1 == backend ]]; then
    printf '%s\n' "BACKEND_IMAGE=$2" "BACKEND_ENV_FILE=$BACKEND_ENV_FILE" "APP_COMMIT=$(jval previous_commit)"
  else
    printf '%s\n' "FRONTEND_IMAGE=$2" "NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL"
  fi
}
snapshot_matches() {  # service rollback-ref snapshot-file
  local -a vars
  mapfile -t vars < <(rollback_env "$1" "$2")
  env "${vars[@]}" docker compose -p "$1" -f "$TRUSTED/$1-managed.yaml" config --format json |
    python3 -I -c '
import json,sys
service, ref, snapshot = sys.argv[1], sys.argv[2], sys.argv[3]
rendered = json.load(sys.stdin)["services"][service]
saved = json.load(open(snapshot))["services"][service]
saved["image"] = ref
sys.exit(0 if rendered == saved else 1)
' "$1" "$2" "$3"
}
rollback() {
  local expected_b expected_f rb rf failures=0 service ref
  local -a vars
  [[ -f $OLD_B && -f $OLD_F && -f $JOURNAL ]] || { echo 'ROLLBACK_SNAPSHOT_MISSING' >&2; return 1; }
  expected_b=$(jval backend); expected_f=$(jval frontend)
  rb="standa-hub-backend:rollback-$TARGET"; rf="standa-hub-frontend:rollback-$TARGET"
  [[ $(image_id "$rb") == "$expected_b" && $(image_id "$rf") == "$expected_f" ]] || { echo 'ROLLBACK_IMAGE_ID_CHANGED' >&2; return 1; }
  snapshot_matches backend "$rb" "$OLD_B" && snapshot_matches frontend "$rf" "$OLD_F" || {
    echo 'MANAGED_CONFIG_CHANGED_SINCE_SNAPSHOT: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  echo '=== RESTORE PREVIOUS RELEASE ===' >&2
  for service in backend frontend; do
    ref=$([[ $service == backend ]] && echo "$rb" || echo "$rf")
    mapfile -t vars < <(rollback_env "$service" "$ref")
    env "${vars[@]}" docker compose -p "$service" -f "$TRUSTED/$service-managed.yaml" \
      up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 "$service" || failures=1
  done
  [[ $(running_id standa-hub-backend) == "$expected_b" ]] || failures=1
  [[ $(running_id standa-hub-frontend) == "$expected_f" ]] || failures=1
  check_backend || failures=1
  check_frontend || failures=1
  if (( failures )); then echo 'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  advance rolled_back
  echo 'ROLLBACK_VERIFIED'
}

# "prepared": the journal exists but "deploying" was never written, so no `compose up` ran. Prove it (both containers
# still run the journal's previous image IDs), close the transaction as "aborted" and move it aside so the same target
# can be deployed again later.
abort_prepared() {
  local expected_b expected_f
  expected_b=$(jval backend); expected_f=$(jval frontend)
  if [[ $(running_id standa-hub-backend) != "$expected_b" || $(running_id standa-hub-frontend) != "$expected_f" ]]; then
    echo 'PREPARED_BUT_CONTAINERS_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1
  fi
  advance aborted
  mv -T -- "$TX" "$TX.aborted-$(utc_stamp)"
  fsync_dir "$STATE_DIR"
  echo 'TRANSACTION_ABORTED_NO_PRODUCTION_CHANGE'
}

on_exit() {
  local rc=$? state
  trap - EXIT INT TERM
  if (( rc != 0 )) && [[ $MODE == --apply && $TX == "$FINAL" && -f $JOURNAL ]]; then
    state=$(jval state) || state=invalid
    case "$state" in
      prepared) abort_prepared || echo 'MANUAL_RECOVERY_REQUIRED' >&2 ;;
      deploying|verifying) { advance rollback_required && rollback; } || echo 'MANUAL_RECOVERY_REQUIRED' >&2 ;;
    esac
  elif (( rc != 0 )) && [[ $MODE == --apply && $TX != "$FINAL" && -d $TX ]]; then
    rm -rf -- "$TX"   # failed while staging: nothing was deployed
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

read_current() {
  OLD_COMMIT=$(docker inspect standa-hub-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^APP_COMMIT=//p' | head -n1)
  [[ $OLD_COMMIT =~ ^[a-f0-9]{40}$ ]] || { echo 'CURRENT_COMMIT_UNKNOWN' >&2; exit 1; }
  OLD_BACKEND=$(docker inspect standa-hub-backend --format '{{.Config.Image}}')
  OLD_FRONTEND=$(docker inspect standa-hub-frontend --format '{{.Config.Image}}')
}

if [[ $MODE == --recover ]]; then
  remove_stale_staging
  if [[ -d $FINAL && ! -L $FINAL && ! -e $JOURNAL ]]; then
    # Left by the pre-review script between mkdir and the journal: it never reached "deploying". Remove it only when the
    # running services are healthy and still match the managed config they were deployed with.
    read_current
    prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND"
    check_backend
    check_frontend
    rm -rf -- "$FINAL"
    fsync_dir "$STATE_DIR"
    echo 'INCOMPLETE_TRANSACTION_REMOVED_NO_PRODUCTION_CHANGE'
    exit 0
  fi
  [[ -f $JOURNAL ]] || { echo 'JOURNAL_NOT_FOUND' >&2; exit 1; }
  state=$(jval state)
  case "$state" in
    prepared) abort_prepared; exit 0 ;;
    deploying|verifying) advance rollback_required ;;
    rollback_required) ;;
    *) echo "NOT_RECOVERABLE: $state" >&2; exit 1 ;;
  esac
  rollback
  exit 0
fi

check_transactions

python3 -I - <<'PY'
import json,subprocess
for s in ('backend','frontend'):
    c=json.loads(subprocess.check_output(['docker','inspect','standa-hub-'+s],text=True))[0]
    l=c['Config'].get('Labels') or {}
    assert c['State']['Running'] and l.get('com.docker.compose.project')==s and l.get('com.docker.compose.service')==s
print('PRODUCTION_CONTAINERS_VERIFIED')
PY
check_backend
check_frontend
read_current
[[ $(docker inspect standa-hub-frontend --format '{{index .Config.Labels "com.docker.compose.project"}}') == frontend ]] || exit 1

if [[ $OLD_COMMIT == "$TARGET" ]]; then
  prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND"
  check_running standa-hub-backend "$(image_id "$BACKEND_NEW")"
  check_running standa-hub-frontend "$(image_id "$FRONTEND_NEW")"
  echo 'ALREADY_DEPLOYED'
  exit 0
fi
# After the "already deployed" case: the audited copy checked this first, so every hourly --check after a successful
# v3 deploy (transaction-v3-<current> exists, state deployed) failed with TRANSACTION_ALREADY_EXISTS.
[[ ! -e $FINAL ]] || { echo 'TRANSACTION_ALREADY_EXISTS' >&2; exit 1; }

# Enforce ancestry even if transaction is invoked outside the updater.
as_git_user git -C "$ROOT" merge-base --is-ancestor "$OLD_COMMIT" "$TARGET" || { echo 'NON_FAST_FORWARD_BLOCKED' >&2; exit 1; }
as_git_user "$TRUSTED/check-ci.sh" "$TARGET"
python3 -I "$TRUSTED/check-backup.py"
python3 -I "$TRUSTED/verify-release.py" "$TARGET"
verify_provenance
NEW_B_ID=$(image_id "$BACKEND_NEW")
NEW_F_ID=$(image_id "$FRONTEND_NEW")
check_migrations "$OLD_BACKEND" "$NEW_B_ID"
prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND"
env BACKEND_IMAGE="$BACKEND_NEW" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$TARGET" \
  docker compose -p backend -f "$BACKEND_MANAGED" config --quiet
env FRONTEND_IMAGE="$FRONTEND_NEW" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
  docker compose -p frontend -f "$FRONTEND_MANAGED" config --quiet

echo 'DEPLOYMENT_PREFLIGHT_OK'
if [[ $MODE == --check ]]; then echo 'NO_PRODUCTION_CHANGES'; exit 0; fi

# --- apply: assemble everything in a hidden staging directory, then publish it with one atomic rename ---
remove_stale_staging
set_tx "$(mktemp -d "$STATE_DIR/.staging-v3-$TARGET.XXXXXXXX")"
chmod 700 "$TX"
prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND" 1
OLD_B_ID=$(running_id standa-hub-backend)
OLD_F_ID=$(running_id standa-hub-frontend)
[[ $(image_id "$OLD_BACKEND") == "$OLD_B_ID" && $(image_id "$OLD_FRONTEND") == "$OLD_F_ID" ]] || { echo 'CURRENT_IMAGE_TAG_DRIFT' >&2; exit 1; }
docker image tag "$OLD_B_ID" "standa-hub-backend:rollback-$TARGET"
docker image tag "$OLD_F_ID" "standa-hub-frontend:rollback-$TARGET"
[[ $(image_id "standa-hub-backend:rollback-$TARGET") == "$OLD_B_ID" && $(image_id "standa-hub-frontend:rollback-$TARGET") == "$OLD_F_ID" ]] || exit 1
python3 -I - "$TX" "$TARGET" "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND" "$OLD_B_ID" "$OLD_F_ID" "$BACKEND_NEW" "$FRONTEND_NEW" "$NEW_B_ID" "$NEW_F_ID" <<'PY'
import json,os,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
p=Path(sys.argv[1]);target=sys.argv[2]
d={'state':'prepared','target_commit':target,'created_at':datetime.now(timezone.utc).isoformat(),
 'previous':{'backend':{'image_reference':sys.argv[4],'image_id':sys.argv[6],'app_commit':sys.argv[3]},
             'frontend':{'image_reference':sys.argv[5],'image_id':sys.argv[7]}},
 'target':{'backend':{'image_reference':sys.argv[8],'image_id':sys.argv[10]},
           'frontend':{'image_reference':sys.argv[9],'image_id':sys.argv[11]}}}
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
mv -T -- "$TX" "$FINAL"
fsync_dir "$STATE_DIR"
set_tx "$FINAL"
advance deploying

# Compose gets the target tags (as before); the running image ID is then checked against the journal's provenance IDs.
echo '=== DEPLOY BACKEND ==='
env BACKEND_IMAGE="$BACKEND_NEW" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$TARGET" \
  docker compose -p backend -f "$BACKEND_MANAGED" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 backend
check_running standa-hub-backend "$(jval target_backend)"
check_backend
echo '=== DEPLOY FRONTEND ==='
env FRONTEND_IMAGE="$FRONTEND_NEW" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
  docker compose -p frontend -f "$FRONTEND_MANAGED" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 frontend
check_running standa-hub-frontend "$(jval target_frontend)"
check_frontend
advance verifying
check_backend
check_frontend
advance deployed
echo 'PRODUCTION_DEPLOYMENT_OK'
