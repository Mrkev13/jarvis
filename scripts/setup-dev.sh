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
#   scripts/setup-dev.sh --force         # re-run the installs even if up to date (ignored with --check)
#   scripts/setup-dev.sh --system-python # install into the current interpreter instead of .venv
#                                        # (for cloud images that manage their own Python)
#
# Env: SETUP_PYTHON (Python executable to use; default: first that actually runs of
#      python3.12, python3, python, "py -3.12"), SETUP_VENV (venv path, default .venv in the repo root).
# Linux/macOS and cloud images. Intended to work in Git Bash on Windows (.venv/Scripts layout);
# local Windows verification pending.
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
    -h|--help) sed -n '2,/^set -euo/{/^#/p}' "$0"; exit 0 ;;
    *) echo "setup-dev: unknown option $arg (see --help)" >&2; exit 1 ;;
  esac
done
if [[ $do_backend -eq 0 && $do_frontend -eq 0 ]]; then
  echo "setup-dev: --backend and --frontend are mutually exclusive (omit both for everything)" >&2; exit 1
fi
[[ $check -eq 1 ]] && force=0  # --check only reports

log() { echo "setup-dev: $*"; }
stale=0

hash_files() {
  if command -v sha256sum >/dev/null 2>&1; then cat "$@" | sha256sum | cut -d' ' -f1
  else cat "$@" | shasum -a 256 | cut -d' ' -f1; fi
}

# find_python: sets PYCMD to the first Python that actually runs (not just exists on PATH;
# Windows has non-working "python3" Store aliases). Returns 1 when none works.
find_python() {
  local c cand
  if [[ -n "${SETUP_PYTHON:-}" ]]; then
    if "$SETUP_PYTHON" -c 'import sys' >/dev/null 2>&1; then PYCMD=("$SETUP_PYTHON"); return 0; fi
    log "SETUP_PYTHON='$SETUP_PYTHON' does not run"; return 1
  fi
  for c in python3.12 python3 python "py -3.12"; do
    read -r -a cand <<< "$c"
    command -v "${cand[0]}" >/dev/null 2>&1 || continue
    if "${cand[@]}" -c 'import sys' >/dev/null 2>&1; then PYCMD=("${cand[@]}"); return 0; fi
  done
  return 1
}
no_python() {
  log "no working Python found (need 3.12). Tried python3.12, python3, python, 'py -3.12'; set SETUP_PYTHON=/path/to/python"
  exit 1
}

# up_to_date <stamp-name> <expected-key>: true when the stored key matches
up_to_date() { [[ $force -eq 0 && -f "$STAMPS/$1" && "$(cat "$STAMPS/$1")" == "$2" ]]; }
write_stamp() { mkdir -p "$STAMPS"; printf '%s' "$2" > "$STAMPS/$1"; }

# ---------------------------------------------------------------- backend
venv_python() {  # sets PYCMD to the venv interpreter if the venv exists
  if [[ -x "$VENV/bin/python" ]]; then PYCMD=("$VENV/bin/python")
  elif [[ -x "$VENV/Scripts/python.exe" ]]; then PYCMD=("$VENV/Scripts/python.exe")
  else PYCMD=(); fi
}

setup_backend() {
  PYCMD=()
  if [[ $system_python -eq 1 ]]; then find_python || no_python
  else venv_python; fi

  local reqs=("$ROOT/backend/requirements.txt" "$ROOT/backend/requirements-dev.txt")
  local version="none" target="$VENV"
  if [[ ${#PYCMD[@]} -gt 0 ]]; then
    version="$("${PYCMD[@]}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    [[ $system_python -eq 1 ]] && target="$("${PYCMD[@]}" -c 'import sys; print(sys.executable)')"
  fi
  # key includes the target (venv path / interpreter) so switching SETUP_VENV is detected
  local key="py$version|$target|$(hash_files "${reqs[@]}")"
  local stamp="backend-$([[ $system_python -eq 1 ]] && echo system || echo venv)"

  # The external stamp survives deleting/recreating a venv at the same path.
  # Its in-venv marker must also survive; system Python keeps stamp-only behavior.
  local marker="$VENV/.standa-hub-setup-ok"
  if [[ ${#PYCMD[@]} -gt 0 ]] && up_to_date "$stamp" "$key" && \
     [[ $system_python -eq 1 || -f "$marker" ]]; then
    log "backend up to date (Python $version)"; return
  fi
  if [[ $check -eq 1 ]]; then log "backend STALE (missing venv/setup marker or requirements changed)"; stale=1; return; fi

  if [[ ${#PYCMD[@]} -eq 0 ]]; then
    find_python || no_python
    log "creating venv $VENV with ${PYCMD[*]}"
    "${PYCMD[@]}" -m venv "$VENV"
    venv_python
    [[ ${#PYCMD[@]} -gt 0 ]] || { log "venv created but no interpreter found in $VENV"; exit 1; }
    version="$("${PYCMD[@]}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    key="py$version|$target|$(hash_files "${reqs[@]}")"
  fi
  [[ "$version" == "3.12" ]] || log "warning: Python $version, CI uses 3.12"

  # A failed forced reinstall must not leave an old success marker behind.
  if [[ $system_python -eq 0 ]]; then rm -f "$marker"; fi
  log "installing backend/requirements-dev.txt"
  "${PYCMD[@]}" -m pip install --disable-pip-version-check -q -r "$ROOT/backend/requirements-dev.txt"
  write_stamp "$stamp" "$key"
  if [[ $system_python -eq 0 ]]; then touch "$marker"; fi
  log "backend ready (${PYCMD[*]})"
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
