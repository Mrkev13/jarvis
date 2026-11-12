# MRK-108 deployment v3 (audited copy + review fixes)

`deploy/v3/` started as an exact, sanitized copy of the production files (`SHA256SUMS.original`, `REDACTIONS.md`,
commit 4f5049e). Later commits in PR #65 change them on purpose; the diff against 4f5049e is the review record.
Changes made on the server after the import are recorded in `PRODUCTION_CHANGES.md`.
**Nothing here is installed automatically, and `--apply` stays off** until the isolated test on a second commit
(MRK-108 step 5) has passed.

## Review fixes (PR #65)

| Finding | Fix |
| --- | --- |
| `prepared` journal could block every later deployment | `prepared` → new terminal state `aborted` (on failure automatically, after power loss via `--recover`), only when both containers still run the journal's previous image IDs; the directory is renamed `transaction-v3-<SHA>.aborted-<UTC>` so the target can be retried |
| Transaction directory without journal | Assembled in `.staging-v3-<SHA>.*` and published by one atomic rename (a visible directory always has a journal). Staging leftovers never touched a container and are removed by `--apply` / `--recover`; a journal-less directory from the old script is removed by `--recover` after the running services are verified unchanged and healthy |
| Interrupted rollback | Stays `rollback_required`; `--recover` repeats it (tested) |
| After a rollback every update stopped on `*_COMPOSE_DRIFT` | Rollback starts the previous images through the same managed templates (the old snapshot + `pull_policy` override changed the config-hash); the template rendered with the previous values must equal the saved snapshot, otherwise `MANAGED_CONFIG_CHANGED_SINCE_SNAPSHOT` → manual |
| After a successful v3 deploy every `--check` failed with `TRANSACTION_ALREADY_EXISTS` | The existence check comes after the "already deployed" case |
| Image trusted by its revision label | The updater always builds from the verified release with `--iidfile` and writes a root-only provenance record (`$STATE_DIR/provenance/<SHA>.json`, 0600); the transaction requires the target tags to point at exactly those IDs and records them in the journal |
| CI gate not bound to the branch | `check-ci.sh` (root-owned copy in `mrk108/`) accepts only the newest `ci.yml` push run for exactly this SHA on the production branch, completed with success |
| Tailnet hostname in scripts | `DEPLOY_NEXT_PUBLIC_API_URL` from a local systemd drop-in (`20-local.conf.example`); the placeholder is refused |

Open: `--check` still builds images (P2); snapshots in `/var/lib/standa-hub/deployments` hold secrets (root, 0700) and
have no retention yet; Alembic head changes still block automatic deployment (migration `0029` needs a controlled
procedure); no restart without a version change; WoT game-assets as an external read-only volume.

## Tests

`backend/tests/test_deploy_v3.py` runs the real updater, transaction, journal, release and backup checks against a fake
`docker` / `curl` / `gh` and a real git repository with a local origin: happy path, `--check`, migration head change,
unhealthy backend, failed frontend start, power loss while deploying, during the rollback and in `prepared`, a changed
container in `prepared`, journal-less and staging directories, re-tagged or unrecorded target images, the CI gate.
`DEPLOY_*` variables point the scripts at temporary paths and the current UID; the systemd unit sets only
`DEPLOY_NEXT_PUBLIC_API_URL`.

## Installing (only after step 5 of MRK-108)

Root-owned, no symlinks: `lib/*.sh` → `/usr/local/lib/standa-hub/`, `mrk108/*` and `../scripts/check-ci.sh` →
`/usr/local/lib/standa-hub/mrk108/`, `systemd/` units and drop-ins → `/etc/systemd/system/`, plus the local
`20-local.conf`. Keep the updater on `--check` until the second-commit test (including a failure, rollback and an
interrupted transaction) has passed on the isolated environment.
