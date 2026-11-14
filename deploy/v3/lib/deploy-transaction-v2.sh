#!/usr/bin/env bash
# MRK-108: reusable deployment transaction. Must run via the root maintenance-lock wrapper.
set -Eeuo pipefail
umask 077

TRUSTED=/usr/local/lib/standa-hub/mrk108
STATE_DIR=/var/lib/standa-hub/deployments
ROOT=/home/standa/projects/jarvis-mrk101
BACKEND_ENV_FILE=/srv/standa-hub/backend/.env.production
NEXT_PUBLIC_API_URL=https://<tailnet-host>:8443
BACKEND_MANAGED="$TRUSTED/backend-managed.yaml"
FRONTEND_MANAGED="$TRUSTED/frontend-managed.yaml"

usage() { echo 'Usage: deploy-transaction-v2.sh --check|--apply|--recover COMMIT_SHA' >&2; exit 2; }
[[ $# == 2 ]] || usage
MODE=$1
TARGET=$2
[[ $MODE == --check || $MODE == --apply || $MODE == --recover ]] || usage
[[ $TARGET =~ ^[0-9a-f]{40}$ ]] || usage
[[ $EUID == 0 ]] || { echo 'ROOT_REQUIRED' >&2; exit 1; }
[[ -e /proc/self/fd/9 ]] || { echo 'MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ -d "$STATE_DIR" && ! -L "$STATE_DIR" ]] || { echo 'STATE_DIRECTORY_MISSING' >&2; exit 1; }
[[ $(stat -c '%u:%a' "$STATE_DIR") == '0:700' ]] || { echo 'STATE_DIRECTORY_NOT_SECURE' >&2; exit 1; }
for p in "$TRUSTED" "$TRUSTED/deployment-journal.py" "$BACKEND_MANAGED" "$FRONTEND_MANAGED" "$TRUSTED/check-backup.py" "$TRUSTED/verify-release.py"; do
  [[ -e "$p" && ! -L "$p" && $(stat -c '%u' "$p") == 0 ]] || { echo "UNTRUSTED_PATH: $p" >&2; exit 1; }
done

TX="$STATE_DIR/transaction-v2-$TARGET"
JOURNAL="$TX/journal.json"
OLD_BACKEND_FILE="$TX/backend-rollback.yaml"
OLD_FRONTEND_FILE="$TX/frontend-rollback.yaml"
OLD_ENV="$TX/backend-rollback.env"

read_journal() { python3 -I - "$JOURNAL" "$1" <<'PY'
import json,sys
from pathlib import Path
j=json.loads(Path(sys.argv[1]).read_text())
key=sys.argv[2]
if key=='state': print(j['state'])
elif key in ('backend','frontend'): print(j['previous'][key]['image_reference'])
elif key=='old_commit': print(j['previous']['backend']['app_commit'])
else: raise SystemExit('INVALID_JOURNAL_FIELD')
PY
}
advance() { python3 -I "$TRUSTED/deployment-journal.py" "$JOURNAL" "$1"; }
image_id() { docker image inspect "$1" --format '{{.Id}}'; }
container_image_id() { docker inspect "$1" --format '{{.Image}}'; }

backend_compose() {
  local compose=$1 image=$2 commit=$3 env_file=$4
  env BACKEND_IMAGE="$image" BACKEND_ENV_FILE="$env_file" APP_COMMIT="$commit" \
    docker compose -p backend -f "$compose" up -d --no-deps --no-build --pull never \
    --wait --wait-timeout 120 backend
}
frontend_compose() {
  local compose=$1 image=$2
  env FRONTEND_IMAGE="$image" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
    docker compose -p frontend -f "$compose" up -d --no-deps --no-build --pull never \
    --wait --wait-timeout 120 frontend
}
check_backend() {
  local i
  for i in $(seq 1 24); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null |
      python3 -I -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="healthy" and d["database"]["status"]=="reachable" and d["migrations"]["status"]=="current"' 2>/dev/null; then return 0; fi
    sleep 5
  done
  echo 'BACKEND_HEALTH_FAILED' >&2; return 1
}
check_frontend() {
  local i
  for i in $(seq 1 24); do
    if curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:3000/login 2>/dev/null; then return 0; fi
    sleep 5
  done
  echo 'FRONTEND_HEALTH_FAILED' >&2; return 1
}
verify_running_image() {
  local actual expected
  expected=$(image_id "$2")
  actual=$(container_image_id "$1")
  [[ $actual == "$expected" ]] || { echo "RUNNING_IMAGE_MISMATCH: $1" >&2; return 1; }
}

# No database downgrade is implemented. Permit only matching Alembic heads.
check_migration_compatibility() {
  local oldhead newhead
  oldhead=$(docker run --rm --network none --pull never --entrypoint alembic "$1" heads)
  newhead=$(docker run --rm --network none --pull never --entrypoint alembic "$2" heads)
  [[ -n "$oldhead" && "$oldhead" == "$newhead" ]] || {
    echo 'MIGRATION_HEAD_CHANGED_OR_UNAVAILABLE: automatic deployment blocked' >&2
    return 1
  }
  echo 'MIGRATION_HEAD_UNCHANGED'
}

# At most one unfinished transaction at a time.
check_other_transactions() {
  python3 -I - "$STATE_DIR" "$TARGET" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); target=sys.argv[2]
for p in root.glob('transaction-v2-*/journal.json'):
    if p.parent.name == 'transaction-v2-'+target: continue
    try: state=json.loads(p.read_text())['state']
    except (ValueError,KeyError,OSError): raise SystemExit('INVALID_EXISTING_JOURNAL: '+str(p))
    if state not in ('deployed','rolled_back'):
        raise SystemExit('UNFINISHED_TRANSACTION: '+str(p))
print('NO_OTHER_PENDING_TRANSACTIONS')
PY
}

# Roll back using per-transaction root-only snapshots, not today's mutable configuration.
rollback() {
  local old_backend old_frontend old_commit errors=0
  old_backend=$(read_journal backend)
  old_frontend=$(read_journal frontend)
  old_commit=$(read_journal old_commit)
  echo '=== ROLLBACK ===' >&2
  [[ -r "$OLD_BACKEND_FILE" && -r "$OLD_FRONTEND_FILE" && -r "$OLD_ENV" ]] || {
    echo 'ROLLBACK_SNAPSHOT_MISSING' >&2; return 1;
  }
  backend_compose "$OLD_BACKEND_FILE" "$old_backend" "$old_commit" "$OLD_ENV" || errors=1
  frontend_compose "$OLD_FRONTEND_FILE" "$old_frontend" || errors=1
  verify_running_image standa-hub-backend "$old_backend" || errors=1
  verify_running_image standa-hub-frontend "$old_frontend" || errors=1
  check_backend || errors=1
  check_frontend || errors=1
  if (( errors )); then echo 'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  advance rolled_back
  echo 'ROLLBACK_VERIFIED'
}

on_exit() {
  local code=$?
  trap - EXIT INT TERM
  if (( code != 0 )) && [[ $MODE == --apply && -f $JOURNAL ]]; then
    local state
    state=$(read_journal state) || state=invalid
    if [[ $state == deploying || $state == verifying ]]; then
      advance rollback_required && rollback || echo 'MANUAL_RECOVERY_REQUIRED' >&2
    fi
  fi
  exit "$code"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ $MODE == --recover ]]; then
  [[ -f $JOURNAL ]] || { echo 'JOURNAL_NOT_FOUND' >&2; exit 1; }
  state=$(read_journal state)
  case $state in
    deploying|verifying) advance rollback_required ;;
    rollback_required) ;;
    *) echo "NOT_RECOVERABLE_STATE: $state" >&2; exit 1 ;;
  esac
  rollback
  exit 0
fi

check_other_transactions
[[ ! -e $TX ]] || { echo 'TRANSACTION_ALREADY_EXISTS' >&2; exit 1; }

# Inspect current state before allowing any deployment.
python3 -I - <<'PY'
import json,subprocess
for service in ('backend','frontend'):
    name='standa-hub-'+service
    c=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
    labels=c['Config'].get('Labels') or {}
    assert c['State']['Running'], name+' not running'
    assert labels.get('com.docker.compose.project')==service, name+' Compose project changed'
    assert labels.get('com.docker.compose.service')==service, name+' Compose service changed'
print('PRODUCTION_CONTAINERS_VERIFIED')
PY
check_backend
check_frontend

BACKEND_OLD=$(docker inspect standa-hub-backend --format '{{.Config.Image}}')
FRONTEND_OLD=$(docker inspect standa-hub-frontend --format '{{.Config.Image}}')
OLD_COMMIT=$(docker inspect standa-hub-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^APP_COMMIT=//p' | head -n1)
[[ "$OLD_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo 'CURRENT_COMMIT_UNKNOWN' >&2; exit 1; }
BACKEND_NEW="standa-hub-backend:$TARGET"
FRONTEND_NEW="standa-hub-frontend:$TARGET"

if [[ $OLD_COMMIT == "$TARGET" ]]; then
  verify_running_image standa-hub-backend "$BACKEND_NEW"
  verify_running_image standa-hub-frontend "$FRONTEND_NEW"
  echo 'ALREADY_DEPLOYED'
  exit 0
fi

# CI runs unprivileged. Remaining checks use pinned root-owned scripts.
runuser -u standa -- "$ROOT/deploy/scripts/check-ci.sh" "$TARGET"
python3 -I "$TRUSTED/check-backup.py"
python3 -I "$TRUSTED/verify-release.py" "$TARGET"
for service in backend frontend; do
  image="standa-hub-$service:$TARGET"
  [[ $(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || {
    echo "TARGET_IMAGE_UNVERIFIED: $image" >&2; exit 1;
  }
done
check_migration_compatibility "$BACKEND_OLD" "$BACKEND_NEW"

# Compose must be valid before the transactional state is created.
env BACKEND_IMAGE="$BACKEND_NEW" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$TARGET" \
  docker compose -p backend -f "$BACKEND_MANAGED" config --quiet
env FRONTEND_IMAGE="$FRONTEND_NEW" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
  docker compose -p frontend -f "$FRONTEND_MANAGED" config --quiet

echo 'DEPLOYMENT_PREFLIGHT_OK'
if [[ $MODE == --check ]]; then echo 'NO_PRODUCTION_CHANGES'; exit 0; fi

# Snapshot rollback material before touching any containers; keep secrets root-only.
mkdir -m 700 "$TX"
cp "$BACKEND_MANAGED" "$OLD_BACKEND_FILE"
cp "$FRONTEND_MANAGED" "$OLD_FRONTEND_FILE"
cp "$BACKEND_ENV_FILE" "$OLD_ENV"
chmod 600 "$OLD_BACKEND_FILE" "$OLD_FRONTEND_FILE" "$OLD_ENV"

python3 -I - "$JOURNAL" "$TARGET" "$BACKEND_OLD" "$FRONTEND_OLD" "$OLD_COMMIT" \
 "$BACKEND_NEW" "$FRONTEND_NEW" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); d={'state':'prepared','target_commit':sys.argv[2],
'created_at':datetime.now(timezone.utc).isoformat(),
'previous':{'backend':{'image_reference':sys.argv[3], 'app_commit':sys.argv[5]},
            'frontend':{'image_reference':sys.argv[4]}},
 'target':{'backend':{'image_reference':sys.argv[6]},
           'frontend':{'image_reference':sys.argv[7]}}}
fd,temp=tempfile.mkstemp(dir=p.parent,prefix='.journal.')
try:
    with os.fdopen(fd,'w') as f:
        json.dump(d,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.chmod(temp,0o600);os.replace(temp,p)
    dirfd=os.open(p.parent,os.O_RDONLY)
    try: os.fsync(dirfd)
    finally: os.close(dirfd)
finally:
    if os.path.exists(temp): os.unlink(temp)
PY
advance deploying

echo '=== DEPLOY BACKEND ==='
backend_compose "$BACKEND_MANAGED" "$BACKEND_NEW" "$TARGET" "$BACKEND_ENV_FILE"
verify_running_image standa-hub-backend "$BACKEND_NEW"
check_backend

echo '=== DEPLOY FRONTEND ==='
frontend_compose "$FRONTEND_MANAGED" "$FRONTEND_NEW"
verify_running_image standa-hub-frontend "$FRONTEND_NEW"
check_frontend
advance verifying
check_backend
check_frontend
advance deployed
echo 'PRODUCTION_DEPLOYMENT_OK'
