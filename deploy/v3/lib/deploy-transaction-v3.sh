#!/usr/bin/env bash
# MRK-108 - transaction for future commits. Use only through the shared maintenance lock.
set -Eeuo pipefail
umask 077

ROOT=/home/standa/projects/jarvis-mrk101
TRUSTED=/usr/local/lib/standa-hub/mrk108
STATE_DIR=/var/lib/standa-hub/deployments
BACKEND_ENV_FILE=/srv/standa-hub/backend/.env.production
NEXT_PUBLIC_API_URL=https://<tailnet-host>:8443
BACKEND_MANAGED="$TRUSTED/backend-managed.yaml"
FRONTEND_MANAGED="$TRUSTED/frontend-managed.yaml"

[[ $# == 2 && ($1 == --check || $1 == --apply || $1 == --recover) && $2 =~ ^[a-f0-9]{40}$ ]] || {
  echo 'Usage: deploy-transaction-v3.sh --check|--apply|--recover SHA' >&2; exit 2;
}
MODE=$1 TARGET=$2
[[ $EUID == 0 && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ -d $STATE_DIR && ! -L $STATE_DIR && $(stat -c '%u:%a' "$STATE_DIR") == 0:700 ]] || { echo 'INSECURE_STATE_DIR' >&2; exit 1; }
for p in "$TRUSTED" "$TRUSTED/deployment-journal.py" "$TRUSTED/check-backup.py" "$TRUSTED/verify-release.py" "$BACKEND_MANAGED" "$FRONTEND_MANAGED"; do
  [[ -e $p && ! -L $p && $(stat -c '%u' "$p") == 0 ]] || { echo "UNTRUSTED_PATH: $p" >&2; exit 1; }
done

TX="$STATE_DIR/transaction-v3-$TARGET"
JOURNAL="$TX/journal.json"
OLD_B="$TX/backend.json"
OLD_F="$TX/frontend.json"
BACKEND_NEW="standa-hub-backend:$TARGET"
FRONTEND_NEW="standa-hub-frontend:$TARGET"

jval() {
  python3 -I - "$JOURNAL" "$1" <<'PY'
import json,sys
j=json.load(open(sys.argv[1])); field=sys.argv[2]
if field == 'state': print(j['state'])
elif field in ('backend','frontend'): print(j['previous'][field]['image_id'])
else: raise ValueError(field)
PY
}
advance() { python3 -I "$TRUSTED/deployment-journal.py" "$JOURNAL" "$1"; }
image_id() { docker image inspect "$1" --format '{{.Id}}'; }
running_id() { docker inspect "$1" --format '{{.Image}}'; }
check_image() { [[ $(running_id "$1") == "$(image_id "$2")" ]] || { echo "IMAGE_MISMATCH: $1" >&2; return 1; }; }

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
    if state not in ('deployed','rolled_back'):
        raise SystemExit('PENDING_TRANSACTION: '+str(p))
for p in root.glob('transaction-v3-*'):
    if p.name != 'transaction-v3-'+target and p.is_dir() and not (p/'journal.json').exists():
        raise SystemExit('INCOMPLETE_TRANSACTION_DIRECTORY: '+str(p))
print('NO_PENDING_TRANSACTIONS')
PY
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

# Image IDs, not mutable release names, are the authority for rollback.
# Compose resolves a unique per-transaction local rollback tag whose ID is checked before use.
rollback() {
  local expected_b expected_f rb rf failures=0
  [[ -f $OLD_B && -f $OLD_F && -f $JOURNAL ]] || { echo 'ROLLBACK_SNAPSHOT_MISSING' >&2; return 1; }
  expected_b=$(jval backend); expected_f=$(jval frontend)
  rb="standa-hub-backend:rollback-$TARGET"; rf="standa-hub-frontend:rollback-$TARGET"
  [[ $(image_id "$rb") == "$expected_b" && $(image_id "$rf") == "$expected_f" ]] || { echo 'ROLLBACK_IMAGE_ID_CHANGED' >&2; return 1; }
  echo '=== RESTORE SNAPSHOT ===' >&2
  env BACKEND_IMAGE="$rb" docker compose -p backend -f "$OLD_B" -f "$TX/override-backend.json" \
    up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 backend || failures=1
  env FRONTEND_IMAGE="$rf" docker compose -p frontend -f "$OLD_F" -f "$TX/override-frontend.json" \
    up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 frontend || failures=1
  [[ $(running_id standa-hub-backend) == "$expected_b" ]] || failures=1
  [[ $(running_id standa-hub-frontend) == "$expected_f" ]] || failures=1
  check_backend || failures=1
  check_frontend || failures=1
  if (( failures )); then echo 'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  advance rolled_back
  echo 'ROLLBACK_VERIFIED'
}

on_exit() {
  local rc=$? state
  trap - EXIT INT TERM
  if (( rc != 0 )) && [[ $MODE == --apply && -f $JOURNAL ]]; then
    state=$(jval state) || state=invalid
    if [[ $state == deploying || $state == verifying ]]; then
      advance rollback_required && rollback || echo 'MANUAL_RECOVERY_REQUIRED' >&2
    fi
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ $MODE == --recover ]]; then
  [[ -f $JOURNAL ]] || { echo 'JOURNAL_NOT_FOUND' >&2; exit 1; }
  state=$(jval state)
  case "$state" in
    deploying|verifying) advance rollback_required ;;
    rollback_required) ;;
    *) echo "NOT_RECOVERABLE: $state" >&2; exit 1 ;;
  esac
  rollback
  exit 0
fi

check_transactions
[[ ! -e $TX ]] || { echo 'TRANSACTION_ALREADY_EXISTS' >&2; exit 1; }

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
OLD_COMMIT=$(docker inspect standa-hub-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^APP_COMMIT=//p' | head -n1)
[[ $OLD_COMMIT =~ ^[a-f0-9]{40}$ ]] || { echo 'CURRENT_COMMIT_UNKNOWN' >&2; exit 1; }
OLD_BACKEND=$(docker inspect standa-hub-backend --format '{{.Config.Image}}')
OLD_FRONTEND=$(docker inspect standa-hub-frontend --format '{{.Config.Image}}')
[[ $(docker inspect standa-hub-frontend --format '{{index .Config.Labels "com.docker.compose.project"}}') == frontend ]] || exit 1

if [[ $OLD_COMMIT == "$TARGET" ]]; then
  prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND"
  check_image standa-hub-backend "$BACKEND_NEW"
  check_image standa-hub-frontend "$FRONTEND_NEW"
  echo 'ALREADY_DEPLOYED'
  exit 0
fi

# Enforce ancestry even if transaction is invoked outside the updater.
runuser -u standa -- git -C "$ROOT" merge-base --is-ancestor "$OLD_COMMIT" "$TARGET" || { echo 'NON_FAST_FORWARD_BLOCKED' >&2; exit 1; }
runuser -u standa -- "$ROOT/deploy/scripts/check-ci.sh" "$TARGET"
python3 -I "$TRUSTED/check-backup.py"
python3 -I "$TRUSTED/verify-release.py" "$TARGET"
for service in backend frontend; do
  image="standa-hub-$service:$TARGET"
  [[ $(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || { echo "TARGET_IMAGE_UNVERIFIED: $image" >&2; exit 1; }
done
check_migrations "$OLD_BACKEND" "$BACKEND_NEW"
prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND"
env BACKEND_IMAGE="$BACKEND_NEW" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$TARGET" \
  docker compose -p backend -f "$BACKEND_MANAGED" config --quiet
env FRONTEND_IMAGE="$FRONTEND_NEW" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
  docker compose -p frontend -f "$FRONTEND_MANAGED" config --quiet

echo 'DEPLOYMENT_PREFLIGHT_OK'
if [[ $MODE == --check ]]; then echo 'NO_PRODUCTION_CHANGES'; exit 0; fi

# Re-run snapshot in apply mode only after transaction directory exists.
mkdir -m 700 "$TX"
prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND" 1
OLD_B_ID=$(running_id standa-hub-backend)
OLD_F_ID=$(running_id standa-hub-frontend)
[[ $(image_id "$OLD_BACKEND") == "$OLD_B_ID" && $(image_id "$OLD_FRONTEND") == "$OLD_F_ID" ]] || { echo 'CURRENT_IMAGE_TAG_DRIFT' >&2; exit 1; }
docker image tag "$OLD_B_ID" "standa-hub-backend:rollback-$TARGET"
docker image tag "$OLD_F_ID" "standa-hub-frontend:rollback-$TARGET"
[[ $(image_id "standa-hub-backend:rollback-$TARGET") == "$OLD_B_ID" && $(image_id "standa-hub-frontend:rollback-$TARGET") == "$OLD_F_ID" ]] || exit 1
python3 -I - "$TX" "$TARGET" "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND" "$OLD_B_ID" "$OLD_F_ID" "$BACKEND_NEW" "$FRONTEND_NEW" <<'PY'
import json,os,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
p=Path(sys.argv[1]);target=sys.argv[2]
for s in ('backend','frontend'):
    (p/f'override-{s}.json').write_text(json.dumps({'services':{s:{'image':f'standa-hub-{s}:rollback-{target}','pull_policy':'never'}}})+'\n')
    (p/f'override-{s}.json').chmod(0o600)
d={'state':'prepared','target_commit':target,'created_at':datetime.now(timezone.utc).isoformat(),
 'previous':{'backend':{'image_reference':sys.argv[4],'image_id':sys.argv[6],'app_commit':sys.argv[3]},
             'frontend':{'image_reference':sys.argv[5],'image_id':sys.argv[7]}},
 'target':{'backend':{'image_reference':sys.argv[8]},'frontend':{'image_reference':sys.argv[9]}}}
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
advance deploying

echo '=== DEPLOY BACKEND ==='
env BACKEND_IMAGE="$BACKEND_NEW" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$TARGET" \
  docker compose -p backend -f "$BACKEND_MANAGED" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 backend
check_image standa-hub-backend "$BACKEND_NEW"
check_backend
echo '=== DEPLOY FRONTEND ==='
env FRONTEND_IMAGE="$FRONTEND_NEW" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
  docker compose -p frontend -f "$FRONTEND_MANAGED" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 frontend
check_image standa-hub-frontend "$FRONTEND_NEW"
check_frontend
advance verifying
check_backend
check_frontend
advance deployed
echo 'PRODUCTION_DEPLOYMENT_OK'
