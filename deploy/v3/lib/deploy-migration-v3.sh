#!/usr/bin/env bash
# MRK-114 - controlled deployment of a release that changes the Alembic head. Run BY HAND only, through the shared
# maintenance lock (never from the timer):
#   with-deployment-lock.sh deploy-migration-v3.sh --check   SHA   # preflight + rehearsal on a copy, no production change
#   with-deployment-lock.sh deploy-migration-v3.sh --apply   SHA   # fresh backup, rehearsal, migrate, deploy
#   with-deployment-lock.sh deploy-migration-v3.sh --recover SHA   # finish / undo an interrupted transaction
#
# The automatic updater (auto-update-v3.sh / deploy-transaction-v3.sh) keeps refusing such a commit: it compares the
# heads in the old and new image, never the database, so a database migrated in advance does not unlock it.
# Target images must already be built from the verified release with a provenance record - the updater does that in
# its run before it stops on MIGRATION_HEAD_CHANGED.
#
# Order (journal $STATE_DIR/migration-v3-<SHA>/journal.json, helper mrk108/migration-journal.py):
#   preflight: lock, trusted paths, no pending deploy/migration transaction, healthy production on an ancestor commit,
#     CI gate, verified release + image provenance, old/new head from the images (must differ), production database
#     exactly at the old head, static check of every migration in between (additive only, check-migration.py)
#   --apply: fresh backup (BACKUP_CMD) + check-backup -> snapshot + rollback tags -> journal "prepared" (staging dir,
#     atomic rename) -> REHEARSAL on a throwaway PostgreSQL restored from that backup (internal network, tmpfs, no
#     ports): old app baseline, `alembic upgrade head` with the new image, new app healthy + ORM smoke, OLD app on the
#     migrated copy ORM smoke + database reachable -> "rehearsed" -> "db_migrating" -> `alembic upgrade head` on
#     production -> database verified at the new head -> "db_migrated" -> "deploying" (managed templates, as every
#     deploy) -> health -> "verifying" -> "deployed".
#   failure before db_migrating: "aborted" (containers verified unchanged, database at the old head).
#   failure during db_migrating: the production revision decides - old head -> "aborted"; new head -> "db_migrated"
#     (the old application keeps running, its compatibility was rehearsed) and --recover rolls forward; else manual.
#   failure while deploying/verifying: "app_rollback_required" -> the previous images through the managed templates ->
#     "rolled_back_app" ONLY after the old application passes the compatibility check on the PRODUCTION database
#     (ORM smoke + database reachable + its /health showing the database at the new head). "migrations: mismatch"
#     alone is never success. The database is never downgraded automatically.
# Configuration: DEPLOY_* variables with production defaults (tests: backend/tests/test_deploy_migration_v3.py).
set -Eeuo pipefail
umask 077

ROOT=${DEPLOY_ROOT:-/home/standa/projects/jarvis-mrk101}
TRUSTED=${DEPLOY_TRUSTED:-/usr/local/lib/standa-hub/mrk108}
STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/standa-hub/deployments}
RELEASES=${DEPLOY_RELEASES:-/srv/standa-hub/releases}
BACKEND_ENV_FILE=${DEPLOY_BACKEND_ENV_FILE:-/srv/standa-hub/backend/.env.production}
NEXT_PUBLIC_API_URL=${DEPLOY_NEXT_PUBLIC_API_URL:-https://<tailnet-host>:8443}
BACKUP_CMD=${DEPLOY_BACKUP_CMD:-/usr/local/lib/standa-hub/backup.sh}
BACKUP_ROOT=${DEPLOY_BACKUP_ROOT:-/srv/standa-hub-data/backups}
PROD_NETWORK=${DEPLOY_PROD_NETWORK:-postgres_default}
PROD_DB_CONTAINER=${DEPLOY_PROD_DB_CONTAINER:-standa-postgres}
DB_USER=${DEPLOY_DB_USER:-standa_hub}
DB_NAME=${DEPLOY_DB_NAME:-standa_hub}
REQUIRED_UID=${DEPLOY_REQUIRED_UID:-0}
GIT_USER=${DEPLOY_GIT_USER-standa}
HEALTH_TRIES=${DEPLOY_HEALTH_TRIES:-24}
HEALTH_SLEEP=${DEPLOY_HEALTH_SLEEP:-5}
BACKEND_MANAGED="$TRUSTED/backend-managed.yaml"
FRONTEND_MANAGED="$TRUSTED/frontend-managed.yaml"

[[ $# == 2 && ($1 == --check || $1 == --apply || $1 == --recover) && $2 =~ ^[a-f0-9]{40}$ ]] || {
  echo 'Usage: deploy-migration-v3.sh --check|--apply|--recover SHA' >&2; exit 2;
}
MODE=$1 TARGET=$2
[[ $EUID == "$REQUIRED_UID" && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ $NEXT_PUBLIC_API_URL == https://* && $NEXT_PUBLIC_API_URL != *'<'* ]] || { echo 'NEXT_PUBLIC_API_URL_NOT_CONFIGURED' >&2; exit 1; }
[[ -d $STATE_DIR && ! -L $STATE_DIR && $(stat -c '%u:%a' "$STATE_DIR") == "$REQUIRED_UID:700" ]] || { echo 'INSECURE_STATE_DIR' >&2; exit 1; }
trusted_path() {
  local path=$1 mode
  [[ -e $path && ! -L $path && $(stat -c %u -- "$path") == "$REQUIRED_UID" ]] || return 1
  mode=$(stat -c %a -- "$path") || return 1
  (( (8#$mode & 0022) == 0 ))
}
for p in "$TRUSTED" "$TRUSTED/migration-journal.py" "$TRUSTED/check-migration.py" "$TRUSTED/compat-smoke.py" \
         "$TRUSTED/check-backup.py" "$TRUSTED/verify-release.py" "$TRUSTED/check-ci.sh" "$BACKEND_MANAGED" \
         "$FRONTEND_MANAGED" "$0" "$(dirname -- "$(readlink -f -- "$0")")" \
         "$BACKUP_CMD" "$(dirname -- "$BACKUP_CMD")"; do
  trusted_path "$p" || { echo "UNTRUSTED_PATH: $p" >&2; exit 1; }
done
# BACKUP_CMD runs as root: a root-owned regular file, no symlink, in a trusted directory (Codex review P1)
[[ -f $BACKUP_CMD && ! -L $BACKUP_CMD && $BACKUP_CMD == /* ]] || { echo "UNTRUSTED_PATH: $BACKUP_CMD" >&2; exit 1; }

FINAL="$STATE_DIR/migration-v3-$TARGET"
PROVENANCE="$STATE_DIR/provenance/$TARGET.json"
BACKEND_NEW="standa-hub-backend:$TARGET"
FRONTEND_NEW="standa-hub-frontend:$TARGET"
REHEARSAL="standa-hub-rehearsal-${TARGET:0:12}"
WORK=$(mktemp -d)
set_tx() { TX=$1; JOURNAL="$TX/journal.json"; OLD_B="$TX/backend.json"; OLD_F="$TX/frontend.json"; }
set_tx "$FINAL"

as_git_user() { if [[ -n $GIT_USER ]]; then runuser -u "$GIT_USER" -- "$@"; else "$@"; fi; }
jval() {
  python3 -I - "$JOURNAL" "$1" <<'PY'
import json,sys
j=json.load(open(sys.argv[1])); f=sys.argv[2]
v={'state':lambda: j['state'], 'backend':lambda: j['previous']['backend']['image_id'],
   'frontend':lambda: j['previous']['frontend']['image_id'], 'previous_commit':lambda: j['previous']['backend']['app_commit'],
   'target_backend':lambda: j['target']['backend']['image_id'], 'target_frontend':lambda: j['target']['frontend']['image_id'],
   'old_head':lambda: j['old_head'], 'new_head':lambda: j['new_head']}[f]()
print(v)
PY
}
advance() { python3 -I "$TRUSTED/migration-journal.py" "$JOURNAL" "$@"; }
image_id() { docker image inspect "$1" --format '{{.Id}}'; }
running_id() { docker inspect "$1" --format '{{.Image}}'; }
check_running() { [[ $(running_id "$1") == "$2" ]] || { echo "IMAGE_MISMATCH: $1" >&2; return 1; }; }
fsync_dir() { python3 -I -c 'import os,sys; fd=os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)' "$1"; }
utc_stamp() { date -u +%Y%m%dT%H%M%SZ; }
image_head() { docker run --rm --network none --pull never --entrypoint alembic "$1" heads | awk 'NF {print $1}' | sort | paste -sd, -; }
prod_db_revision() {
  docker exec "$PROD_DB_CONTAINER" psql -X -U "$DB_USER" -d "$DB_NAME" -tAc 'SELECT version_num FROM alembic_version' |
    awk 'NF {print $1}' | sort | paste -sd, -
}

# ---------- health (production) ----------
health_json() { curl -sS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null || true; }
check_backend() {  # strict: the deployed code and the database agree
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if health_json | python3 -I -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="healthy" and d["database"]["status"]=="reachable" and d["migrations"]["status"]=="current"' 2>/dev/null; then return 0; fi
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
# Old code on the newer schema: reachable database whose revision is the NEW head (old code reports a mismatch, which
# alone proves nothing) + the ORM smoke of every mapped entity inside the running container + frontend /login.
check_old_app_compatible() {
  local new_head=$1 i ok=0
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if health_json | python3 -I -c '
import json,sys
d=json.load(sys.stdin); new=sys.argv[1]
assert d["database"]["status"]=="reachable"
assert ",".join(sorted(d["migrations"].get("current") or []))==new
' "$new_head" 2>/dev/null; then ok=1; break; fi
    sleep "$HEALTH_SLEEP"
  done
  (( ok )) || { echo 'OLD_APP_DATABASE_CHECK_FAILED' >&2; return 1; }
  docker exec -i standa-hub-backend python - <"$TRUSTED/compat-smoke.py" | grep -q '^ORM_SMOKE_OK' || {
    echo 'OLD_APP_ORM_SMOKE_FAILED' >&2; return 1; }
  check_frontend
  echo 'OLD_APP_COMPATIBLE_WITH_MIGRATED_DATABASE'
}

check_pending() {
  python3 -I - "$STATE_DIR" "$TARGET" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); target=sys.argv[2]
terminal={'transaction':('deployed','rolled_back','aborted'),'migration':('deployed','aborted','rolled_back_app')}
for kind, pattern in (('transaction','transaction-v2-*'),('transaction','transaction-v3-*'),('migration','migration-v3-*')):
    for d in root.glob(pattern):
        if not d.is_dir() or d.name == 'migration-v3-'+target:
            continue
        j=d/'journal.json'
        if not j.exists():
            raise SystemExit('INCOMPLETE_TRANSACTION_DIRECTORY: '+str(d))
        try: state=json.loads(j.read_text())['state']
        except (ValueError,KeyError,OSError): raise SystemExit('INVALID_JOURNAL: '+str(j))
        if state not in terminal[kind]:
            raise SystemExit('PENDING_TRANSACTION: '+str(d)+' (run --recover for its target)')
print('NO_PENDING_TRANSACTIONS')
PY
}

prepare_snapshot() {  # same drift check as deploy-transaction-v3.sh
  local old_commit=$1 old_backend=$2 old_frontend=$3 bh fh
  bh=$(env BACKEND_IMAGE="$old_backend" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$old_commit" \
       bash -o pipefail -c 'docker compose -p backend -f "$1" config --format json |
         docker compose -p backend -f - config --hash backend' _ "$BACKEND_MANAGED" | awk '{print $NF}')
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
  fi
  echo 'COMPOSE_HASHES_MATCH_RUNNING'
}

verify_provenance() {
  [[ -f $PROVENANCE && ! -L $PROVENANCE && $(stat -c '%u:%a' "$PROVENANCE") == "$REQUIRED_UID:600" ]] || {
    echo "TARGET_IMAGE_PROVENANCE_MISSING: $TARGET (let the updater build it first)" >&2; return 1; }
  local service expected
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
    [[ $(image_id "standa-hub-$service:$TARGET" 2>/dev/null) == "$expected" ]] || { echo "TARGET_IMAGE_NOT_FROM_VERIFIED_BUILD: $service" >&2; return 1; }
    [[ $(docker image inspect "$expected" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || {
      echo "TARGET_IMAGE_UNVERIFIED: $service" >&2; return 1; }
  done
  echo 'TARGET_IMAGE_PROVENANCE_VERIFIED'
}

# Rendered backend environment (env_file + compose environment) as a docker --env-file; values with a newline are
# refused (docker env-files cannot hold them). Root-only, in $WORK, removed on exit.
render_backend_env() {
  env BACKEND_IMAGE="$1" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$2" \
    docker compose -p backend -f "$BACKEND_MANAGED" config --format json |
    python3 -I -c '
import json,sys
env=json.load(sys.stdin)["services"]["backend"].get("environment") or {}
out=open(sys.argv[1],"w")
for k,v in sorted(env.items()):
    v="" if v is None else str(v)
    if "\n" in v: raise SystemExit("MULTILINE_ENV_VALUE: "+k)
    out.write(f"{k}={v}\n")
' "$WORK/backend.env"
  chmod 600 "$WORK/backend.env"
}
# Everything with side effects outside the database is off in rehearsal containers (and the network is internal).
SAFE_ENV=(-e SCHEDULER_ENABLED=false -e REMINDERS_CHECK_ENABLED=false -e DAILY_BRIEFING_ENABLED=false
          -e WEEKLY_REVIEW_ENABLED=false -e EXTERNAL_DELIVERY_ENABLED=false -e BACKUP_ENABLED=false
          -e OFFSITE_BACKUP_ENABLED=false -e RUN_ALEMBIC_UPGRADE_AT_STARTUP=false -e MEDIA_DIR=/tmp/rehearsal-media
          -e BACKUP_DIR=/tmp/rehearsal-backups -e MONITORING_LOG_PATH= -e GROQ_BASE_URL=http://127.0.0.1:9)

# ---------- rehearsal on a throwaway copy ----------
cleanup_rehearsal() {
  docker rm -f "$REHEARSAL-old" "$REHEARSAL-new" "$REHEARSAL-db" >/dev/null 2>&1 || true
  docker network rm "$REHEARSAL" >/dev/null 2>&1 || true
}
newest_dump() {
  python3 -I - "$BACKUP_ROOT" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
runs=sorted((root/'runs').glob('backup_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
if not runs: raise SystemExit('BACKUP_NOT_FOUND')
d=json.loads(runs[0].read_text())
if d.get('status')!='success': raise SystemExit('BACKUP_NOT_SUCCESSFUL')
dump=(root/d['database']['filename']).resolve()
if not dump.is_relative_to(root) or not dump.is_file(): raise SystemExit('INVALID_BACKUP_PATH')
print(dump)
PY
}
copy_revision() { docker exec "$REHEARSAL-db" psql -X -U "$DB_USER" -d rehearsal -tAc 'SELECT version_num FROM alembic_version' | awk 'NF {print $1}' | sort | paste -sd, -; }
app_health() {  # $1 container -> /health JSON (also on 503)
  docker exec "$1" python -c '
import urllib.request, urllib.error
try:
    print(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5).read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode())
' 2>/dev/null || true
}
start_app() {  # name image commit url
  docker run -d --name "$1" --network "$REHEARSAL" --env-file "$WORK/backend.env" "${SAFE_ENV[@]}" \
    -e DATABASE_URL="$4" -e APP_COMMIT="$3" --pull never "$2" \
    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --no-proxy-headers >/dev/null
}
expect_app() {  # name mode(strict|old-on-new) new_head
  local i body
  for i in $(seq 1 "$HEALTH_TRIES"); do
    body=$(app_health "$1")
    if [[ -n $body ]] && python3 -I -c '
import json,sys
d=json.loads(sys.argv[1]); mode, new = sys.argv[2], sys.argv[3]
assert d["database"]["status"]=="reachable"
if mode=="strict": assert d["status"]=="healthy" and d["migrations"]["status"]=="current"
else: assert ",".join(sorted(d["migrations"].get("current") or []))==new
' "$body" "$2" "$3" 2>/dev/null; then
      docker exec -i "$1" python - <"$TRUSTED/compat-smoke.py" | grep -q '^ORM_SMOKE_OK' || { echo "REHEARSAL_ORM_SMOKE_FAILED: $1" >&2; return 1; }
      return 0
    fi
    sleep "$HEALTH_SLEEP"
  done
  echo "REHEARSAL_APP_UNHEALTHY: $1 ($2)" >&2; return 1
}
rehearse() {  # dump old_image old_commit new_image old_head new_head
  local dump=$1 old_img=$2 old_commit=$3 new_img=$4 old_head=$5 new_head=$6 pw url pg_image i
  cleanup_rehearsal
  # the IMAGE ID the production database runs (a tag can be moved), verified to exist locally (Codex review P2)
  pg_image=$(docker inspect "$PROD_DB_CONTAINER" --format '{{.Image}}')
  [[ $pg_image =~ ^sha256:[0-9a-f]{64}$ && $(image_id "$pg_image") == "$pg_image" ]] || { echo 'POSTGRES_IMAGE_UNVERIFIED' >&2; return 1; }
  pw=$(python3 -I -c 'import secrets; print(secrets.token_hex(16))')
  url="postgresql+psycopg2://$DB_USER:$pw@$REHEARSAL-db:5432/rehearsal"
  render_backend_env "$old_img" "$old_commit"
  docker network create --internal "$REHEARSAL" >/dev/null
  docker run -d --name "$REHEARSAL-db" --network "$REHEARSAL" --tmpfs /var/lib/postgresql --pull never \
    -e POSTGRES_USER="$DB_USER" -e POSTGRES_PASSWORD="$pw" -e POSTGRES_DB=rehearsal "$pg_image" >/dev/null
  for i in $(seq 1 30); do docker exec "$REHEARSAL-db" pg_isready -U "$DB_USER" -d rehearsal >/dev/null 2>&1 && break; sleep 1; done
  gzip -dc -- "$dump" | docker exec -i "$REHEARSAL-db" psql -X -q -v ON_ERROR_STOP=1 --single-transaction \
    -U "$DB_USER" -d rehearsal >/dev/null
  [[ $(copy_revision) == "$old_head" ]] || { echo 'REHEARSAL_COPY_NOT_AT_OLD_HEAD' >&2; return 1; }
  echo 'REHEARSAL_RESTORE_OK'
  start_app "$REHEARSAL-old" "$old_img" "$old_commit" "$url"
  expect_app "$REHEARSAL-old" strict "$old_head"
  docker rm -f "$REHEARSAL-old" >/dev/null
  echo 'REHEARSAL_OLD_APP_BASELINE_OK'
  docker run --rm --network "$REHEARSAL" --env-file "$WORK/backend.env" "${SAFE_ENV[@]}" -e DATABASE_URL="$url" \
    --pull never --entrypoint alembic "$new_img" upgrade head >/dev/null
  [[ $(copy_revision) == "$new_head" ]] || { echo 'REHEARSAL_MIGRATION_DID_NOT_REACH_NEW_HEAD' >&2; return 1; }
  echo 'REHEARSAL_MIGRATION_OK'
  start_app "$REHEARSAL-new" "$new_img" "$TARGET" "$url"
  expect_app "$REHEARSAL-new" strict "$new_head"
  echo 'REHEARSAL_NEW_APP_OK'
  start_app "$REHEARSAL-old" "$old_img" "$old_commit" "$url"
  expect_app "$REHEARSAL-old" old-on-new "$new_head"
  echo 'REHEARSAL_OLD_APP_COMPATIBLE'
  cleanup_rehearsal
}

# ---------- production steps ----------
migrate_production() {  # new_image
  render_backend_env "$(jval target_backend)" "$TARGET"
  docker run --rm --network "$PROD_NETWORK" --env-file "$WORK/backend.env" "${SAFE_ENV[@]}" \
    --pull never --entrypoint alembic "$1" upgrade head
}
deploy_new() {
  advance deploying
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
  echo 'MIGRATION_DEPLOYMENT_OK'
}
# The managed templates rendered with the previous values must equal the snapshot saved at "prepared" (image aside):
# otherwise the trusted Compose config changed since then and the rollback would start the old images with another
# configuration (Codex review P2) -> manual recovery, like deploy-transaction-v3.sh.
snapshot_matches() {  # service rollback-ref snapshot-file
  local -a vars
  if [[ $1 == backend ]]; then
    vars=("BACKEND_IMAGE=$2" "BACKEND_ENV_FILE=$BACKEND_ENV_FILE" "APP_COMMIT=$(jval previous_commit)")
  else
    vars=("FRONTEND_IMAGE=$2" "NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL")
  fi
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
rollback_app() {  # previous images through the managed templates; the database stays migrated
  local rb rf failures=0
  rb="standa-hub-backend:rollback-$TARGET"; rf="standa-hub-frontend:rollback-$TARGET"
  [[ -f $OLD_B && -f $OLD_F ]] || { echo 'ROLLBACK_SNAPSHOT_MISSING' >&2; return 1; }
  [[ $(image_id "$rb") == "$(jval backend)" && $(image_id "$rf") == "$(jval frontend)" ]] || { echo 'ROLLBACK_IMAGE_ID_CHANGED' >&2; return 1; }
  snapshot_matches backend "$rb" "$OLD_B" && snapshot_matches frontend "$rf" "$OLD_F" || {
    echo 'MANAGED_CONFIG_CHANGED_SINCE_SNAPSHOT: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  echo '=== RESTORE PREVIOUS APPLICATION (database stays migrated) ===' >&2
  env BACKEND_IMAGE="$rb" BACKEND_ENV_FILE="$BACKEND_ENV_FILE" APP_COMMIT="$(jval previous_commit)" \
    docker compose -p backend -f "$BACKEND_MANAGED" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 backend || failures=1
  env FRONTEND_IMAGE="$rf" NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
    docker compose -p frontend -f "$FRONTEND_MANAGED" up -d --no-deps --no-build --pull never --force-recreate --wait --wait-timeout 120 frontend || failures=1
  [[ $(running_id standa-hub-backend) == "$(jval backend)" && $(running_id standa-hub-frontend) == "$(jval frontend)" ]] || failures=1
  (( failures == 0 )) && check_old_app_compatible "$(jval new_head)" || {
    echo 'APP_ROLLBACK_NOT_VERIFIED: MANUAL_RECOVERY_REQUIRED (database stays at the new head; restore only by hand from the backup taken before the migration)' >&2
    return 1; }
  advance rolled_back_app --note 'old application verified on the migrated database'
  echo 'APP_ROLLED_BACK_DATABASE_STAYS_MIGRATED'
}
archive() {
  local dest
  install -d -m 700 "$STATE_DIR/archive"
  dest=$(mktemp -d "$STATE_DIR/archive/migration-v3-$TARGET.$(jval state)-$(utc_stamp).XXXXXX")
  mv -T -- "$FINAL" "$dest"
  fsync_dir "$STATE_DIR"
  echo "MIGRATION_TRANSACTION_ARCHIVED: archive/${dest##*/}"
}
abort_unchanged() {  # nothing was migrated or deployed: prove it, close as aborted, move aside for a retry
  if [[ $(running_id standa-hub-backend) != "$(jval backend)" || $(running_id standa-hub-frontend) != "$(jval frontend)" ]]; then
    echo 'CONTAINERS_CHANGED: MANUAL_RECOVERY_REQUIRED' >&2; return 1; fi
  [[ $(prod_db_revision) == "$(jval old_head)" ]] || { echo 'DATABASE_NOT_AT_OLD_HEAD: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  advance aborted --note "${1:-no production change}"
  archive
  echo 'MIGRATION_ABORTED_NO_PRODUCTION_CHANGE'
}
resolve_db_migrating() {  # the production revision decides what an interrupted migration did
  local rev
  rev=$(prod_db_revision) || { echo 'DATABASE_REVISION_UNKNOWN: MANUAL_RECOVERY_REQUIRED' >&2; return 1; }
  if [[ $rev == "$(jval old_head)" ]]; then abort_unchanged 'migration did not apply (database at the old head)'
  elif [[ $rev == "$(jval new_head)" ]]; then advance db_migrated --note 'database verified at the new head'; return 0
  else echo "DATABASE_AT_UNEXPECTED_REVISION: $rev MANUAL_RECOVERY_REQUIRED" >&2; return 1; fi
}

on_exit() {
  local rc=$? state
  trap - EXIT INT TERM
  cleanup_rehearsal
  rm -rf -- "$WORK"
  if (( rc != 0 )) && [[ $MODE == --apply && $TX == "$FINAL" && -f $JOURNAL ]]; then
    state=$(jval state) || state=invalid
    case "$state" in
      prepared|rehearsed) abort_unchanged 'failed before the migration' || echo 'MANUAL_RECOVERY_REQUIRED' >&2 ;;
      db_migrating) resolve_db_migrating && echo 'DATABASE_MIGRATED_APP_NOT_DEPLOYED: run --recover to finish the deployment' >&2 ;;
      db_migrated) echo 'DATABASE_MIGRATED_APP_NOT_DEPLOYED: run --recover to finish the deployment' >&2 ;;
      deploying|verifying) { advance app_rollback_required && rollback_app; } || echo 'MANUAL_RECOVERY_REQUIRED' >&2 ;;
    esac
  elif (( rc != 0 )) && [[ $MODE == --apply && $TX != "$FINAL" && -d $TX ]]; then
    rm -rf -- "$TX"
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ $MODE == --recover ]]; then
  [[ -f $JOURNAL ]] || { echo 'MIGRATION_JOURNAL_NOT_FOUND' >&2; exit 1; }
  case "$(jval state)" in
    prepared|rehearsed) abort_unchanged 'recovered before the migration'; exit 0 ;;
    aborted) archive; exit 0 ;;   # power loss between "advance aborted" and the archive (Codex review P1)
    db_migrating) resolve_db_migrating; [[ -e $FINAL ]] || exit 0 ;;
  esac
  case "$(jval state)" in
    db_migrated) deploy_new ;;                      # roll forward: the database already has the new schema
    deploying|verifying) advance app_rollback_required; rollback_app ;;
    app_rollback_required) rollback_app ;;
    *) echo "NOT_RECOVERABLE: $(jval state)" >&2; exit 1 ;;
  esac
  exit 0
fi

# ---------- preflight (--check and --apply) ----------
check_pending
if [[ -f $JOURNAL && $(jval state) == aborted ]]; then  # aborted but not yet archived: nothing was changed
  if [[ $MODE == --apply ]]; then archive; else echo 'ABORTED_MIGRATION_WILL_BE_ARCHIVED'; fi
fi
[[ ! -e $FINAL || ( $MODE == --check && -f $JOURNAL && $(jval state) == aborted ) ]] || {
  echo 'MIGRATION_TRANSACTION_ALREADY_EXISTS (finished ones: see archive/ or --recover)' >&2; exit 1; }
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
[[ $OLD_COMMIT != "$TARGET" ]] || { echo 'ALREADY_DEPLOYED' >&2; exit 1; }
OLD_BACKEND=$(docker inspect standa-hub-backend --format '{{.Config.Image}}')
OLD_FRONTEND=$(docker inspect standa-hub-frontend --format '{{.Config.Image}}')
as_git_user git -C "$ROOT" merge-base --is-ancestor "$OLD_COMMIT" "$TARGET" || { echo 'NON_FAST_FORWARD_BLOCKED' >&2; exit 1; }
as_git_user "$TRUSTED/check-ci.sh" "$TARGET"
python3 -I "$TRUSTED/check-backup.py"
python3 -I "$TRUSTED/verify-release.py" "$TARGET"
verify_provenance
NEW_B_ID=$(image_id "$BACKEND_NEW"); NEW_F_ID=$(image_id "$FRONTEND_NEW")
OLD_B_ID=$(running_id standa-hub-backend); OLD_F_ID=$(running_id standa-hub-frontend)
OLD_HEAD=$(image_head "$OLD_B_ID"); NEW_HEAD=$(image_head "$NEW_B_ID")
[[ -n $OLD_HEAD && -n $NEW_HEAD ]] || { echo 'ALEMBIC_HEAD_UNKNOWN' >&2; exit 1; }
[[ $OLD_HEAD != "$NEW_HEAD" ]] || { echo 'NOT_A_MIGRATION_RELEASE: use the automatic updater' >&2; exit 1; }
[[ $OLD_HEAD != *,* && $NEW_HEAD != *,* ]] || { echo 'MULTIPLE_ALEMBIC_HEADS: MANUAL_REVIEW_REQUIRED' >&2; exit 1; }
echo "ALEMBIC_HEADS: $OLD_HEAD -> $NEW_HEAD"
DB_REV=$(prod_db_revision)
[[ $DB_REV == "$OLD_HEAD" ]] || { echo "DATABASE_NOT_AT_OLD_HEAD: $DB_REV (a database migrated outside this procedure is never accepted)" >&2; exit 1; }
echo 'PRODUCTION_DATABASE_AT_OLD_HEAD'
python3 -I "$TRUSTED/check-migration.py" "$RELEASES/$TARGET/backend/alembic/versions" "$OLD_HEAD" "$NEW_HEAD"
prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND"
[[ $(image_id "$OLD_BACKEND") == "$OLD_B_ID" && $(image_id "$OLD_FRONTEND") == "$OLD_F_ID" ]] || { echo 'CURRENT_IMAGE_TAG_DRIFT' >&2; exit 1; }

if [[ $MODE == --check ]]; then
  rehearse "$(newest_dump)" "$OLD_B_ID" "$OLD_COMMIT" "$NEW_B_ID" "$OLD_HEAD" "$NEW_HEAD"
  echo 'MIGRATION_PREFLIGHT_OK'
  echo 'NO_PRODUCTION_CHANGES'
  exit 0
fi

# ---------- --apply ----------
echo '=== FRESH BACKUP ==='
"$BACKUP_CMD"
python3 -I "$TRUSTED/check-backup.py"
DUMP=$(newest_dump)

for d in "$STATE_DIR"/.staging-migration-v3-*; do  # never reached "prepared": nothing was changed
  if [[ -d $d && ! -L $d ]]; then rm -rf -- "$d"; echo "STALE_STAGING_REMOVED: ${d##*/}"; fi
done
set_tx "$(mktemp -d "$STATE_DIR/.staging-migration-v3-$TARGET.XXXXXXXX")"
chmod 700 "$TX"
prepare_snapshot "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND" 1
docker image tag "$OLD_B_ID" "standa-hub-backend:rollback-$TARGET"
docker image tag "$OLD_F_ID" "standa-hub-frontend:rollback-$TARGET"
python3 -I - "$TX" "$TARGET" "$OLD_COMMIT" "$OLD_BACKEND" "$OLD_FRONTEND" "$OLD_B_ID" "$OLD_F_ID" "$NEW_B_ID" "$NEW_F_ID" \
  "$OLD_HEAD" "$NEW_HEAD" "${DUMP##*/}" <<'PY'
import json,os,sys,tempfile
from pathlib import Path
from datetime import datetime,timezone
p=Path(sys.argv[1])
now=datetime.now(timezone.utc).isoformat()
d={'state':'prepared','kind':'migration','target_commit':sys.argv[2],'created_at':now,
   'previous':{'backend':{'image_reference':sys.argv[4],'image_id':sys.argv[6],'app_commit':sys.argv[3]},
               'frontend':{'image_reference':sys.argv[5],'image_id':sys.argv[7]}},
   'target':{'backend':{'image_id':sys.argv[8]},'frontend':{'image_id':sys.argv[9]}},
   'old_head':sys.argv[10],'new_head':sys.argv[11],'backup_dump':sys.argv[12],
   'history':[{'state':'prepared','at':now}]}
fd,tmp=tempfile.mkstemp(prefix='.journal.',dir=p)
with os.fdopen(fd,'w') as f:
    json.dump(d,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
os.chmod(tmp,0o600);os.replace(tmp,p/'journal.json')
PY
mv -T -- "$TX" "$FINAL"
fsync_dir "$STATE_DIR"
set_tx "$FINAL"

echo '=== REHEARSAL ON A COPY OF THE FRESH BACKUP ==='
rehearse "$DUMP" "$OLD_B_ID" "$OLD_COMMIT" "$NEW_B_ID" "$OLD_HEAD" "$NEW_HEAD"
advance rehearsed --note 'copy migrated; new app healthy; old app compatible'

echo '=== MIGRATE PRODUCTION DATABASE ==='
advance db_migrating
migrate_production "$NEW_B_ID"
[[ $(prod_db_revision) == "$NEW_HEAD" ]] || { echo 'PRODUCTION_MIGRATION_DID_NOT_REACH_NEW_HEAD' >&2; exit 1; }
advance db_migrated --note 'database verified at the new head'
deploy_new
