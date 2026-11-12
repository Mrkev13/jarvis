#!/usr/bin/env bash
# MRK-108 automatic updater v3. Install as root-owned file. Run under the existing maintenance-lock wrapper.
set -Eeuo pipefail
umask 077

MODE="${1:---check}"
[[ "$MODE" == --check || "$MODE" == --apply ]] || { echo 'Usage: auto-update-v2.sh --check|--apply' >&2; exit 2; }
[[ "$EUID" -eq 0 && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }

ROOT=/home/standa/projects/jarvis-mrk101
TRUSTED=/usr/local/lib/standa-hub/mrk108
RELEASES=/srv/standa-hub/releases
BRANCH=mrk-101-ubuntu-production
API_URL=https://<tailnet-host>:8443
TRANSACTION=/usr/local/lib/standa-hub/deploy-transaction-v3.sh

for path in "$TRUSTED/check-backup.py" "$TRUSTED/verify-release.py" "$TRANSACTION"; do
  [[ -f "$path" && ! -L "$path" && $(stat -c %u "$path") == 0 ]] || { echo "UNTRUSTED_HELPER: $path" >&2; exit 1; }
done
[[ -d "$RELEASES" && ! -L "$RELEASES" ]] || { echo 'RELEASE_DIRECTORY_NOT_READY' >&2; exit 1; }

echo '=== FETCH PRODUCTION BRANCH ==='
runuser -u standa -- git -C "$ROOT" fetch origin \
  "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
TARGET=$(runuser -u standa -- git -C "$ROOT" rev-parse --verify "refs/remotes/origin/$BRANCH^{commit}")
[[ "$TARGET" =~ ^[0-9a-f]{40}$ ]] || { echo 'INVALID_TARGET_SHA' >&2; exit 1; }

CURRENT=$(docker inspect standa-hub-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^APP_COMMIT=//p' | head -n 1)
[[ "$CURRENT" =~ ^[0-9a-f]{40}$ ]] || { echo 'CURRENT_COMMIT_UNKNOWN' >&2; exit 1; }
echo "Current: $CURRENT"
echo "Target:  $TARGET"

# Block updates on unfinished transactions even when GitHub is unchanged.
"$TRANSACTION" --check "$CURRENT"

if [[ "$CURRENT" == "$TARGET" ]]; then
  "$TRANSACTION" --check "$TARGET"
  echo 'NO_UPDATE_NEEDED'
  exit 0
fi

# Do not automatically downgrade or diverge from deployed production history.
if ! runuser -u standa -- git -C "$ROOT" merge-base --is-ancestor "$CURRENT" "$TARGET"; then
  echo 'NON_FAST_FORWARD_RELEASE_BLOCKED' >&2
  exit 1
fi

# GitHub approval and backup freshness before any build.
runuser -u standa -- "$ROOT/deploy/scripts/check-ci.sh" "$TARGET"
python3 -I "$TRUSTED/check-backup.py"

RELEASE="$RELEASES/$TARGET"
if [[ -e "$RELEASE" && ( ! -d "$RELEASE" || -L "$RELEASE" ) ]]; then
  echo 'INVALID_RELEASE_DIRECTORY' >&2
  exit 1
fi
if [[ ! -e "$RELEASE" ]]; then
  TEMP=$(mktemp -d "$RELEASES/.prepare.XXXXXXXX")
  cleanup() { [[ -z ${TEMP:-} ]] || rm -rf -- "$TEMP"; }
  trap cleanup EXIT
  # Reject traversal and unsafe tar members before files are used by root.
  runuser -u standa -- git -C "$ROOT" archive "$TARGET" |
    python3 -I -c '
import sys, tarfile
from pathlib import Path
root = Path(sys.argv[1])
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as archive:
    archive.extractall(path=root, filter="data")
' "$TEMP"
  mv -T -- "$TEMP" "$RELEASE"
  TEMP=''
fi
python3 -I "$TRUSTED/verify-release.py" "$TARGET"

for sub in backend frontend; do
  [[ -f "$RELEASE/$sub/Dockerfile" && -f "$RELEASE/$sub/.dockerignore" ]] || {
    echo "RELEASE_BUILD_INPUT_MISSING: $sub" >&2; exit 1;
  }
done

# Images must be constructed from the verified isolated release, not the dirty production tree.
echo '=== BUILD BACKEND ==='
if ! docker image inspect "standa-hub-backend:$TARGET" >/dev/null 2>&1; then
  docker build --label "org.opencontainers.image.revision=$TARGET" \
  -t "standa-hub-backend:$TARGET" "$RELEASE/backend"
fi
echo '=== BUILD FRONTEND ==='
if ! docker image inspect "standa-hub-frontend:$TARGET" >/dev/null 2>&1; then
  docker build --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
  --label "org.opencontainers.image.revision=$TARGET" \
  -t "standa-hub-frontend:$TARGET" "$RELEASE/frontend"
fi

for sub in backend frontend; do
  IMAGE="standa-hub-$sub:$TARGET"
  [[ $(docker image inspect "$IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || {
    echo "BAD_BUILT_IMAGE: $IMAGE" >&2; exit 1;
  }
done

"$TRANSACTION" --check "$TARGET"
if [[ "$MODE" == --check ]]; then
  echo 'UPDATE_READY_CHECK_ONLY'
  exit 0
fi
"$TRANSACTION" --apply "$TARGET"
echo 'AUTO_UPDATE_DEPLOYED'
