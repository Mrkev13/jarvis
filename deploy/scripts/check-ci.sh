#!/usr/bin/env bash
# MRK-108: is the exact commit approved by CI on the production branch? Installed root-owned as
# /usr/local/lib/standa-hub/mrk108/check-ci.sh and run as the git user (its `gh` login), never from the dev checkout.
#
# Approved = the newest `ci.yml` workflow run for a push of exactly this SHA to the production branch is completed with
# conclusion success. A run on another branch (same SHA pushed elsewhere), another workflow, a PR run or a run still in
# progress is not an approval.
set -euo pipefail

TARGET="${1:?Usage: check-ci.sh COMMIT_SHA}"
REPO="${DEPLOY_REPO:-Mrkev13/jarvis}"
BRANCH="${DEPLOY_BRANCH:-mrk-101-ubuntu-production}"

if [[ ! "$TARGET" =~ ^[0-9a-f]{40}$ ]]; then
  echo "INVALID_COMMIT_SHA"
  exit 1
fi
if [[ ! "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "INVALID_BRANCH"
  exit 1
fi

command -v gh >/dev/null || {
  echo "GITHUB_CLI_MISSING"
  exit 1
}

echo "=== VERIFY CI: $TARGET on $BRANCH ==="

RUNS="$(gh api \
  "repos/$REPO/actions/workflows/ci.yml/runs?head_sha=$TARGET&branch=$BRANCH&event=push&per_page=20")"

STATUS="$(printf '%s' "$RUNS" | python3 -I -c '
import json, sys
target, branch = sys.argv[1], sys.argv[2]
runs = [r for r in json.load(sys.stdin).get("workflow_runs", [])
        if r.get("head_sha") == target and r.get("head_branch") == branch and r.get("event") == "push"
        and r.get("path", "").split("@")[0] == ".github/workflows/ci.yml"]
if not runs:
    print("CI_NOT_FOUND")
else:
    run = max(runs, key=lambda r: (r["created_at"], r["id"]))
    print(run["status"], run["conclusion"])
' "$TARGET" "$BRANCH")"

if [[ "$STATUS" == "CI_NOT_FOUND" ]]; then
  echo "CI_NOT_FOUND"
  exit 1
fi
if [[ "$STATUS" != "completed success" ]]; then
  echo "CI_NOT_APPROVED: $STATUS"
  exit 1
fi

echo "CI_APPROVED"
