#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:?Usage: check-ci.sh COMMIT_SHA}"
REPO="Mrkev13/jarvis"

if [[ ! "$TARGET" =~ ^[0-9a-f]{40}$ ]]; then
  echo "INVALID_COMMIT_SHA"
  exit 1
fi

command -v gh >/dev/null || {
  echo "GITHUB_CLI_MISSING"
  exit 1
}

echo "=== VERIFY CI: $TARGET ==="

RUNS="$(gh api \
  "repos/$REPO/actions/workflows/ci.yml/runs?head_sha=$TARGET&event=push&per_page=20" \
  --jq '[.workflow_runs[]
    | select(.head_sha == "'"$TARGET"'")
    | select(.event == "push")
    | {id, status, conclusion, created_at}]')"

COUNT="$(echo "$RUNS" | python3 -c \
  'import json,sys; print(len(json.load(sys.stdin)))')"

if [[ "$COUNT" -eq 0 ]]; then
  echo "CI_NOT_FOUND"
  exit 1
fi

STATUS="$(echo "$RUNS" | python3 -c '
import json,sys
runs=json.load(sys.stdin)
runs.sort(key=lambda x:(x["created_at"],x["id"]),reverse=True)
run=runs[0]
print(run["status"],run["conclusion"])
')"

if [[ "$STATUS" != "completed success" ]]; then
  echo "CI_NOT_APPROVED: $STATUS"
  exit 1
fi

echo "CI_APPROVED"
