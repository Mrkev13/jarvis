#!/usr/bin/env bash
# MRK-108 automatic updater v3. Install as root-owned file. Run under the existing maintenance-lock wrapper.
#
# Review fixes on top of the audited production copy (deploy/v3/SHA256SUMS.original, PR #65):
# - Images are always built from the verified release with --iidfile; the resulting image IDs go to a root-only
#   provenance record that the transaction requires. A pre-existing tag with the right revision label is no proof.
# - check-ci.sh is the root-owned copy in $TRUSTED (run as the git user for its gh login), never the dev checkout's.
# - Configuration via DEPLOY_* variables with production defaults (tests); DEPLOY_NEXT_PUBLIC_API_URL is required and
#   comes from a local systemd drop-in, so no hostname lives in Git.
set -Eeuo pipefail
umask 077

MODE="${1:---check}"
[[ "$MODE" == --check || "$MODE" == --apply ]] || { echo 'Usage: auto-update-v3.sh --check|--apply' >&2; exit 2; }

ROOT=${DEPLOY_ROOT:-/home/standa/projects/jarvis-mrk101}
TRUSTED=${DEPLOY_TRUSTED:-/usr/local/lib/standa-hub/mrk108}
RELEASES=${DEPLOY_RELEASES:-/srv/standa-hub/releases}
STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/standa-hub/deployments}
BRANCH=${DEPLOY_BRANCH:-mrk-101-ubuntu-production}
API_URL=${DEPLOY_NEXT_PUBLIC_API_URL:-https://<tailnet-host>:8443}
TRANSACTION=${DEPLOY_TRANSACTION:-/usr/local/lib/standa-hub/deploy-transaction-v3.sh}
REQUIRED_UID=${DEPLOY_REQUIRED_UID:-0}
GIT_USER=${DEPLOY_GIT_USER-standa}

[[ "$EUID" -eq "$REQUIRED_UID" && -e /proc/self/fd/9 ]] || { echo 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' >&2; exit 1; }
[[ $API_URL == https://* && $API_URL != *'<'* ]] || { echo 'NEXT_PUBLIC_API_URL_NOT_CONFIGURED' >&2; exit 1; }
for path in "$TRUSTED/check-backup.py" "$TRUSTED/verify-release.py" "$TRUSTED/check-ci.sh" "$TRANSACTION"; do
  [[ -f "$path" && ! -L "$path" && $(stat -c %u "$path") == "$REQUIRED_UID" ]] || { echo "UNTRUSTED_HELPER: $path" >&2; exit 1; }
done
as_git_user() { if [[ -n $GIT_USER ]]; then runuser -u "$GIT_USER" -- "$@"; else "$@"; fi; }
[[ -d "$RELEASES" && ! -L "$RELEASES" ]] || { echo 'RELEASE_DIRECTORY_NOT_READY' >&2; exit 1; }

echo '=== FETCH PRODUCTION BRANCH ==='
as_git_user git -C "$ROOT" fetch origin \
  "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
TARGET=$(as_git_user git -C "$ROOT" rev-parse --verify "refs/remotes/origin/$BRANCH^{commit}")
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
if ! as_git_user git -C "$ROOT" merge-base --is-ancestor "$CURRENT" "$TARGET"; then
  echo 'NON_FAST_FORWARD_RELEASE_BLOCKED' >&2
  exit 1
fi

# GitHub approval and backup freshness before any build.
as_git_user "$TRUSTED/check-ci.sh" "$TARGET"
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
  as_git_user git -C "$ROOT" archive "$TARGET" |
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

# Images must be constructed from the verified isolated release, not the dirty production tree. Always build (the
# layer cache keeps it fast) and record the produced image IDs: an existing tag is never trusted on its own.
IDS=$(mktemp -d)
trap 'rm -rf -- "$IDS"; [[ -z ${TEMP:-} ]] || rm -rf -- "$TEMP"' EXIT
echo '=== BUILD BACKEND ==='
docker build --label "org.opencontainers.image.revision=$TARGET" --iidfile "$IDS/backend" \
  -t "standa-hub-backend:$TARGET" "$RELEASE/backend"
echo '=== BUILD FRONTEND ==='
docker build --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
  --label "org.opencontainers.image.revision=$TARGET" --iidfile "$IDS/frontend" \
  -t "standa-hub-frontend:$TARGET" "$RELEASE/frontend"

for sub in backend frontend; do
  IMAGE="standa-hub-$sub:$TARGET"
  BUILT=$(cat "$IDS/$sub")
  [[ $BUILT =~ ^sha256:[0-9a-f]{64}$ && $(docker image inspect "$IMAGE" --format '{{.Id}}') == "$BUILT" ]] || {
    echo "BUILT_IMAGE_TAG_MISMATCH: $IMAGE" >&2; exit 1;
  }
  [[ $(docker image inspect "$BUILT" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}') == "$TARGET" ]] || {
    echo "BAD_BUILT_IMAGE: $IMAGE" >&2; exit 1;
  }
done

# Root-only provenance record (atomic write); the transaction trusts the target tags only if they still point here.
install -d -m 700 "$STATE_DIR/provenance"
python3 -I - "$STATE_DIR/provenance/$TARGET.json" "$TARGET" "$(cat "$IDS/backend")" "$(cat "$IDS/frontend")" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
path,target,backend,frontend=sys.argv[1:]
d={'target_commit':target,'release_verified':True,'built_at':datetime.now(timezone.utc).isoformat(),
   'images':{'backend':{'image_id':backend},'frontend':{'image_id':frontend}}}
fd,tmp=tempfile.mkstemp(prefix='.provenance.',dir=os.path.dirname(path))
try:
    with os.fdopen(fd,'w') as f:
        json.dump(d,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,path)
finally:
    if os.path.exists(tmp):os.unlink(tmp)
print('IMAGE_PROVENANCE_RECORDED')
PY

"$TRANSACTION" --check "$TARGET"
if [[ "$MODE" == --check ]]; then
  echo 'UPDATE_READY_CHECK_ONLY'
  exit 0
fi
"$TRANSACTION" --apply "$TARGET"
echo 'AUTO_UPDATE_DEPLOYED'
