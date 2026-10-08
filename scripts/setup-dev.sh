#!/usr/bin/env bash
# Standa Hub – idempotent dev bootstrap for people and agents (Local/Cloud Claude, Codex).
#
# Installs backend (Python venv + requirements-dev.txt) and frontend (npm ci) dependencies
# ONLY when they are missing or their lockfiles changed. A second run with nothing changed
# finishes in about a second. Never touches .env files, databases or MEDIA_DIR.
#
#   scripts/setup-dev.sh                 # backend + frontend, skip what is up to date
#   scripts/setup-dev.sh --backend       # only Python
#   scripts/setup-dev.sh --frontend      # only npm
#   scripts/setup-dev.sh --check         # report only; exit 2 if something is stale
#   scripts/setup-dev.sh --force         # reinstall even if up to date
#   scripts/setup-dev.sh --system-python # install into the current interpreter instead of .venv
#                                        # (for cloud images that manage their own Python)
#
# Env: SETUP_PYTHON (interpreter used to create the venv, default python3.12 → python3 → python),
#      SETUP_VENV (venv path, default .venv in the repo root).
# Works on Linux/macOS and in Git Bash on Windows (.venv/Scripts layout).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMPS="$ROOT/.dev-setup"
VENV="${SETUP_VENV:-$ROOT/.venv}"

do_backend=1 do_frontend=1 check=0 force=0 system_python=0
for arg in "$@"; do
  case "$arg" in
    --backend) do_frontend=0 ;;
    --frontend) do_backend=0 ;;
    --check) check=1 ;;
    --force) force=1 ;;
    --system-python) system_python=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "setup-dev: unknown option $arg (see --help)" >&2; exit 1 ;;
  esac
done

log() { echo "setup-dev: $*"; }
stale=0

hash_files() {
  if command -v sha256sum >/dev/null 2>&1; then cat "$@" | sha256sum | cut -d' ' -f1
  else cat "$@" | shasum -a 256 | cut -d' ' -f1; fi
}

# up_to_date <stamp-name> <expected-key>: true when the stored key matches
up_to_date() { [[ $force -eq 0 && -f "$STAMPS/$1" && "$(cat "$STAMPS/$1")" == "$2" ]]; }
write_stamp() { mkdir -p "$STAMPS"; printf '%s' "$2" > "$STAMPS/$1"; }

# ---------------------------------------------------------------- backend
setup_backend() {
  local py
  if [[ $system_python -eq 1 ]]; then
    py="$(command -v python3 || command -v python)"
  else
    if [[ -x "$VENV/bin/python" ]]; then py="$VENV/bin/python"
    elif [[ -x "$VENV/Scripts/python.exe" ]]; then py="$VENV/Scripts/python.exe"
    else py=""; fi
  fi

  local reqs=("$ROOT/backend/requirements.txt" "$ROOT/backend/requirements-dev.txt")
  local version="none"
  [[ -n "$py" ]] && version="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  local key="py$version-$(hash_files "${reqs[@]}")"
  local stamp="backend-$([[ $system_python -eq 1 ]] && echo system || echo venv)"

  if [[ -n "$py" ]] && up_to_date "$stamp" "$key"; then
    log "backend up to date (Python $version)"; return
  fi
  if [[ $check -eq 1 ]]; then log "backend STALE (missing venv or requirements changed)"; stale=1; return; fi

  if [[ -z "$py" ]]; then
    local base="${SETUP_PYTHON:-}"
    if [[ -z "$base" ]]; then
      for candidate in python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then base="$candidate"; break; fi
      done
    fi
    [[ -n "$base" ]] || { log "no Python found (need 3.12)"; exit 1; }
    log "creating venv $VENV with $base"
    "$base" -m venv "$VENV"
    if [[ -x "$VENV/bin/python" ]]; then py="$VENV/bin/python"; else py="$VENV/Scripts/python.exe"; fi
    version="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    key="py$version-$(hash_files "${reqs[@]}")"
  fi
  [[ "$version" == "3.12" ]] || log "warning: Python $version, CI uses 3.12"

  log "installing backend/requirements-dev.txt"
  "$py" -m pip install --disable-pip-version-check -q -r "$ROOT/backend/requirements-dev.txt"
  write_stamp "$stamp" "$key"
  log "backend ready ($py)"
}

# ---------------------------------------------------------------- frontend
setup_frontend() {
  command -v npm >/dev/null 2>&1 || { log "npm not found (need Node.js 24)"; exit 1; }
  local node_major; node_major="$(node -p 'process.versions.node.split(".")[0]')"
  local key="node$node_major-$(hash_files "$ROOT/frontend/package-lock.json")"

  if [[ -f "$ROOT/frontend/node_modules/.package-lock.json" ]] && up_to_date frontend "$key"; then
    log "frontend up to date (Node $node_major)"; return
  fi
  if [[ $check -eq 1 ]]; then log "frontend STALE (missing node_modules or package-lock changed)"; stale=1; return; fi
  [[ "$node_major" == "24" ]] || log "warning: Node $node_major, CI uses 24"

  log "npm ci in frontend/"
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund --no-update-notifier --loglevel=error)
  write_stamp frontend "$key"
  log "frontend ready"
}

[[ $do_backend -eq 1 ]] && setup_backend
[[ $do_frontend -eq 1 ]] && setup_frontend

if [[ $check -eq 1 && $stale -eq 1 ]]; then exit 2; fi
if [[ $check -eq 0 ]]; then
  log "done. Env files are not created: copy backend/.env.template / frontend/.env.template yourself (see README)."
fi
