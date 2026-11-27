#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT=/home/standa/projects/jarvis-mrk101
SHARED=/srv/standa-hub/shared
STATE_DIR=/var/lib/standa-hub/deployments
TRUSTED=/usr/local/lib/standa-hub/mrk108
BACKEND_ENV_FILE=/srv/standa-hub/backend/.env.production
NEXT_PUBLIC_API_URL=https://<tailnet-host>:8443
EXPECTED_TARGET=32db7b89049316842de3f65a5b70879605e833eb
JOURNAL="$STATE_DIR/deployment-transaction-$EXPECTED_TARGET.json"
BACKEND_OLD=standa-hub-backend:baseline-mrk108
FRONTEND_OLD=standa-hub-frontend:baseline-mrk108
BACKEND_NEW="standa-hub-backend:$EXPECTED_TARGET"
FRONTEND_NEW="standa-hub-frontend:$EXPECTED_TARGET"
BACKEND_MANAGED="$TRUSTED/backend-managed.yaml"
FRONTEND_MANAGED="$TRUSTED/frontend-managed.yaml"
BACKEND_ORIGINAL="$TRUSTED/backend-original.yaml"
FRONTEND_ORIGINAL="$TRUSTED/frontend-original.yaml"

[[ $EUID -eq 0 ]] || { echo 'RUN_AS_ROOT_THROUGH_MAINTENANCE_LOCK' >&2; exit 1; }
[[ -r /proc/self/fd/9 ]] || { echo 'MAINTENANCE_LOCK_FD_MISSING' >&2; exit 1; }
[[ $# -eq 2 ]] || { echo 'Usage: deploy-transaction-mrk108.sh --check|--apply|--recover SHA' >&2; exit 2; }
MODE=$1
TARGET=$2
[[ "$TARGET" == "$EXPECTED_TARGET" ]] || { echo 'UNAPPROVED_TARGET' >&2; exit 1; }
[[ "$MODE" == '--check' || "$MODE" == '--apply' || "$MODE" == '--recover' ]] || exit 2

journal_state() {
  python3 - "$JOURNAL" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); print(json.loads(p.read_text())["state"] if p.exists() else "missing")
PY
}
advance() { python3 "$TRUSTED/deployment-journal.py" "$JOURNAL" "$1"; }

compose_backend() {
  env BACKEND_IMAGE="$1" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$TARGET" \
    docker compose -p backend -f "$BACKEND_MANAGED" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 backend
}
compose_frontend() {
  env FRONTEND_IMAGE="$1" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
    docker compose -p frontend -f "$FRONTEND_MANAGED" up -d --no-deps --no-build --pull never --wait --wait-timeout 120 frontend
}

restore_backend() {
  docker compose -p backend -f "$BACKEND_ORIGINAL" \
    -f "$STATE_DIR/rollback-mrk108-backend.yaml" \
    up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 backend
}
restore_frontend() {
  docker compose -p frontend -f "$FRONTEND_ORIGINAL" \
    -f "$STATE_DIR/rollback-mrk108-frontend.yaml" \
    up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 frontend
}

check_backend_http() {
  local i
  for i in $(seq 1 24); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null |
      python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="healthy" and d["database"]["status"]=="reachable" and d["migrations"]["status"]=="current"' 2>/dev/null; then
      return 0
    fi
    sleep 5
  done
  echo 'BACKEND_HEALTH_FAILED' >&2
  return 1
}
check_frontend_http() {
  local i
  for i in $(seq 1 24); do
    if curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:3000/login; then return 0; fi
    sleep 5
  done
  echo 'FRONTEND_HEALTH_FAILED' >&2
  return 1
}
check_image() {
  local name=$1 reference=$2 expected actual
  expected=$(docker image inspect "$reference" --format '{{.Id}}')
  actual=$(docker inspect "$name" --format '{{.Image}}')
  [[ "$actual" == "$expected" ]] || { echo "IMAGE_MISMATCH: $name" >&2; return 1; }
}

verify_baseline_tags() {
  python3 - "$SHARED/deployment-plan-$TARGET.json" "$BACKEND_OLD" "$FRONTEND_OLD" <<'PYCODE'
import json, subprocess, sys
from pathlib import Path
plan=json.loads(Path(sys.argv[1]).read_text())
for service,tag in (("backend",sys.argv[2]),("frontend",sys.argv[3])):
    got=subprocess.check_output(["docker","image","inspect",tag,"--format","{{.Id}}"],text=True).strip()
    assert got==plan["previous"][service]["image_id"], f"BASELINE_TAG_CHANGED: {service}"
print("ROLLBACK_IMAGES_PINNED")
PYCODE
}

# These two recovery override files are created exclusively before switching anything.
create_recovery_files() {
  python3 - "$STATE_DIR" "$BACKEND_OLD" "$FRONTEND_OLD" <<'PY'
import os,sys
from pathlib import Path
p=Path(sys.argv[1]); p.mkdir(parents=True,exist_ok=True)
for name,image in (("backend",sys.argv[2]),("frontend",sys.argv[3])):
    file=p/f"rollback-mrk108-{name}.yaml"
    data=f"services:\n  {name}:\n    image: {image}\n    pull_policy: never\n"
    if file.exists():
        if file.read_text()!=data: raise SystemExit(f"RECOVERY_OVERRIDE_CONFLICT: {file}")
    else:
        with file.open('x') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        file.chmod(0o600)
PY
}

rollback() {
  echo '=== RESTORE ORIGINAL PRODUCTION CONFIGURATIONS ===' >&2
  local failures=0
  restore_backend || failures=1
  restore_frontend || failures=1
  check_image standa-hub-backend "$BACKEND_OLD" || failures=1
  check_image standa-hub-frontend "$FRONTEND_OLD" || failures=1
  check_backend_http || failures=1
  check_frontend_http || failures=1
  if (( failures )); then echo 'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  advance rolled_back
  echo 'ROLLBACK_VERIFIED'
}

on_exit() {
  local code=$?
  trap - EXIT ERR INT TERM
  if (( code != 0 )) && [[ "$MODE" == '--apply' ]] && [[ -f "$JOURNAL" ]]; then
    local state
    state=$(journal_state) || state=unknown
    if [[ "$state" == deploying || "$state" == verifying ]]; then
      advance rollback_required || { echo 'JOURNAL_UPDATE_FAILED' >&2; exit "$code"; }
      rollback || exit "$code"
    fi
  fi
  exit "$code"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$MODE" == '--recover' ]]; then
  verify_baseline_tags
  [[ $(journal_state) == rollback_required || $(journal_state) == deploying || $(journal_state) == verifying ]] || { echo 'NO_INTERRUPTED_TRANSACTION'; exit 1; }
  state=$(journal_state)
  if [[ "$state" != rollback_required ]]; then advance rollback_required; fi
  rollback
  exit 0
fi

[[ ! -e "$JOURNAL" ]] || { echo "TRANSACTION_ALREADY_EXISTS: $(journal_state)" >&2; exit 1; }
[[ -r "$TRUSTED/check-production-baseline.py" ]] || exit 1
[[ -r "$BACKEND_ORIGINAL" && -r "$FRONTEND_ORIGINAL" ]] || exit 1
[[ -r "$BACKEND_MANAGED" && -r "$FRONTEND_MANAGED" ]] || exit 1

cd "$ROOT"
echo '=== CI / BACKUP / RELEASE / BASELINE ==='
runuser -u standa -- "$ROOT/deploy/scripts/check-ci.sh" "$TARGET"
python3 "$TRUSTED/check-backup.py"
python3 "$TRUSTED/verify-release.py" "$TARGET"
python3 "$TRUSTED/check-production-baseline.py" "$TARGET"
check_backend_http
check_frontend_http
check_image standa-hub-backend "$BACKEND_OLD"
check_image standa-hub-frontend "$FRONTEND_OLD"
verify_baseline_tags

# The first rollout is deliberately pinned to the already-tested commit.
for image in "$BACKEND_NEW" "$FRONTEND_NEW"; do
  [[ $(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || exit 1
done

if [[ "$MODE" == '--check' ]]; then
  echo 'DEPLOYMENT_PREFLIGHT_OK'
  echo 'NO_PRODUCTION_CHANGES'
  exit 0
fi

create_recovery_files
python3 - "$JOURNAL" "$TARGET" "$BACKEND_OLD" "$FRONTEND_OLD" "$BACKEND_NEW" "$FRONTEND_NEW" <<'PY'
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); data={"state":"prepared","target_commit":sys.argv[2],"created_at":datetime.now(timezone.utc).isoformat(),"previous":{"backend":{"image_reference":sys.argv[3]},"frontend":{"image_reference":sys.argv[4]}},"target":{"backend":{"image_reference":sys.argv[5]},"frontend":{"image_reference":sys.argv[6]}}}
with p.open('x') as f:
    json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
p.chmod(0o600)
fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
PY
advance deploying

echo '=== DEPLOY BACKEND ==='
compose_backend "$BACKEND_NEW"
check_image standa-hub-backend "$BACKEND_NEW"
check_backend_http

echo '=== DEPLOY FRONTEND ==='
compose_frontend "$FRONTEND_NEW"
check_image standa-hub-frontend "$FRONTEND_NEW"
check_frontend_http
advance verifying
check_backend_http
check_frontend_http
advance deployed
echo 'PRODUCTION_DEPLOYMENT_OK'
