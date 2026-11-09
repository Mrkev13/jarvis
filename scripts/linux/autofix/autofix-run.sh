#!/usr/bin/env bash
# MRK-97: runs INSIDE the disposable autofix container (scripts/linux/autofix/Dockerfile), never on the host.
#
# Input:  /src (read-only) = the PR's tracked files at the reviewed commit - a plain file tree, NO .git;
#         /prompt.md (read-only) = the task with the review text; the dedicated Claude token in the environment.
# Work:   the tree is copied to /work (size-limited tmpfs; the stage in /tmp is a tmpfs too). Claude may only read and edit files there - no shell,
#         no git, no web (allowlist + dontAsk). So NO code from the PR (tests, setup or npm scripts) runs anywhere
#         near the token; CI runs the tests after the push, and Codex reviews the result again.
# Output: a tar on stdout with answer.md (Claude's summary) and tree/ (the edited files). The trusted host script
#         (claude-fix.sh) caps its size, unpacks it safely, builds the commit itself, checks it and pushes.
set -uo pipefail

SRC_DIR="${SRC_DIR:-/src}"
WORK_DIR="${WORK_DIR:-/work}"
STAGE_DIR="${STAGE_DIR:-/tmp/stage}"
PROMPT_FILE="${PROMPT_FILE:-/prompt.md}"
CLAUDE="${CLAUDE:-claude}"
MAX_ANSWER_BYTES=200000

# Read and edit files only. Everything else is refused in dontAsk mode; the denials are belt and braces.
ALLOWED_TOOLS=(Read Edit Write Glob Grep)
DENIED_TOOLS=(Bash WebFetch WebSearch NotebookEdit)

budget=()
[[ -n "${CLAUDE_BUDGET_USD:-}" ]] && budget=(--max-budget-usd "$CLAUDE_BUDGET_USD")

mkdir -p "$STAGE_DIR"
cp -a "$SRC_DIR/." "$WORK_DIR/"
cd "$WORK_DIR" || exit 3

claude_exit=0
"$CLAUDE" -p "$(cat "$PROMPT_FILE")" --permission-mode dontAsk --output-format text \
  --allowedTools "${ALLOWED_TOOLS[@]}" --disallowedTools "${DENIED_TOOLS[@]}" "${budget[@]}" \
  </dev/null >"$STAGE_DIR/answer.raw" 2>"$STAGE_DIR/claude.log" || claude_exit=$?
head -c "$MAX_ANSWER_BYTES" "$STAGE_DIR/answer.raw" >"$STAGE_DIR/answer.md"
echo "$claude_exit" >"$STAGE_DIR/claude.exit"

# stdout = the only channel back to the host
tar -cf - -C "$STAGE_DIR" answer.md claude.exit -C "$WORK_DIR" --transform 's,^\./,tree/,' .
