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

`deploy-transaction-v3.sh` was deliberately left at `02a965c`, which does **not** read restart journals. Known gap
until a version with the pending-restart block (`7d6ba62` or later) is installed: the config-hash drift check catches
a restart interrupted *before* the backend was recreated, but not one interrupted *after* the recreate and before a
terminal journal state (e.g. `verifying`) - the container already runs the new env, its hash matches the live file,
and the updater would carry on (`ALREADY_DEPLOYED` / deploy a new commit) before the restart is recovered (Codex
review of PR #76, reproduced in the isolated tests). Operating rule until then: if `restart-v3.sh --apply` does not
end with `RESTART_OK` or `ROLLBACK_VERIFIED`, stop the timer
(`sudo systemctl stop standa-hub-auto-update.timer`), run `restart-v3.sh --recover`, and start the timer again only
after the restart journal is terminal (`restarted`, `rolled_back` or `aborted`).

Run: `restart-v3.sh --check` → `PREVIOUS_ENV_RECONSTRUCTED`, `ENV_VALID`, `RESTART_PREFLIGHT_OK`; `--apply` at
2026-11-21T17:54:09Z (journal `restart-v3-20261121T175409Z-1152408`). Verified afterwards:

- backend env: the five switches `true`, `BACKUP_ENABLED=false`, calendar feeds and VAPID key set; `/health`
  healthy, commit unchanged (`d11a5f2`);
- Calendar → Synchronizovat works (Google and Moodle); a test reminder arrived on the phone;
- updater: `BACKEND_COMPOSE_DRIFT` before the restart, `ALREADY_DEPLOYED` after it, then deployed `cf5d5b3`
  (`AUTO_UPDATE_DEPLOYED`) on its own.

## 2026-11-22 – migration tooling installed, first `--check` of release `6526411` (MRK-114)

Why: release PR #83 (`main@f2b9ac9`, Alembic `0028_school_progress` → `0030_memory_lifecycle`) needs the controlled
migration deployment. Before installing, the root-only files were verified unchanged against the last recorded state
(`deploy-transaction-v3.sh` `8fb0e6e8…` = `02a965c`, `backup.sh` `232c2892…`, `mrk108/check-ci.sh` `a0ee7354…`,
`mrk108/backend-managed.yaml` `9c318778…`, `mrk108/frontend-managed.yaml` `088d3e88…`, updater service inactive).

Installed from `mrk-101-ubuntu-production` at `adf962e` with the timer stopped (root, scripts 0755, helpers 0644;
SHA-256 prefix):

| File | SHA-256 |
| --- | --- |
| `/usr/local/lib/standa-hub/deploy-migration-v3.sh` (new) | `41a3642bcdde…` |
| `/usr/local/lib/standa-hub/deploy-transaction-v3.sh` (`02a965c` → repo version: pending migration / restart / template journals block it) | `d3a5acebeb47…` |
| `/usr/local/lib/standa-hub/restart-v3.sh` (MRK-121 version) | `1a20a47cd156…` |
| `/usr/local/lib/standa-hub/frontend-template-v3.sh` (new) | `341e547fbb2f…` |
| `/usr/local/lib/standa-hub/mrk108/check-migration.py` (new) | `350edc677e71…` |
| `/usr/local/lib/standa-hub/mrk108/compat-smoke.py` (new) | `9704a6eecc4d…` |
| `/usr/local/lib/standa-hub/mrk108/migration-journal.py` (new) | `c7a2c69db64f…` |

`frontend-managed.yaml` deliberately **not** replaced (MRK-121 goes through `frontend-template-v3.sh`). The known gap of
the 2026-11-21 entry (old updater not reading restart journals) is closed by the new `deploy-transaction-v3.sh`.

After the merge of #83 the updater built the target images and stopped on `MIGRATION_HEAD_CHANGED` (as designed). The
timer was then stopped for the controlled deployment (it held the maintenance lock while rebuilding every 10 minutes;
`--check` ended with `MAINTENANCE_LOCK_TIMEOUT`).

`deploy-migration-v3.sh --check 6526411…`: preflight passed (`CI_APPROVED`, `BACKUP_VERIFIED` 18.2 h,
`TARGET_IMAGE_PROVENANCE_VERIFIED`, `PRODUCTION_DATABASE_AT_OLD_HEAD`, `MIGRATION_OPS_ADDITIVE`,
`COMPOSE_HASHES_MATCH_RUNNING`, `REHEARSAL_RESTORE_OK`), then `REHEARSAL_APP_UNHEALTHY: …-old (strict)` – **no
production change**. Two defects of the rehearsal that the fake docker could not show (the reason MRK-114 asked for a
real run first):

1. the throwaway copy was named `rehearsal`; the app refuses a `DATABASE_URL` whose database is not
   `PRODUCTION_DATABASE_NAME` (`production.guard_production_environment`, also in `alembic` via `models`);
2. `docker compose config --format json` prints every literal `$` as `$$` (verified with Compose v5.6); written to a
   `docker --env-file` unchanged, the bcrypt `AUTH_PIN_HASH` becomes invalid and the app refuses to start.

Fixed in the follow-up PR (copy uses the production database name; rendered env unescaped) with regression tests on a
production-like environment. Next: install the fixed `deploy-migration-v3.sh`, `--check`, `--apply`, start the timer.

Second `--check` (fixed script `a11b90d1dfcd…`, #84): `REHEARSAL_OLD_APP_BASELINE_OK`, `REHEARSAL_MIGRATION_OK`,
`REHEARSAL_NEW_APP_OK`, then `REHEARSAL_APP_UNHEALTHY: …-old (old-on-new)` – again no production change. Third defect:
the old code cannot name a revision it does not know (backend `health_service` reports it as `"unknown"`), so the
old-on-new comparison of that name with the new head could never pass – also in the app-rollback compatibility check.
Fixed in the next PR: the old app's `/health` has to agree (reachable, the new head or `unknown`), the revision itself
is read from the database (the copy, or production before an app rollback).

Third `--check` (script `755ec8506356…`, #85): all rehearsal steps passed (`REHEARSAL_OLD_APP_COMPATIBLE`,
`MIGRATION_PREFLIGHT_OK`, `NO_PRODUCTION_CHANGES`).

`deploy-migration-v3.sh --apply 6526411…` (22 November 2026, updater timer stopped, maintenance lock): fresh backup
(ID 60, `BACKUP_VERIFIED`, age 0.0 h) → rehearsal on a copy of that backup (all steps OK) → journal `prepared →
rehearsed → db_migrating → db_migrated → deploying → verifying → deployed` → `MIGRATION_DEPLOYMENT_OK`. Production
database `0028_school_progress` → `0030_memory_lifecycle`; backend and frontend recreated through the managed templates
and healthy. Afterwards the timer was started again; backend `/health`: `healthy`, migrations `current`
(`0030_memory_lifecycle`), commit `6526411`, scheduler `running`. The later commits on the production branch (#84,
#85: deploy tooling and tests only, no Alembic change) are left to the updater.

Installed `deploy-migration-v3.sh` is `755ec8506356…` (= repository after #85).

## 2026-11-22 – frontend template with the game-assets volume (MRK-121)

Why: WoT/MFF images live outside Git and the image, in `/srv/standa-hub-data/game-assets` (1034 files, copied from the
Windows machine; directory root 755, files 644). The frontend mounts it read-only (`frontend-managed.yaml` at
`mrk-101-ubuntu-production`, SHA-256 `17223cfef4d4…`).

With the updater timer stopped (it had just deployed `0f4f17d` by itself): new template installed as
`/root/frontend-managed.new.yaml` (root 0644, `17223cfef4d4…`) → `frontend-template-v3.sh --check`
(`INSTALLED_TEMPLATE_MATCHES_RUNNING`, diff = only the `volumes:` entry, `TEMPLATE_PREFLIGHT_OK`,
`NO_PRODUCTION_CHANGES`) → `--apply`: journal `prepared → recreating → verifying → restarted`, frontend recreated with
the same image and healthy, `FRONTEND_TEMPLATE_APPLIED` (the installed `mrk108/frontend-managed.yaml` is now the new
template). Verified: mount `/srv/standa-hub-data/game-assets -> /app/public/game-assets ro=true`; timer started again
(`active`).
