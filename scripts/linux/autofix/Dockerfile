# MRK-97: disposable sandbox for automatic fixes (built once on the Ubuntu host from the INSTALLED copy, see
# docs/operations.md). Python 3.12 + Node 22 like CI, git, and Claude Code CLI. Runs as the host user's uid with
# a read-only root filesystem; the PR code only ever runs in here.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Pin the CLI version you checked (`claude --version` on the host): docker build --build-arg CLAUDE_CODE_VERSION=x.y.z
ARG CLAUDE_CODE_VERSION=latest
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && npm cache clean --force
COPY autofix-run.sh /usr/local/bin/autofix-run
RUN chmod 755 /usr/local/bin/autofix-run
WORKDIR /work
