# MRK-108 v3 – production changes after the import

`SHA256SUMS.original` stays the proof of the state at the first import (commit 4f5049e). Changes made directly on
the production server afterwards are recorded here, newest last, with the SHA-256 of the installed file.

## 2026-11-12 – CI check from the root-owned copy

Changed on the Ubuntu server:

- `/usr/local/lib/standa-hub/auto-update-v3.sh`
- `/usr/local/lib/standa-hub/deploy-transaction-v3.sh`

In both scripts, the CI check path changed from `$ROOT/deploy/scripts/check-ci.sh` (the dev checkout) to
`/usr/local/lib/standa-hub/mrk108/check-ci.sh` (root:root, 755, SHA-256
`4d9e271e86aefbaf6f6c91cc1ab02d51c81345037a78555c6ecd31ba01b42334` = `deploy/scripts/check-ci.sh` at 932e2fc).
The call stays `runuser -u standa -- "/usr/local/lib/standa-hub/mrk108/check-ci.sh" "$TARGET"`.

| Installed file | SHA-256 after the change |
| --- | --- |
| `auto-update-v3.sh` | `53afd9fd74946df401eade57f3d7a53c04239eb44075059f1d92a3b48c579dfc` |
| `deploy-transaction-v3.sh` | `c3f1de5020ce7711e230d3d8851d9893291f7c1e6d58a3d7752eec06d6f36019` |

The sums identify the installed files; they cannot be recomputed from this repository because the copies here are
redacted (`<tailnet-host>`) and carry the PR #65 review changes. The scope of the edit (only the CI path) was checked
on the server when it was made.

Verified on the server: the CI check for production commit `32db7b8` → `CI_APPROVED`, exit 0; the systemd updater run
afterwards → `Result=success`, `ExecMainStatus=0`, `NO_UPDATE_NEEDED`.

Not deployed: the PR #65 review version (da866d5 and later). Automatic `--apply` stays off.

## Before 2026-11-21 – reviewed `deploy-transaction-v3.sh` installed (recorded afterwards)

Found on 21 November 2026: the installed `/usr/local/lib/standa-hub/deploy-transaction-v3.sh` is no longer the copy
recorded above. Its SHA-256 `8fb0e6e8b7074f8c871795b5161077d5eefedbcfed059671e1c5e9ba4e432c83` is exactly
`deploy/v3/lib/deploy-transaction-v3.sh` at `02a965c` (PR #65 review version with the normalized Compose hash). The
install date was not recorded. The later repository changes of this file (`bfeb894` archive PID, `a8d3e7e` /
`0e768a7` MRK-114 migration blocking, `7d6ba62` MRK-120 restart blocking) are **not** installed;
`deploy-migration-v3.sh` is not installed. The updater has run the 10-minute timer with `--apply` (deployments of
`d11a5f2` on 15 November and `cf5d5b3` on 21 November).

## 2026-11-21 – env-only backend restart (MRK-120)

Why: the Ubuntu `backend/.env.production` still had the cut-over values - scheduler, reminders, briefings and Web
Push off, VAPID keys and calendar feeds empty (MRK-103). Compose reads `env_file` only when it creates a container and
puts the values into the config-hash, so after the edit the updater stopped on `BACKEND_COMPOSE_DRIFT`.

Changed on the Ubuntu server (values never left the server; only names, states and checksums are recorded):

| Change | Detail |
| --- | --- |
| `/srv/standa-hub/backend/.env.production` owner | `standa:standa 600` → `root:root 600` (restart-v3.sh requires a root-owned env file) |
| `.env.production` content | changed variables: `SCHEDULER_ENABLED`, `REMINDERS_CHECK_ENABLED`, `DAILY_BRIEFING_ENABLED`, `WEEKLY_REVIEW_ENABLED`, `EXTERNAL_DELIVERY_ENABLED` (all `true`), `WEB_PUSH_VAPID_PRIVATE_KEY`, `WEB_PUSH_VAPID_PUBLIC_KEY`, `WEB_PUSH_CONTACT` (the Windows keys), `GOOGLE_ICS_URL`, `MOODLE_ICS_URL`; `BACKUP_ENABLED` stays `false` (`standa-hub-backup.timer` owns backups) |
| `/usr/local/lib/standa-hub/restart-v3.sh` (new, root 755) | `148e85cebb5eb0fe1eb46509e04120d3a38abb23bc62136fc42ed5cd325c41cb` = `deploy/v3/lib/restart-v3.sh` at `cf5d5b3` |
| `/usr/local/lib/standa-hub/mrk108/restart-journal.py` (new, root 644) | `bbdf1cdb8f00e120c2590b2993d49c59dff57e0d42081bda07e235d04fd5aa35` = `deploy/v3/mrk108/restart-journal.py` at `cf5d5b3` |

`deploy-transaction-v3.sh` was deliberately left at `02a965c`, so the updater does not yet wait for a pending
restart (a crashed restart is still caught by the config-hash drift check).

Run: `restart-v3.sh --check` → `PREVIOUS_ENV_RECONSTRUCTED`, `ENV_VALID`, `RESTART_PREFLIGHT_OK`; `--apply` at
2026-11-21T17:54:09Z (journal `restart-v3-20261121T175409Z-1152408`). Verified afterwards:

- backend env: the five switches `true`, `BACKUP_ENABLED=false`, calendar feeds and VAPID key set; `/health`
  healthy, commit unchanged (`d11a5f2`);
- Calendar → Synchronizovat works (Google and Moodle); a test reminder arrived on the phone;
- updater: `BACKEND_COMPOSE_DRIFT` before the restart, `ALREADY_DEPLOYED` after it, then deployed `cf5d5b3`
  (`AUTO_UPDATE_DEPLOYED`) on its own.
