#!/usr/bin/env bash
# MRK-121 - change the managed frontend Compose template (e.g. the game-assets volume) and recreate ONLY the frontend
# with the same image, as one transaction. Use only through the shared maintenance lock:
#   sudo $L/with-deployment-lock.sh $L/frontend-template-v3.sh --check NEW_TEMPLATE
#   sudo $L/with-deployment-lock.sh $L/frontend-template-v3.sh --apply NEW_TEMPLATE
#   sudo $L/with-deployment-lock.sh $L/frontend-template-v3.sh --recover
#
# Why: deploy-transaction-v3.sh renders the installed template ($TRUSTED/frontend-managed.yaml) and compares its
# config-hash with the running frontend. Installing a changed template alone -> FRONTEND_COMPOSE_DRIFT on every run;
# recreating by hand bypasses the lock, journal, health check and rollback.
#
# Safety:
# - NEXT_PUBLIC_API_URL is taken from the running container and accepted only if the INSTALLED template rendered with
#   it and the running image reference gives exactly the running config-hash (INSTALLED_TEMPLATE_DRIFT otherwise) - so
#   no hostname has to be passed or stored, and the previous state is proven.
# - The new template must be root-owned, not group/other-writable; Compose validates it before any change.
# - Journal (mrk108/restart-journal.py states): prepared -> recreating -> verifying -> restarted. The frontend is
#   recreated from the copy in the transaction, image ID / config-hash / health are checked, and only then is the new
#   template installed atomically. On failure or --recover: rollback_required -> rolled_back = the previous template
#   installed again and the frontend recreated with it (hash proven). A pending template change blocks
#   deploy-transaction-v3, deploy-migration-v3 and restart-v3 (repository versions).
set -Eeuo pipefail
umask 077

TRUSTED=${DEPLOY_TRUSTED:-/usr/local/lib/standa-hub/mrk108}
STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/standa-hub/deployments}
REQUIRED_UID=${DEPLOY_REQUIRED_UID:-0}
HEALTH_TRIES=${DEPLOY_HEALTH_TRIES:-24}
HEALTH_SLEEP=${DEPLOY_HEALTH_SLEEP:-5}
FRONTEND_MANAGED="$TRUSTED/frontend-managed.yaml"

if [[ $# == 1 && $1 == --recover ]]; then MODE=--recover CANDIDATE=''
elif [[ $# == 2 && ($1 == --check || $1 == --apply) ]]; then MODE=$1 CANDIDATE=$2
else echo 'Usage: frontend-template-v3.sh --check|--apply NEW_TEMPLATE | --recover' >&2; exit 2
fi
[[ $EUID == "$REQUIRED_UID" && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ -d $STATE_DIR && ! -L $STATE_DIR && $(stat -c '%u:%a' "$STATE_DIR") == "$REQUIRED_UID:700" ]] || { echo 'INSECURE_STATE_DIR' >&2; exit 1; }
trusted_path() {
  local path=$1 mode
  [[ -e $path && ! -L $path && $(stat -c %u -- "$path") == "$REQUIRED_UID" ]] || return 1
  mode=$(stat -c %a -- "$path") || return 1
  (( (8#$mode & 0022) == 0 ))
}
for p in "$TRUSTED" "$TRUSTED/restart-journal.py" "$FRONTEND_MANAGED" "$0"; do
  trusted_path "$p" || { echo "UNTRUSTED_PATH: $p" >&2; exit 1; }
done
if [[ -n $CANDIDATE ]]; then
  [[ -f $CANDIDATE ]] && trusted_path "$CANDIDATE" || { echo 'UNTRUSTED_TEMPLATE' >&2; exit 1; }
fi

TX='' JOURNAL=''
advance() { python3 -I "$TRUSTED/restart-journal.py" "$JOURNAL" "$1"; }
jget() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$JOURNAL" "$1"; }
image_id() { docker image inspect "$1" --format '{{.Id}}'; }
running_id() { docker inspect standa-hub-frontend --format '{{.Image}}'; }
running_hash() { docker inspect standa-hub-frontend --format '{{index .Config.Labels "com.docker.compose.config-hash"}}'; }
fsync_dir() { python3 -I -c 'import os,sys; fd=os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)' "$1"; }
utc_stamp() { date -u +%Y%m%dT%H%M%SZ; }

# Same computation as prepare_snapshot in deploy-transaction-v3.sh for the frontend.
render_hash() {
  env FRONTEND_IMAGE="$IMAGE_REF" NEXT_PUBLIC_API_URL="$API_URL" \
    docker compose -p frontend -f "$1" config --hash frontend | awk '{print $NF}'
}
up_frontend() {
  env FRONTEND_IMAGE="$IMAGE_REF" NEXT_PUBLIC_API_URL="$API_URL" \
    docker compose -p frontend -f "$1" up -d --no-deps --no-build --pull never --force-recreate \
      --wait --wait-timeout 120 frontend
}
check_frontend() {
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:3000/login 2>/dev/null; then return 0; fi
    sleep "$HEALTH_SLEEP"
  done
  echo 'FRONTEND_HEALTH_FAILED' >&2; return 1
}
# Atomic install of a template into $TRUSTED (root, 0644), then fsync.
install_template() {
  local tmp
  tmp=$(mktemp "$TRUSTED/.frontend-managed.yaml.XXXXXXXX")
  cat -- "$1" > "$tmp"
  chmod 644 "$tmp"
  mv -T -- "$tmp" "$FRONTEND_MANAGED"
  fsync_dir "$TRUSTED"
}

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
        if kind == 'template' and mode == '--recover':
            own.append(str(d)); continue
        raise SystemExit('PENDING_'+kind.upper()+': '+str(d)+' (run --recover of its script)')
if len(own) > 1:
    raise SystemExit('SEVERAL_PENDING_TEMPLATE_CHANGES: MANUAL_RECOVERY_REQUIRED')
print(own[0] if own else 'NO_PENDING_TRANSACTIONS')
PY
}

remove_stale_staging() {
  local d
  for d in "$STATE_DIR"/.staging-template-v3-*; do
    [[ -d $d && ! -L $d ]] || continue
    rm -rf -- "$d"
    echo "STALE_STAGING_REMOVED: ${d##*/}"
  done
}

read_current() {
  python3 -I - <<'PY'
import json,subprocess
c=json.loads(subprocess.check_output(['docker','inspect','standa-hub-frontend'],text=True))[0]
l=c['Config'].get('Labels') or {}
assert c['State']['Running'] and l.get('com.docker.compose.project')=='frontend' and l.get('com.docker.compose.service')=='frontend'
print('PRODUCTION_FRONTEND_VERIFIED')
PY
  IMAGE_REF=$(docker inspect standa-hub-frontend --format '{{.Config.Image}}')
  IMAGE_ID=$(running_id)
  [[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ && $(image_id "$IMAGE_REF") == "$IMAGE_ID" ]] || { echo 'CURRENT_IMAGE_TAG_DRIFT' >&2; exit 1; }
  API_URL=$(docker inspect standa-hub-frontend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^NEXT_PUBLIC_API_URL=//p' | head -n1)
  [[ $API_URL == https://* && $API_URL != *'<'* ]] || { echo 'NEXT_PUBLIC_API_URL_UNKNOWN' >&2; exit 1; }
  RUNNING_HASH=$(running_hash)
  [[ -n $RUNNING_HASH ]] || { echo 'RUNNING_CONFIG_HASH_MISSING' >&2; exit 1; }
}

rollback() {
  local expected_id prev_hash failures=0
  read_current_for_rollback
  expected_id=$(jget image_id); prev_hash=$(jget previous_hash)
  [[ -f $TX/template.previous ]] || { echo 'ROLLBACK_TEMPLATE_MISSING: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  [[ $(image_id "$IMAGE_REF") == "$expected_id" ]] || { echo 'ROLLBACK_IMAGE_ID_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  [[ $(render_hash "$TX/template.previous") == "$prev_hash" ]] || {
    echo 'PREVIOUS_TEMPLATE_HASH_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  echo '=== RESTORE PREVIOUS FRONTEND TEMPLATE ===' >&2
  install_template "$TX/template.previous"
  up_frontend "$FRONTEND_MANAGED" || failures=1
  [[ $(running_id) == "$expected_id" ]] || failures=1
  [[ $(running_hash) == "$prev_hash" ]] || failures=1
  check_frontend || failures=1
  if (( failures )); then echo 'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  advance rolled_back
  echo 'ROLLBACK_VERIFIED'
}
# After a crash the container may run either template; the image and the API URL are the same in both.
read_current_for_rollback() {
  IMAGE_REF=$(jget image_reference)
  API_URL=$(docker inspect standa-hub-frontend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^NEXT_PUBLIC_API_URL=//p' | head -n1)
  [[ $API_URL == https://* && $API_URL != *'<'* ]] || { echo 'NEXT_PUBLIC_API_URL_UNKNOWN: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
}
abort_prepared() {
  [[ $(running_id) == "$(jget image_id)" && $(running_hash) == "$(jget previous_hash)" ]] || {
    echo 'PREPARED_BUT_FRONTEND_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  advance aborted
  echo 'TEMPLATE_CHANGE_ABORTED_NO_PRODUCTION_CHANGE'
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
  if [[ -n $TX && ${TX##*/} == .staging-template-v3-* && -d $TX ]]; then rm -rf -- "$TX"; fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

remove_stale_staging

if [[ $MODE == --recover ]]; then
  found=$(pending --recover)
  if [[ $found == NO_PENDING_TRANSACTIONS ]]; then echo 'NO_PENDING_TEMPLATE_CHANGE'; exit 0; fi
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
check_frontend

TX=$(mktemp -d "$STATE_DIR/.staging-template-v3-XXXXXXXX")
chmod 700 "$TX"
cp -- "$FRONTEND_MANAGED" "$TX/template.previous"
cp -- "$CANDIDATE" "$TX/template.target"
[[ $(render_hash "$TX/template.previous") == "$RUNNING_HASH" ]] || {
  echo 'INSTALLED_TEMPLATE_DRIFT: the installed template does not match the running frontend - MANUAL_REVIEW_REQUIRED' >&2; exit 1; }
echo 'INSTALLED_TEMPLATE_MATCHES_RUNNING'
env FRONTEND_IMAGE="$IMAGE_REF" NEXT_PUBLIC_API_URL="$API_URL" \
  docker compose -p frontend -f "$TX/template.target" config --quiet || { echo 'TEMPLATE_INVALID' >&2; exit 1; }
TARGET_HASH=$(render_hash "$TX/template.target")
[[ -n $TARGET_HASH ]] || { echo 'TEMPLATE_RENDER_FAILED' >&2; exit 1; }
echo '--- template change (no secrets: values come from variables) ---'
diff -u --label installed --label new "$TX/template.previous" "$TX/template.target" || true
if [[ $TARGET_HASH == "$RUNNING_HASH" ]]; then
  echo 'NOTHING_TO_CHANGE: the frontend already runs this template'
  exit 0
fi
echo 'TEMPLATE_PREFLIGHT_OK'
if [[ $MODE == --check ]]; then echo 'NO_PRODUCTION_CHANGES'; exit 0; fi

python3 -I - "$TX" "$IMAGE_REF" "$IMAGE_ID" "$RUNNING_HASH" "$TARGET_HASH" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1])
d={'state':'prepared','kind':'frontend-template','created_at':datetime.now(timezone.utc).isoformat(),
   'image_reference':sys.argv[2],'image_id':sys.argv[3],'previous_hash':sys.argv[4],'target_hash':sys.argv[5]}
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
FINAL="$STATE_DIR/template-v3-$(utc_stamp)-$$"
[[ ! -e $FINAL ]] || { echo 'TEMPLATE_DIRECTORY_COLLISION' >&2; exit 1; }
mv -T -- "$TX" "$FINAL"
fsync_dir "$STATE_DIR"
TX=$FINAL JOURNAL="$FINAL/journal.json"
advance recreating

echo '=== RECREATE FRONTEND (same image, new template) ==='
up_frontend "$TX/template.target"
[[ $(running_id) == "$IMAGE_ID" ]] || { echo 'IMAGE_MISMATCH: standa-hub-frontend' >&2; exit 1; }
[[ $(running_hash) == "$TARGET_HASH" ]] || { echo 'CONFIG_HASH_MISMATCH: standa-hub-frontend' >&2; exit 1; }
check_frontend
advance verifying
install_template "$TX/template.target"
[[ $(render_hash "$FRONTEND_MANAGED") == "$TARGET_HASH" ]] || { echo 'INSTALLED_TEMPLATE_MISMATCH' >&2; exit 1; }
check_frontend
advance restarted
echo 'FRONTEND_TEMPLATE_APPLIED'
