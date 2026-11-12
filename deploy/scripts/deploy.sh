#!/usr/bin/env bash
# MRK-108: automatic deploy of Standa Hub on the Ubuntu host after a merge to main (systemd timer, every 10 minutes).
#
#   deploy.sh check   # tools, checkout, env files, timer, deployed vs. origin/main - names and booleans only; exit 2 = not ready
#   deploy.sh run     # one pass: deploy origin/main when it moved (what the timer runs)
#
# One pass (only when origin/main is ahead of the checked-out commit):
#   1. preconditions: tracked files of the checkout are clean, origin/main descends from the deployed commit
#      (no rewritten history), the commit did not fail before (a failed commit is not retried - fix it with a new merge);
#   2. fresh backup (deploy/scripts/backup.sh = standa-hub-backup.service) - no backup, no deploy;
#   3. the running images are kept as :previous; checkout --detach of the new commit; build backend + frontend
#      (a failed build changes nothing that runs);
#   4. `docker compose up -d` - the backend's `migrate` service (alembic upgrade head) runs first;
#   5. health: /health must not be unhealthy (healthy, or degraded = scheduler/backup warning), migrations current,
#      version.commit == the new commit, and frontend /login 200 - within HEALTH_TIMEOUT;
#   6. on any failure after the build: ROLLBACK - previous commit checked out, :previous images back as :local,
#      containers started again WITHOUT the migrate service (the old code does not know the newer revision; migrations
#      are additive, so the old code runs on the newer schema - docs/ubuntu-deployment.md "Automatic deploy").
#      The database is never rolled back automatically.
# The result of every pass is in $STATE_DIR/last-result.txt; a failed pass exits 1 (systemctl status / journal).
#
# Run the INSTALLED copy (/usr/local/lib/standa-hub/deploy.sh, root via standa-hub-deploy.service), never the file
# inside the checkout - the checkout is switched to the commit being deployed. Git runs as $REPO_USER, so the
# checkout keeps its owner; docker runs as root.
#
# Env: REPO_DIR (/srv/standa-hub), REPO_USER (standa; empty = current user), BRANCH (main),
#      STATE_DIR (/var/lib/standa-hub-deploy), BACKUP_CMD (/usr/local/lib/standa-hub/backup.sh), DOCKER (docker),
#      HEALTH_URL (http://127.0.0.1:8000/health), FRONTEND_URL (http://127.0.0.1:3000/login),
#      HEALTH_TIMEOUT (300 s), HEALTH_INTERVAL (5 s).
set -euo pipefail

REPO_DIR="${REPO_DIR:-/srv/standa-hub}"
REPO_USER="${REPO_USER-standa}"
BRANCH="${BRANCH:-main}"
STATE_DIR="${STATE_DIR:-/var/lib/standa-hub-deploy}"
BACKUP_CMD="${BACKUP_CMD:-/usr/local/lib/standa-hub/backup.sh}"
DOCKER="${DOCKER:-docker}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:3000/login}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
IMAGES=(standa-hub-backend standa-hub-frontend)

log() { printf '[deploy] %s\n' "$*"; }

result() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >"$STATE_DIR/last-result.txt"
  log "$*"
}

# git always as the checkout's owner (the unit runs as root)
g() {
  if [[ -n "$REPO_USER" && "$(id -un)" != "$REPO_USER" ]]; then
    runuser -u "$REPO_USER" -- git -C "$REPO_DIR" "$@"
  else
    git -C "$REPO_DIR" "$@"
  fi
}

compose_backend() { (cd "$REPO_DIR/backend" && APP_COMMIT="$1" "$DOCKER" compose "${@:2}"); }
compose_frontend() { (cd "$REPO_DIR/frontend" && "$DOCKER" compose "$@"); }

# /health JSON on stdin; $1 = expected commit, $2 = "strict" (not unhealthy, migrations current) or "loose"
# (rollback: answers with the right commit; the old code reports the newer schema as a mismatch = HTTP 503 unhealthy)
health_ok() {
  python3 -c '
import json, sys
want, mode = sys.argv[1], sys.argv[2]
try:
    h = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
ok = (h.get("version") or {}).get("commit") == want
if mode == "strict":
    ok = ok and h.get("status") in ("healthy", "degraded") and (h.get("migrations") or {}).get("status") == "current"
sys.exit(0 if ok else 1)
' "$1" "$2"
}

wait_healthy() {   # $1 = commit, $2 = strict|loose
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) body
  while ((SECONDS < deadline)); do
    # no -f: /health answers 503 with a JSON body when unhealthy, health_ok decides
    body="$(curl -sS --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
    if [[ -n "$body" ]] && health_ok "$1" "$2" <<<"$body" && curl -fsS -o /dev/null --max-time 5 "$FRONTEND_URL"; then
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

rollback() {   # $1 = previous commit, $2 = failed commit, $3 = why
  local prev="$1" bad="$2" why="$3" image
  log "rolling back to ${prev:0:7} ($why)"
  echo "$bad" >"$STATE_DIR/failed-$bad"
  g -c advice.detachedHead=false checkout --quiet --detach "$prev" || true
  for image in "${IMAGES[@]}"; do
    "$DOCKER" image inspect "$image:previous" >/dev/null 2>&1 && "$DOCKER" image tag "$image:previous" "$image:local"
  done
  # --no-deps: never run `migrate` with the old code (it does not know the newer revision)
  compose_backend "$prev" up -d --no-build --no-deps backend || true
  compose_frontend up -d --no-build || true
  if wait_healthy "$prev" loose; then
    result "deploy of ${bad:0:7} failed ($why); rolled back to ${prev:0:7} - running. Database not rolled back."
  else
    result "deploy of ${bad:0:7} failed ($why); ROLLBACK to ${prev:0:7} NOT healthy - manual action needed"
  fi
  # the caller returns 1 (a non-zero return here would fire the ERR trap and overwrite the result)
}

run() {
  mkdir -p "$STATE_DIR"
  exec 9>"$STATE_DIR/run.lock"
  if ! flock -n 9; then log "another deploy is running; nothing to do"; return 0; fi
  trap 'result "deploy failed unexpectedly (line $LINENO)"' ERR

  g fetch --quiet origin "$BRANCH"
  local current target image
  current="$(g rev-parse HEAD)"
  target="$(g rev-parse "origin/$BRANCH")"
  if [[ "$current" == "$target" ]]; then
    [[ -f "$STATE_DIR/last-result.txt" ]] || result "up to date at ${current:0:7}"
    return 0
  fi
  if [[ -f "$STATE_DIR/failed-$target" ]]; then
    log "${target:0:7} failed before - not retried (merge a fix)"
    return 0
  fi
  if [[ -n "$(g status --porcelain --untracked-files=no)" ]]; then
    result "deploy of ${target:0:7} refused: tracked files in $REPO_DIR are modified (git status)"
    return 1
  fi
  if ! g merge-base --is-ancestor "$current" "$target"; then
    result "deploy of ${target:0:7} refused: origin/$BRANCH does not descend from ${current:0:7} (rewritten history?)"
    return 1
  fi

  log "deploying ${current:0:7} -> ${target:0:7}"
  if ! "$BACKUP_CMD" >"$STATE_DIR/backup.log" 2>&1; then
    result "deploy of ${target:0:7} refused: backup failed (see $STATE_DIR/backup.log); nothing changed"
    return 1
  fi
  for image in "${IMAGES[@]}"; do
    "$DOCKER" image inspect "$image:local" >/dev/null 2>&1 && "$DOCKER" image tag "$image:local" "$image:previous"
  done

  g -c advice.detachedHead=false checkout --quiet --detach "$target"
  if ! compose_backend "$target" build backend >"$STATE_DIR/build.log" 2>&1 \
      || ! compose_frontend build frontend >>"$STATE_DIR/build.log" 2>&1; then
    # nothing running changed: back to the previous checkout and images
    g -c advice.detachedHead=false checkout --quiet --detach "$current"
    for image in "${IMAGES[@]}"; do
      "$DOCKER" image inspect "$image:previous" >/dev/null 2>&1 && "$DOCKER" image tag "$image:previous" "$image:local"
    done
    echo "$target" >"$STATE_DIR/failed-$target"
    result "deploy of ${target:0:7} failed: build (see $STATE_DIR/build.log); still running ${current:0:7}"
    return 1
  fi

  if ! compose_backend "$target" up -d >"$STATE_DIR/up.log" 2>&1; then
    rollback "$current" "$target" "start or migration failed, see $STATE_DIR/up.log"
    return 1
  fi
  if ! compose_frontend up -d >>"$STATE_DIR/up.log" 2>&1; then
    rollback "$current" "$target" "frontend start failed"
    return 1
  fi
  if ! wait_healthy "$target" strict; then
    rollback "$current" "$target" "health check failed within ${HEALTH_TIMEOUT}s"
    return 1
  fi
  echo "$target" >"$STATE_DIR/deployed"
  result "deployed ${target:0:7} (was ${current:0:7}); healthy, migrations current"
}

check() {
  local ready=true value
  report() { printf '%s: %s\n' "$1" "$2"; [[ "$2" == true ]] || ready=false; }
  for tool in git curl python3 flock "$DOCKER"; do
    command -v "$tool" >/dev/null && value=true || value=false; report "${tool##*/}_installed" "$value"
  done
  [[ -d "$REPO_DIR/.git" ]] && value=true || value=false; report checkout_present "$value"
  [[ -z "$(g status --porcelain --untracked-files=no 2>/dev/null)" ]] && value=true || value=false
  report checkout_clean "$value"
  [[ -f "$REPO_DIR/backend/.env.production" ]] && value=true || value=false; report backend_env_file "$value"
  [[ -f "$REPO_DIR/frontend/.env" ]] && value=true || value=false; report frontend_env_file "$value"
  [[ -x "$BACKUP_CMD" || -f "$BACKUP_CMD" ]] && value=true || value=false; report backup_script "$value"
  systemctl is-enabled --quiet standa-hub-deploy.timer 2>/dev/null && value=true || value=false
  report timer_enabled "$value"
  printf 'deployed: %s\n' "$(g rev-parse --short HEAD 2>/dev/null || echo unknown)"
  printf 'origin_%s: %s\n' "$BRANCH" "$(g rev-parse --short "origin/$BRANCH" 2>/dev/null || echo unknown)"
  printf 'last_result: %s\n' "$(cat "$STATE_DIR/last-result.txt" 2>/dev/null || echo 'none yet')"
  printf 'ready: %s\n' "$ready"
  [[ "$ready" == true ]] || exit 2
}

case "${1:-check}" in
  run) run ;;
  check) check ;;
  *) echo "usage: $0 [check|run]" >&2; exit 1 ;;
esac
