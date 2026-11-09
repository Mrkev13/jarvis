#!/usr/bin/env bash
# MRK-97: runs INSIDE the disposable autofix container (scripts/linux/autofix/Dockerfile), never on the host.
#
# The container gets only: /work (a fresh clone of the PR branch, no host config, no hooks), /prompt.md (read-only),
# /out (results) and the dedicated Claude token from the env file. No GitHub token, no host files, no production.
# Claude edits and commits inside /work; this script then writes the new commits as a git bundle to /out. The
# trusted host script (claude-fix.sh) verifies the bundle and is the only one that pushes.
#
#   autofix-run <reviewed head sha>
# Outputs: $OUT_DIR/answer.md (Claude's summary), claude.exit, fix.bundle (only when there are new commits).
set -uo pipefail

HEAD_SHA="${1:?usage: autofix-run <head sha>}"
OUT_DIR="${OUT_DIR:-/out}"
PROMPT_FILE="${PROMPT_FILE:-/prompt.md}"
CLAUDE="${CLAUDE:-claude}"

# What Claude may do without asking (dontAsk refuses everything else). Inside the container these are conveniences,
# not the security boundary - the container is.
ALLOWED_TOOLS=(Read Edit Write Glob Grep
  "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git add:*)" "Bash(git commit:*)"
  "Bash(bash scripts/setup-dev.sh:*)" "Bash(.venv/bin/python -m pytest:*)" "Bash(.venv/bin/python -m pyflakes:*)"
  "Bash(npm run lint:*)" "Bash(npm test:*)" "Bash(npm run build:*)" "Bash(npx tsc:*)" "Bash(cd:*)" "Bash(ls:*)")
DENIED_TOOLS=("Bash(git push:*)" "Bash(gh:*)" "Bash(curl:*)" "Bash(wget:*)" WebFetch WebSearch)

budget=()
[[ -n "${CLAUDE_BUDGET_USD:-}" ]] && budget=(--max-budget-usd "$CLAUDE_BUDGET_USD")

git config --global --add safe.directory "$PWD"
git config --global user.name "Claude (autofix)"
git config --global user.email "noreply@anthropic.com"

claude_exit=0
"$CLAUDE" -p "$(cat "$PROMPT_FILE")" --permission-mode dontAsk --output-format text \
  --allowedTools "${ALLOWED_TOOLS[@]}" --disallowedTools "${DENIED_TOOLS[@]}" "${budget[@]}" \
  </dev/null >"$OUT_DIR/answer.md" 2>"$OUT_DIR/claude.log" || claude_exit=$?
echo "$claude_exit" >"$OUT_DIR/claude.exit"

# Only commits on top of the reviewed head travel back; nothing else from this container is used.
if git merge-base --is-ancestor "$HEAD_SHA" HEAD 2>/dev/null && [[ "$(git rev-list --count "$HEAD_SHA..HEAD")" -gt 0 ]]; then
  git bundle create --quiet "$OUT_DIR/fix.bundle" HEAD "^$HEAD_SHA"
fi
exit 0
