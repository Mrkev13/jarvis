#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="/run/standa-hub/maintenance.lock"

if [[ $# -eq 0 ]]; then
  echo "Usage: with-deployment-lock.sh COMMAND [ARGS...]" >&2
  exit 2
fi

exec 9>"$LOCK_FILE"

if ! flock -w 300 9; then
  echo "MAINTENANCE_LOCK_TIMEOUT" >&2
  exit 1
fi

echo "MAINTENANCE_LOCK_ACQUIRED"

"$@"
