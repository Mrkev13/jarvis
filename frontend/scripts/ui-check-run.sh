#!/usr/bin/env bash
# Standa Hub – run the browser UI checks in one command (MRK-95), locally and in CI.
#
# Builds the app (unless --no-build), starts the mock API (fixtures, never Groq) and `next start`, runs the
# selected checks one by one with a fresh mock for each, and always stops both servers again – also on failure
# or Ctrl+C. Screenshots land in frontend/scripts/.ui-check/ (gitignored; CI uploads them as an artifact).
#
#   scripts/ui-check-run.sh                     # everything: ui, flags, flags-off, changes
#   scripts/ui-check-run.sh ui changes          # only the named checks
#   scripts/ui-check-run.sh --no-build ui       # reuse the existing .next build
#
# Checks: ui (ui-check.mjs), flags (module-flags-check.mjs), flags-off (same with wot+finance disabled),
#         changes (changes-check.mjs).
# Env:    PLAYWRIGHT_MODULE / PLAYWRIGHT_CHROMIUM are passed through (see the header of ui-check.mjs);
#         UI_CHECK_PAGES limits the per-page layout pass of ui-check.mjs.
# Ports 3000 (app) and 8000 (mock API) must be free – the checks use them directly.
# Linux/macOS and CI; intended to work in Git Bash on Windows (local verification pending).
set -euo pipefail

FRONTEND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FRONTEND"
LOGS="$FRONTEND/scripts/.ui-check/logs"
mkdir -p "$LOGS"

build=1
checks=()
for arg in "$@"; do
  case "$arg" in
    --no-build) build=0 ;;
    ui|flags|flags-off|changes) checks+=("$arg") ;;
    -h|--help) sed -n '2,/^set -euo/{/^#/p}' "$0"; exit 0 ;;
    *) echo "ui-check-run: unknown argument $arg (see --help)" >&2; exit 1 ;;
  esac
done
[[ ${#checks[@]} -eq 0 ]] && checks=(ui flags flags-off changes)

APP_PID="" MOCK_PID=""
stop_pid() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
cleanup() {
  stop_pid "$MOCK_PID"
  stop_pid "$APP_PID"
  MOCK_PID="" APP_PID=""
}
trap cleanup EXIT
trap 'exit 130' INT TERM

wait_for() {
  local url="$1" name="$2"
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "$url"; then return 0; fi
    sleep 1
  done
  echo "ui-check-run: $name did not start (log: $LOGS/$name.log)" >&2
  tail -20 "$LOGS/$name.log" >&2 || true
  exit 1
}

start_mock() {
  stop_pid "$MOCK_PID"
  node scripts/mock-api.mjs >"$LOGS/mock-api.log" 2>&1 &
  MOCK_PID=$!
  wait_for "http://127.0.0.1:8000/modules" mock-api
}

if [[ $build -eq 1 ]]; then
  echo "ui-check-run: npm run build"
  npm run build >"$LOGS/build.log" 2>&1 || { tail -40 "$LOGS/build.log" >&2; exit 1; }
fi

node node_modules/next/dist/bin/next start -p 3000 -H 127.0.0.1 >"$LOGS/next.log" 2>&1 &
APP_PID=$!
wait_for "http://127.0.0.1:3000/login" next

failed=()
for check in "${checks[@]}"; do
  start_mock  # fresh mock state (preferences, modules, Dnes) for every check
  echo "ui-check-run: $check"
  status=0
  case "$check" in
    ui) node scripts/ui-check.mjs || status=$? ;;
    flags) node scripts/module-flags-check.mjs || status=$? ;;
    flags-off) UI_FLAGS_DISABLED=wot,finance node scripts/module-flags-check.mjs || status=$? ;;
    changes) node scripts/changes-check.mjs || status=$? ;;
  esac
  [[ $status -ne 0 ]] && failed+=("$check")
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "ui-check-run: FAILED: ${failed[*]}" >&2
  exit 1
fi
echo "ui-check-run: all passed (${checks[*]}). Screenshots: $FRONTEND/scripts/.ui-check/"
