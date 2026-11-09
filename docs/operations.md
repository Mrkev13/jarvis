# Production runtime (MRK-23 v2)

Current target: Windows, native Python/Node processes, one backend scheduler owner.
**Docker Desktop is not required.** Future Linux service integration is separate;
the application commands below remain portable. This branch has cloud proof only.

## Configuration and preparation

Use a separate production installation/worktree, production PostgreSQL database,
media directory and backup directory. Do not reuse the development database by
accident. Install Python 3.12, Node 24/npm, PostgreSQL and matching `pg_dump`.
Follow [README](../README.md) and `scripts/setup-dev.sh` for dependencies.

Copy [backend/.env.production.template](../backend/.env.production.template) to an
ignored, protected local file (for example `backend/.env.production`). Fill it
locally; never commit or paste its contents. The launcher requires the FILE to
contain all required settings, overriding inherited values for those settings:

- `APP_ENV=production`, explicit `DATABASE_URL` with PostgreSQL host/database,
  `PRODUCTION_DATABASE_NAME` matching the intentionally selected production DB.
  This confirmation cannot prove a DB is production; the operator must select it.
- `AUTH_PIN_HASH` is a valid bcrypt hash; `FRONTEND_ORIGINS` lists allowed origins.
  `MEDIA_DIR`/`BACKUP_DIR` are absolute production paths.
- `GROQ_API_KEY` or `OPENAI_API_KEY` is required by existing client construction.
  Cloud validation uses a dummy with a loopback dead-end provider URL and all
  AI schedule/delivery flags disabled. Health never calls a provider.
- Explicit booleans: `SCHEDULER_ENABLED`, `REMINDERS_CHECK_ENABLED`,
  `DAILY_BRIEFING_ENABLED`, `WEEKLY_REVIEW_ENABLED`, `EXTERNAL_DELIVERY_ENABLED`,
  `BACKUP_ENABLED`, `RUN_ALEMBIC_UPGRADE_AT_STARTUP`. Last must be **false** in
  production: apply migrations deliberately before starting. Backups enabled
  require the hourly scheduler enabled; reminders alone do not schedule backups.
- Optional `APP_VERSION` (SemVer), `APP_COMMIT` (7–40 hex digits). Invalid/unset
  metadata is JSON null (unknown). Launcher resolves absent commit via git once
  before starting Uvicorn; direct Uvicorn launch must supply metadata explicitly.
  Health does not run git. Restart after updates; compare the health commit to git.
- Optional `PG_DUMP_PATH`, backup time/retention, cookie policy and module settings
  use existing [backend template](../backend/.env.template). Private Moodle feed
  stays only here; no calendar changes are part of this branch.
- Optional `MONITORING_LOG_PATH`: absolute protected writable local file; create
  its directory first. Reuses MRK-26 rotation (2 MiB × current + 3 archives) and
  allowlisted safe scheduler observations. No root logger/duplicate framework.

Protect config, repository, venv, Node installation, media and logs with Windows
ACLs. The task helper runs as SYSTEM; writable scripts/config by untrusted users
would allow privilege escalation. SYSTEM needs local read/execute/write access.
It does not inherit your user PATH, user profile, mapped drives, network login or
interactive credentials. Use machine-wide Node/Python and local disk paths;
remote/off-machine copy credentials and scheduling remain MRK-25 acceptance.

Frontend: copy [frontend/.env.production.template](../frontend/.env.production.template)
to `frontend/.env.production.local`, with the intended **public browser API URL**.
Never put backend secrets there. `NEXT_PUBLIC_API_URL` is baked into the build:
change it only with a rebuild. Production helper refuses `.env`/`.env.local`
because Next gives `.env.local` precedence over production configuration. Keep
those development files in a separate checkout. The helper clears inherited
`NEXT_PUBLIC_API_URL` before build/start so the production file controls that value. Optional env settings not in the
production file can still come from the inherited process environment; review it
before deployment. The backend never auto-loads dev dotenv files in production.

## Development vs production

Development (working directories matter):

```sh
cd backend
python -m uvicorn main:app --reload --no-proxy-headers
# separate terminal
cd frontend
npm run dev
```

Production backend, after explicit env loading/validation:

```sh
cd backend
python -m production --env-file /absolute/protected/production.env --check
python -m production --env-file /absolute/protected/production.env
```

The launcher sets backend cwd and starts exactly:
`python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --no-proxy-headers`.
On Windows it waits for the foreground child and propagates its exit code; on
POSIX it replaces the launcher process. There is **no --reload**. Direct launch with that Uvicorn command is also supported
with production env already loaded, `APP_ENV=production` and all required keys;
its database guard validates config and prevents development dotenv fallback.
Port binding is not access control; firewall/network/HTTPS setup is outside MRK-23.

Explicit migration command (from backend, with protected env loaded into that
process, never copy DATABASE_URL to shell history):

```sh
python -m alembic upgrade head
```

To load the same protected file without setting secrets manually, from backend:

```sh
python -c "import sys; from production import load_production_environment; load_production_environment(sys.argv[1]); from alembic.config import Config; from alembic import command; command.upgrade(Config('alembic.ini'), 'head')" /absolute/protected/production.env
```

This is an explicit operator command, never a health check or automatic restart.

Production frontend (cwd frontend):

```sh
npm ci
npm run build
npm run start -- --hostname 0.0.0.0 --port 3000
```

No Next standalone output or container required. Builds are deployment actions;
normal service restart runs the existing build. Verify `/login` returns a page
and the browser can reach its configured backend (a served page alone is not proof).

## Windows launch and autostart

PowerShell, replace placeholders with locally chosen paths (no real secrets here):

```powershell
& .\scripts\windows\start-backend.ps1 -ProjectDirectory '<installation>' -EnvFile '<protected-production-env>'
& .\scripts\windows\start-frontend.ps1 -ProjectDirectory '<installation>' -Build
& .\scripts\windows\start-frontend.ps1 -ProjectDirectory '<installation>'
& .\scripts\windows\check-health.ps1 -RequireHealthy
```

Private HTTPS for browsers/PWA/Web Push is Tailscale Serve in front of these ports (tailnet only, never Funnel):
`scripts/windows/tailscale-serve.ps1`, cutover/rollback and `-BindAddress 127.0.0.1` in
[https-pwa-push.md](https-pwa-push.md). The PIN login rate limit reads `X-Forwarded-For` only from
`AUTH_TRUSTED_PROXIES` (MRK-73; default: no proxy is trusted, the key is the TCP peer). Every Uvicorn start passes
`--no-proxy-headers` (`production.py` does it itself): without it Uvicorn rewrites the client address from
`X-Forwarded-For` for loopback peers before the app sees it.

The backend helper defaults to `<installation>\.venv\Scripts\python.exe`; an
explicit `-PythonPath` supports other installations. Scripts preserve child exit
codes, handle spaces, fail with fixed messages and never echo secret config.
Do not bypass execution policy machine-wide; if local policy disallows scripts,
use your normal approved signing/policy process for manual runs. The registered
tasks pass a process-scoped `-ExecutionPolicy Bypass` for their own start script
only (a machine `AllSigned` policy would otherwise refuse the unsigned scripts at
boot under SYSTEM); machine policy stays unchanged, so the installation folder
must be writable only by Administrators/SYSTEM.

After manual smoke tests, in an elevated local PowerShell:

```powershell
& .\scripts\windows\register-tasks.ps1 -ProjectDirectory '<installation>' -BackendEnvFile '<protected-production-env>'
```

Idempotently registers/replaces **only** `StandaHub-Backend` and
`StandaHub-Frontend`. SYSTEM service-account principal requires no stored user
password. Startup trigger has 30s delay, `StartWhenAvailable`, no execution limit,
ignore duplicate instance, task-level retry every minute up to 999 times. That retry
only covers a task that fails to **launch**; Windows treats an action that exits
nonzero as a completed run and does not restart it (verified on Windows). Crash
recovery therefore lives in the start scripts: each runs its child in a loop and
restarts it after a nonzero exit (10s, doubling to 60s; reset after 2 minutes up).
Exit 0 or 130 (clean shutdown / Ctrl+C) ends the script; `Stop-ScheduledTask`
ends the whole process tree (verified: no orphan Uvicorn/Node, ports released).
This helper does not start tasks, migrate, build or provision PostgreSQL. Configure
PostgreSQL's own service/autostart locally. Port-in-use startup fails; never launch
a dev backend alongside the production scheduler. Restart timing and behavior
when a child is killed must be verified on Windows, not assumed from cloud tests.

**Antivirus "gaming/performance" modes can disable the tasks.** On the acceptance
machine, AVG (Avast engine) Gaming mode disabled both tasks within seconds whenever
a game was running (Task Scheduler Operational log: Event ID 142 "System disabled
task \StandaHub-Backend", in the same batch as other background tasks, plus a
`\AVAST Software\Gaming mode Task Scheduler recovery` task that re-enables them at
boot). A disabled task keeps the running instance alive but **gets no restart on
failure**. Exclude the two tasks from that mode (or turn off its pausing of
scheduled/background tasks); do not weaken antivirus protection. Verify with the
Operational log enabled and the game running, then re-check `Settings.Enabled`.

```powershell
Start-ScheduledTask -TaskName StandaHub-Backend
Start-ScheduledTask -TaskName StandaHub-Frontend
Stop-ScheduledTask -TaskName StandaHub-Frontend
Stop-ScheduledTask -TaskName StandaHub-Backend
```

For manual processes Ctrl+C provides clean Uvicorn shutdown. Task Scheduler stop
may force termination; check for surviving children/occupied ports before restart.
An intentional task stop does not request an automatic restart. The existing
scheduler shutdown does not wait for in-flight jobs; avoid stopping during backup.

## Health contract and policy

Public unauthenticated `GET /health`, `Cache-Control: no-store`:

```json
{
  "status": "healthy|degraded|unhealthy",
  "checked_at": "UTC timestamp",
  "version": {"version": null, "commit": null},
  "database": {"status": "reachable|unreachable"},
  "migrations": {"status": "current|mismatch|unknown", "current": [], "head": []},
  "scheduler": {"status": "running|disabled|stopped|degraded", "backup_job_enabled": true, "jobs": []},
  "backup": {"status": "fresh|stale|unknown|disabled", "state": "ok|warning|unknown|disabled",
    "last_attempt_status": null, "last_attempt_at": null, "last_success_at": null,
    "age_seconds": null, "max_age_seconds": 93600}
}
```

Job rows contain fixed ID, enabled/running booleans, last_started_at,
last_finished_at, last_success_at, last_failure_at, last_result, duration_seconds,
consecutive_failures and MRK-26 status. All observations are process-local:
restart resets timestamps/streaks; unknown never asserts a prior success. A run
that completes without error resets its streak. Three consecutive failed runs
warn/degrade; stopped expected scheduler degrades immediately. Caught substep
failures count once per overall run, do not stop other jobs, and retain the existing
MRK-19 domain-event cleanup. These are execution observations; persisted business
states (e.g. scheduled AI generation internally storing a failure) are separate.

DB/schema failure or revision mismatch is **unhealthy / HTTP 503**. Health uses
an independent no-pool read-only PostgreSQL probe (3s connect, per-statement and
lock timeout); several bounded queries mean total request time can exceed 3s.
Resolve code heads once from deployed Alembic scripts; no hard-coded revision,
migration execution, writes, filesystem scan or background provider call. Unknown
DB revision text is redacted. Backup observation failure is unhealthy because
schema/read access cannot be trusted.

Scheduler warning/stopped, enabled backup with unknown/stale observation, latest
failed backup attempt or missing hourly backup owner is **degraded / HTTP 200**.
A monitor must inspect JSON, not just HTTP 200. Disabled optional services do not
by themselves degrade. Unknown version is explicit but does not fail availability.

Backup age uses latest successful **completed** `BackupLog.finished_at`, from the
existing validated DB+media pipeline. No rehash/reverification or new scanner in
health. Exactly **26h is fresh; greater is stale**. Missing/future finish is unknown;
a newer unfinished success-labelled row cannot conceal an older stale backup.
A recent failure warns even with a fresh prior backup (freshness remains separate).
Off-machine copies (MRK-57, restic → B2) report in `/health.offsite`. Once
`OFFSITE_BACKUP_ENABLED=true`, the overall status is degraded if there was no successful
off-site copy in more than 26h, the last repository check failed, or the configuration
is unusable. Before configuration the section says `disabled` and never degrades.
Setup, policy and restore: [offsite backups](offsite-backups.md).

No database URL, username/password, filename/path, env values, raw exception,
stack trace, API key, feed URL or user records in health. PostgreSQL backup URLs
are decoded by SQLAlchemy make_url; supported schemes are postgresql,
postgresql+psycopg2 and the legacy postgres alias. Supported query options:
sslmode, sslcert, sslkey, sslrootcert, application_name, connect_timeout, options.
Unsupported/repeated options fail safely rather than silently changing connection
semantics. pg_dump password goes only through PGPASSWORD; driver stderr and raw
errors are discarded for fixed categories in metadata/logs.

## Logs, update, rollback and recovery

Safe monitoring rotation is opt-in and isolated. It drops arbitrary messages,
args, exceptions, paths and unknown fields; scheduler only supplies enum/numeric
observations. Existing general app/Uvicorn logs are **not globally sanitized**;
do not collect arbitrary stdout/stderr as trusted secret-free monitoring. This
branch sanitizes caught scheduler/backup errors; broader legacy logging audit is
separate. Task Scheduler history provides process exit/restart visibility; inspect
locally with protected access. Do not paste complete logs into issues.

Update: take/verify a local backup plus MRK-25 off-machine copy, stop both tasks,
fetch the approved main commit, record previous commit/migration, install pinned
dependencies (`npm ci`), explicitly migrate, rebuild frontend with production env,
start backend then frontend, verify health commit/schema and browser API access.
No automatic pull/rebuild on restart. Never deploy directly over a running process.

Rollback: stop tasks, return to the recorded prior commit, reinstall dependencies
and rebuild, then start/verify only if that version supports the current schema.
Do not blindly downgrade business data. Use reviewed migration downgrade or a
verified backup restore into a separate scratch DB first; see [backups](backups.md).
Health mismatch is a stop signal. Avoid parallel backend instances during recovery.

### One-command update (MRK-92)

`scripts/windows/update.ps1` runs the update and rollback above as one operator command. It is started by a person
(elevated PowerShell) or, opt-in, by the automatic deploy below; nothing else pulls or rebuilds on its own.

```powershell
powershell -ExecutionPolicy Bypass -File C:\StandaHub\scripts\windows\update.ps1
```

**First run (bootstrap).** A production checkout older than this script (e.g. `f3da60e`) does not contain
`update.ps1` yet. Run the reviewed copy from `origin/main` once, without touching the tracked tree: it is written to the
elevated user's own `%TEMP%` (not readable or writable by other users) and pointed at the installation. The script is
ASCII-only, so this copy is byte-exact; later runs use the in-repo path above.

```powershell
git -C C:\StandaHub fetch origin
git -C C:\StandaHub show origin/main:scripts/windows/update.ps1 | Set-Content -Encoding ASCII "$env:TEMP\standahub-update.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\standahub-update.ps1" -ProjectDirectory C:\StandaHub
Remove-Item "$env:TEMP\standahub-update.ps1"
```

1. **Preconditions, nothing changed yet:** elevated shell, no locally modified tracked files, the running commit is
   contained in the target (`git merge-base --is-ancestor`, so a local commit is never silently dropped), `/health`
   reports a **fresh** backup (`-AllowStaleBackup` only when you hold another backup), no scheduler job running (the
   hourly job runs relative to backend start, so the script waits for it). Already at `origin/main` →
   "Already up to date", exit 0, Hub untouched.
2. **Update:** write the MRK-90 maintenance marker → stop both tasks → `git checkout --detach <target>` →
   `pip install -r backend/requirements.txt` → `npm ci` → frontend build → `production --check` → migration →
   start backend (waits for `/health` with migrations `current`) → start frontend (`/login`) → remove the marker.
   The marker (`C:\ProgramData\StandaHub\heartbeat\maintenance-until.txt`, protected folder) makes the heartbeat
   report "up" during the planned outage. It holds an expiry 45 minutes ahead and the heartbeat ignores anything
   further than 2 hours away, so an interrupted update (crash, power loss) cannot silence monitoring for longer; no
   scheduled task is ever disabled. The script waits for a heartbeat run already in progress before stopping the Hub.
   Everything that can fail runs **before** the migration; `alembic/env.py` runs all pending migrations in one
   transaction, so a failed migration leaves the schema as it was.
3. **Failure:** the script reads the live schema revision.
   - unchanged → automatic rollback to the previous commit (reinstall, rebuild, start), **exit 1**, nothing lost;
   - changed (migration succeeded, a later step failed) → no code rollback and no data downgrade; it starts what it
     can (backend first: reminders and backups keep running) and exits **3**: stop and get help.

Exit codes: `0` updated / already up to date, `1` failed and rolled back, `2` preconditions not met (nothing
changed), `3` failed after the migration. Output is the script's own fixed messages plus pip/npm/git/Next output;
the env file is read only inside Python. Gitignored local files (`frontend/public/game-assets`, `.env*`) are left
alone. Automatic runs of this script after a merge are opt-in, see the next section.

### Automatic deploy after merge (MRK-98, opt-in)

`scripts/windows/auto-update.ps1` runs `update.ps1` by itself when `origin/main` moved. All decisions stay in
`update.ps1`: fresh-backup precondition, maintenance marker, build before migration, health check and rollback. What
this script adds:

- the task `StandaHub-AutoUpdate` runs every 10 minutes as **your Windows account** with highest privileges, so `git
  fetch` uses your GitHub login. Windows stores the password for the task; the script never prints or saves it.
  A changed Windows password means re-running `-Mode Register`;
- it deploys exactly the commit it looked at (`update.ps1 -Ref <sha>`); only reviewed, CI-green merges reach `main`;
- a commit whose update failed (exit 1 = rolled back, exit 3 = failed after the migration) is **never retried
  automatically**. The next automatic attempt is a newer commit, or run `update.ps1` by hand after the fix;
- exit 2 (nothing changed: backup not fresh yet, local edits, Hub unreachable) is retried on the next run;
- one run at a time (lock file), one log per attempt in `C:\ProgramData\StandaHub\auto-update\logs` (last 30);
- optional alert: a second healthchecks.io check "Hub deploy" (period 10 min, grace 30 min). Every finished run pings
  it, or `/fail` while a failed commit is pending or deploys have not started for 6 hours. Missing pings (task
  disabled, password changed, git cannot fetch) alert too.

Setup (elevated PowerShell on the Hub host; AVG exclusions for `C:\StandaHub\scripts\windows\*` and
`C:\ProgramData\StandaHub\*` from MRK-90 already cover these paths):

```powershell
$s = 'C:\StandaHub\scripts\windows\auto-update.ps1'
powershell -ExecutionPolicy Bypass -File $s -Mode Prepare
# optional: paste the "Hub deploy" ping URL, save, close (never into chat/Linear/git)
notepad C:\ProgramData\StandaHub\auto-update\deploy-ping-url.txt
powershell -ExecutionPolicy Bypass -File $s -Mode Register     # Windows password (not the PIN); first auto run in 15 min
powershell -ExecutionPolicy Bypass -File $s -Mode Run          # first run by hand: "nothing to do" or a deploy
powershell -ExecutionPolicy Bypass -File $s -Mode Check        # ready: True, last_result
```

Day to day: `-Mode Pause` / `-Mode Resume` (e.g. before an exam week; manual `update.ps1` still works),
`-Mode Check` shows `failed_commit_pending` and `last_result`. After a failed deploy: read the newest log, fix it
in a new PR. The merge deploys itself; if the fix must go out at once, run `update.ps1` by hand.

### Review gate (MRK-97)

Roles: Claude writes the code and opens the PR, Codex reviews it (started by Standa), **Standa merges by hand**.
Branch protection makes the merge possible only when **all CI jobs and the status "Review gate (Codex verdict)"
are green**.

The gate (`.github/workflows/review-gate.yml`) is green only when the newest review **on the PR's current head
commit**, posted by the repository owner's account and not dismissed, contains the line `Codex-Verdict: MERGE`.
`BLOCK` makes it red, no verdict keeps it pending, and every new push needs a new review. Each pass sets `pending`
first and any API error ends in `error` (fail closed). The gate **never merges** and never enables GitHub
auto-merge (a leftover auto-merge is switched off).

**The gate is trusted code.** It runs only the copy on `main` and never checks out or runs PR code:
- `pull_request_target` (every push / label change) runs the base branch's file;
- `schedule` every 10 minutes re-evaluates **all open PRs** - a review written, edited or dismissed is not an event
  the trusted copy sees, so the status follows it within 10 minutes;
- `workflow_dispatch` (*Actions → Review gate → Run workflow*, branch `main`, PR number) for an immediate re-check;
  a dispatch from any other ref fails.

Because `pull_request_target` checks land on the base commit, the result is a **commit status** on the PR head with
the context `Review gate (Codex verdict)` - that is the required check.

**Critical changes** get the label `manual-merge` (look at them extra carefully before merging):

| area | paths |
|---|---|
| migrace | `backend/alembic/` |
| přihlašování a bezpečnost | `backend/auth*.py`, `frontend/proxy.ts` |
| zálohy a obnova | `backend/backup_service.py`, `backend/offsite_backup.py`, `backend/offsite_restic.py`, `scripts/**/*backup*`, `*restore*`, `*offsite*` |
| CI, review a deploy | `.github/`, `scripts/`, `Dockerfile*`, `docker-compose*.yml` / `compose*.yml` |
| příliš mnoho souborů | more changed files than the API lists (`changed_files` > listed, or > 3000) - fail closed |

**Limitations:** Codex posts with the same GitHub account as the agents, so the verdict line is a rule in
`AGENTS.md` (only the reviewer writes it), not an identity check. A PR that **adds** a workflow runs it with that
PR's token; such a PR is critical (`.github/`), and the reviewer must block anything that touches the gate. The first
introduction of the gate (the MRK-97 PR itself) runs only once the workflow is on `main`.

Automatic review on the Ubuntu host, automatic fixes after `BLOCK` and an automatic merge are a follow-up issue:
they need a proper isolation boundary for the reviewer and the fixer (see that issue).

**GitHub settings (Standa, once, after the MRK-97 PR is on `main`):**

1. *Settings* → *Branches* → *Add classic branch protection rule*, pattern `main`:
   - **Require a pull request before merging**, required approvals **0** (the gate is the review requirement);
   - **Require status checks to pass before merging**, add these five checks:
     `Backend tests and pyflakes`, `PostgreSQL migration round-trip`, `Frontend lint, types, tests and build`,
     `UI checks (ui-check, module flags, changes)`, `Review gate (Codex verdict)`.
     A check is offered only after it has reported once, so add the gate after it ran on a PR;
   - leave *Require branches to be up to date* **off** (the gate is tied to the exact head commit anyway);
   - keep *Do not allow bypassing* **off**, so Standa can still merge by hand in an emergency.
2. Check: open a PR, watch "Review gate" stay pending ("Waiting for a Codex review…"), and turn green within
   10 minutes after a `MERGE` review (or at once with *Run workflow*). Then merge by hand.

## LOCAL Windows acceptance (not performed in cloud)

1. Verify isolated production DB/config/media/backup/log paths and ACLs; SYSTEM can
   read/execute the installation and write only required directories. Node/npm and
   pg_dump resolve under SYSTEM. No secret values in task arguments/history.
2. Apply migrations deliberately; launch backend manually. Confirm `/health` is
   public, safe, current migration head and running commit match the deployed code.
   Ensure one Uvicorn worker, no reload, one scheduler; no dev process on the port.
3. Build/start frontend with `.env.production.local`; `/login` serves and browser
   requests reach production backend. Confirm changing API URL requires rebuilding.
4. Register twice and inspect both fixed tasks (idempotent, startup/retry/working
   directory/settings). Start them; test scripts with a project path containing spaces.
5. Reboot PC: PostgreSQL starts, both tasks start without interactive login, Hub
   returns; inspect PostgreSQL startup races, task history and orphan processes.
6. Kill backend worker: the start script restarts it (~10s) and /health returns;
   kill frontend similarly. Do not rely on Task Scheduler retry for this (it does
   not restart an action that exited nonzero).
7. Confirm scheduler timestamps/success/failure streaks with synthetic failing work;
   three failures degrade, success recovers, restart resets observations honestly.
   Verify reminders and MRK-19 retention still operate with single ownership.
8. Verify real completed backup is fresh; >26h is stale; newest failure warns.
   Verify pg_dump with encoded credentials/TLS options using a disposable local DB,
   never paste URL/errors. Complete MRK-25 copy/restore checks independently.
9. Stop/restart and update/rollback smoke; inspect safe rotating monitoring files
   using dummy canaries, Task Scheduler nonzero exit results and clean shutdown.
10. Network/firewall/Tailscale/HTTPS/phone acceptance is a later issue, not done here.

## Cloud verification for this branch

- Full backend CI-equivalent suite: **1011 passed, 8 skipped, 412 subtests**;
  existing datetime/TestClient deprecation warnings remain.
- Frontend: **350 tests passed**, typecheck/build passed; lint has zero errors and
  three existing unused-variable warnings in Calendar (outside MRK-23 scope).
- Pyflakes and git diff sanity passed. Four PowerShell scripts parsed without
  syntax errors using tree-sitter-powershell; this is not Windows execution.
- Disposable PostgreSQL 16: dynamic head `0020_calendar_source_presence` matched,
  synthetic completed backup produced healthy; simulated revision mismatch and
  loopback failed connection produced safe unhealthy state. No user DB accessed.
- Native cloud Uvicorn production launch: one worker, no reload, explicit config,
  public healthy response, observed scheduler run, commit metadata and clean SIGINT
  shutdown. Next production build/start served `/login` (HTTP 200).
- Security tests use dummy canaries: health/API/log/backup metadata exclude URL,
  password, path and raw error text. Identical scheduler policies/retention remain.
- Independent review identified Windows launcher supervision and inherited frontend
  API environment issues; both fixed and re-reviewed. Windows process path has unit
  coverage; Next production env precedence was checked with its real env loader.
- No migration added, no scheduler persistence, no real secrets or provider calls.
  **Groq request count: 0.** Real Windows reboot/restart/ACL acceptance is still pending.
