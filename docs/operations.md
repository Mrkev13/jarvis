# Production operations (MRK-23)

Standa Hub is a Next.js frontend, FastAPI backend and PostgreSQL database.
Production uses **Docker Compose with three services** on Windows/Docker Desktop
and later Linux/Docker Engine. Development retains `npm run dev` and uvicorn
`--reload`. This change is independent of MRK-22.

## Choice and Windows acceptance boundary

| Option | Benefits | Costs / decision |
| --- | --- | --- |
| Docker Compose | Same builds, process supervision and persistent volumes on Windows/Linux; PostgreSQL client shipped with backend | Requires Docker engine. Chosen; no extra proxy/worker containers |
| NSSM / Windows service wrapper | Can run native Python/Node before interactive login | Windows-specific install, environment/path handling and separate Linux service setup; fallback if Docker Desktop startup cannot meet host requirements |
| Windows Task Scheduler | Built in; useful for boot/login startup | Boot trigger alone is not process supervision; adds fragile command/environment handling; not the application supervisor |

Docker's `restart: unless-stopped` restarts **exited** application processes, and
resumes containers when the Docker engine starts. An unhealthy Docker healthcheck
alone **does not restart** a hung process. Monitor health and investigate hangs.
A deliberate `compose stop` leaves services stopped until explicitly started.

**Docker Desktop normally starts on user sign-in, not unattended before login.**
Do not claim unattended reboot acceptance based on cloud tests. Local Claude must
verify the real Windows engine startup (including the intended login policy).
If reboot without login is required and Docker Desktop cannot meet it, leave
MRK-23 In Review: use a separately reviewed native service wrapper or Linux host.
Do not enable automatic Windows login merely to make this check pass.

## Configuration and data safety

Run commands from the repository root. Install Docker with Compose v2. Use a
separate production release checkout; do not place a development `backend/.env`
in it. Copy templates (PowerShell `Copy-Item` also works):

```sh
cp deploy/.env.template deploy/.env.production
cp backend/.env.production.template backend/.env.production
```

Both resulting files are ignored. Restrict access to them. Never commit secrets.
Set `RELEASE_TAG` to the checked-out Git commit (`git rev-parse --short HEAD`).
Set `POSTGRES_DB`, `POSTGRES_USER`, a new `POSTGRES_PASSWORD`, and an explicit
`PRODUCTION_DATABASE_URL`, e.g.
`postgresql+psycopg2://USER:URL_ENCODED_PASSWORD@postgres:5432/standa_hub_prod`.
The launcher requires the URL database to match `PRODUCTION_DATABASE_NAME`.
Compose sets that name from `POSTGRES_DB`. There is no development DB fallback.
Changing PostgreSQL credentials in env does **not** change an initialized volume;
rotate credentials in PostgreSQL as a separate operation.

Set `PUBLIC_API_URL` to the browser-visible backend URL **before building** the
frontend. `NEXT_PUBLIC_API_URL` is compiled into the build; changing it requires
a rebuild. Set `FRONTEND_ORIGINS` in backend config to the actual frontend origin.
Compose sets server-only `BACKEND_INTERNAL_URL=http://backend:8000`; auth checks
and frontend health use it, while browser requests use the public origin.

Generate `AUTH_PIN_HASH` privately with the project's bcrypt dependency:

```sh
cd backend
python -c "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass('Production PIN: ').encode(), bcrypt.gensalt()).decode())"
```

Run with the backend virtualenv activated if using a native Python installation.
**Single-quote the bcrypt hash** in the env file (`AUTH_PIN_HASH='$2b$...'`) so
Compose does not interpret dollar signs as variable substitutions. Never put the
real PIN in a command. `AUTH_COOKIE_NAME` must match frontend/backend. Set
`AUTH_COOKIE_SECURE=true` for HTTPS; only for loopback HTTP smoke tests use false.
Keep production config explicit: scheduler/reminder/backup enabled flags,
absolute media/backup paths (Compose fixes them to `/data/media`, `/data/backups`),
startup migration setting, backup hour/retention and health age threshold.

AI is deliberately disabled by default in the production template:
`DAILY_BRIEFING_ENABLED=false`, `WEEKLY_REVIEW_ENABLED=false`, external delivery
false, a non-secret `GROQ_API_KEY=disabled-placeholder`, and a loopback dead-port
`GROQ_BASE_URL`. The placeholder only constructs the existing client; it cannot
reach Groq. To restore scheduled AI, configure a real key and base URL privately,
review existing module settings in `backend/.env.template`, then explicitly enable
those jobs. No real AI requests are needed to deploy or validate this setup.

Ports bind **only to 127.0.0.1**. Configure Tailscale Serve/HTTPS on Windows
separately for frontend 3000 and backend 8000 (e.g. separate HTTPS ports).
The backend public URL, CORS origin, secure cookie and browser must agree.
Never expose PostgreSQL; Compose publishes no database port.

Volumes are explicitly scoped to project `standa-hub-production`:
`postgres_data`, `media`, `backups`. Keep the project name stable across releases.
Do not run `docker compose down -v` on production. No dev DB/media directory is
mounted. A fresh start creates a **new** DB; it does not import existing real data.
Before adoption, back up current DB + media, test a restore into a separate
staging instance, then migrate verified copies. Follow [backups.md](backups.md).
Do not overwrite a real database with a smoke-test dataset.

## Build, start, health, stop

From repository root, after configuring both files:

```sh
docker compose --env-file deploy/.env.production -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env.production -f deploy/compose.yaml build
docker compose --env-file deploy/.env.production -f deploy/compose.yaml up -d --wait --wait-timeout 180
docker compose --env-file deploy/.env.production -f deploy/compose.yaml ps
docker compose --env-file deploy/.env.production -f deploy/compose.yaml logs --tail 100 backend frontend
```

The backend upgrades Alembic on startup and fails startup if it cannot migrate.
PostgreSQL must be ready before it starts. The frontend waits for a backend health
HTTP 200; `degraded` is HTTP 200 so first deployment can start before its first
successful backup. `unhealthy` is HTTP 503. **`up --wait` is not proof of fully
healthy business operation**: inspect the response status and backup state.

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:3000/health
curl --fail http://127.0.0.1:3000/login
docker compose --env-file deploy/.env.production -f deploy/compose.yaml stop
```

PowerShell can use `Invoke-RestMethod` for JSON and `Invoke-WebRequest` for pages.
Stop grants the backend 60 seconds to finish active work. Inspect shutdown logs;
long-running external jobs may exceed this and be forcibly terminated. Existing
scheduler shutdown semantics remain unchanged; pending work retries on restart.
`down` removes containers/network, retains volumes. `up -d` starts them again.

### Platform-neutral application commands

For native service wrappers, keep the same single-worker start command, with a
backend virtualenv installed from `requirements.txt` and `pg_dump` >= server major:

```sh
python backend/production.py --env-file backend/.env.production --host 127.0.0.1 --port 8000
```

Explicit native `DATABASE_URL`, `PRODUCTION_DATABASE_NAME`, absolute Windows/Linux
`MEDIA_DIR`/`BACKUP_DIR`, and all production flags are mandatory. It launches
`python -m uvicorn main:app --workers 1` without `--reload`; no worker flag can be
passed through. Do not start a second backend against the same production DB.
For the frontend (Node 24, build-time public URL and server env already configured):

```sh
cd frontend
npm ci
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

`npm start` needs the full `.next` build + installed dependencies. Compose instead
ships standalone output (`node server.js`) with `public` and `.next/static` copied.
Geist fonts are bundled locally, with OFL licenses, so builds do not fetch Google
Fonts. Dev is still `npm run dev`; backend dev is `uvicorn main:app --reload`.

## Health contract

`GET /health` is unauthenticated, read-only, uncached and returns no user data,
credentials, SQL, filenames, filesystem paths, job arguments or exception text.
Backend shape:

```json
{
  "status": "healthy | degraded | unhealthy",
  "checked_at": "UTC ISO timestamp",
  "database": {"status": "reachable | unreachable"},
  "migrations": {"status": "current | behind | unknown", "current": ["revision"], "head": ["revision"]},
  "scheduler": {
    "status": "running | degraded | stopped | disabled", "running": true,
    "backup_job_enabled": true,
    "jobs": [{"id": "standa_hub_hourly", "enabled": true,
      "status": "scheduled | missing | stale | failed | disabled",
      "last_started": null, "last_run": null, "last_result": null,
      "running": false, "next_run": "UTC ISO timestamp"}]
  },
  "backup": {"status": "current | missing | stale | stalled | failed | disabled | unknown",
    "last_attempt_status": "success | failed | running | null",
    "last_attempt_at": null, "last_success_at": null, "age_seconds": null,
    "max_age_seconds": 129600}
}
```

Job observations are in-memory for the current process, reset on restart. All four
configured jobs are listed, including disabled jobs. `last_run` is completion time,
`last_result` is success/failed/running or null; it describes job execution, not an
LLM answer's correctness. Already-caught scheduler exceptions and reminder/delivery
failure counts are recorded without changing handling. Some briefing/review failures
are handled inside their services; inspect their module state/logs for details.
A job is stale after max(three intervals, five minutes) since its last start.
PostgreSQL health connection and SQL statement timeouts are three seconds each.
DB failure or Alembic mismatch is unhealthy; scheduler stopped/missing/stale/failed,
missing/stale/failed/stalled backup or backup enabled without hourly owner is
degraded. Intentionally disabled features are shown as disabled.
Backup age comes from the last successful log, while a later failed attempt is
reported even if a prior success is fresh. Running >1 hour is stalled. Default
maximum successful-backup age is 36 hours (`HEALTH_BACKUP_MAX_AGE_HOURS`).
This is log-based: it does **not** prove files still exist, external replication or
restore integrity. Those require independent checks.

Frontend `/health` returns only `status`, `frontend: "ok"` and
`backend: {reachable, status}`. Backend failure gives HTTP 503; degraded gives 200.
Its timeout is three seconds, redirects/invalid responses are failures.
The Docker frontend probe also checks `/login` to verify a production page serves.
Health does not replace an authenticated browser smoke test.

## Scheduler and backups

One uvicorn process owns APScheduler, all four scheduled jobs and daily backup.
No second worker/container/replica. `SCHEDULER_ENABLED` controls hourly
snapshots/notifications/daily backup; reminders have their own flag. Keep hourly
and backup enabled together. Briefing/review are separately opt-in; enabling them
requires private AI configuration and may incur real requests outside this task.

Run a first backup after adoption using the existing authenticated backup UI/API;
verify DB dump, media archive, checksum/manifest and a staging restore. The image
contains a compatible PostgreSQL client. Backups live on an explicit volume,
**on the same host**: arrange an encrypted off-machine copy and monitor it.
Retention defaults to 30 days; inspect available space, daily completion and logs.
A single backup does not cover writes made afterward. See [backups.md](backups.md).

## Update and rollback

1. Record old commit/release tag and current health; save the configured env files
   securely. Make and verify a DB + media backup before migration.
2. Stop services, preserving volumes. Update the release checkout to the reviewed
   commit; do not merge or deploy an unreviewed branch automatically.
3. Set a new `RELEASE_TAG`, validate config and build. Retain previous tagged
   backend/frontend images; do not prune them before the rollback window closes.
4. Start with `up -d --wait`, inspect migrations, scheduler, backup health and do
   an authenticated UI check. Confirm browser API requests use the intended URL.
5. For code rollback **only if schema remains compatible**, stop, restore previous
   checkout/config/tag, then `up -d --no-build --wait` using retained images.
6. If migrations are incompatible, stop all writers and restore the verified
   pre-update DB **and matching media** into a staging/new volume first. Validate
   before switching production. Do not blindly run Alembic downgrade or restore
   over an active database. Restoration loses newer writes; plan recovery with
   the owner. Keep the failed-state backup for analysis.

## Windows verification checklist — Local Claude required

Do these against the real Windows deployment with disposable fault checks staged
first. Do not mark MRK-23 Done until all acceptance evidence is recorded.

- [ ] Record deployed commit/tag, Docker/Compose version, real DB name, media/backup
  volume names and host login/startup policy. Confirm no dev DB is targeted.
- [ ] Back up current DB/media; verify a staging restore before moving real data.
- [ ] Set private env files; validate quoted bcrypt hash, secure cookie, HTTPS API
  URL/CORS and matching auth cookie names. Keep secrets out of logs/screenshots.
- [ ] Build/start with commands above; `/login` serves production output, PIN login
  works, browser API requests target production and existing real data/media remain.
- [ ] Inspect backend `/health`: schema current/head match; one scheduler; enabled
  jobs gain last-run/status; force a safe real backup and confirm current age/status.
- [ ] Inspect frontend `/health` and authenticated UI; confirm health contains no
  business data or private errors. Test Tailscale/HTTPS from another permitted device.
- [ ] **Reboot Windows** with the intended login policy; without dev terminals,
  Docker engine and all services return, UI loads, scheduler resumes, health settles.
  Record any required user login. If unattended-before-login is required but fails,
  keep issue In Review and decide a native wrapper/Linux host follow-up.
- [ ] **Kill the backend's uvicorn/Python process**, not `compose stop` (which
  intentionally suppresses restart). For container setup find the Python child
  using `docker compose ... top backend`, then use `docker compose ... exec backend
  python -c "import os,signal; os.kill(PID, signal.SIGKILL)"` replacing PID with its
  container PID. Record restart count/logs; backend must return within one minute,
  with exactly one scheduler and no duplicated reminders/briefings.
- [ ] In staging, stop DB and confirm backend/frontend 503 without private data;
  restore DB and confirm recovery. Verify stopped scheduler and stale backup show
  degraded (unit tests cover these; avoid altering real backup rows on production).
- [ ] Stop gracefully; inspect completion/shutdown logs and no lingering owner.
  Restart; verify persistence, media, replay links and backup files are intact.
- [ ] Run update and rollback rehearsal in staging with matching DB/media snapshot;
  configure off-machine backups and external health monitoring.

Cloud can prove application builds, production starts, health/fault behavior and
container shutdown. It cannot prove Windows reboot/autostart, actual Windows
process recovery timing, hardware uptime or your PC's Tailscale access.

## Cloud evidence (2026-10-08)

Baseline: `origin/main` at `a316584`, independent of the unmerged MRK-22 branch.
Dedicated branch: `mrk-23-production-service`. No schema migration added.

- Docker Compose config/YAML validated; both production images built. Next.js
  standalone build compiled and generated all pages without Google Fonts requests.
- Backend one-worker production start, frontend standalone start, both `/health`
  healthy and production `/login` HTTP 200 verified against PostgreSQL 16.
- Real DB + media backup succeeded, including an additional backup with a
  URL-encoded dummy password. The pre-existing pg_dump parser incorrectly passed
  encoded credentials literally; it now uses the already available SQLAlchemy URL
  parser. No backup scheduling/retention behavior changed.
- Stale backup -> degraded HTTP 200; DB stopped -> backend/frontend unhealthy
  HTTP 503 with no private error text; restored DB -> healthy.
- Actual scheduler stop -> degraded covered by regression test. Linux container
  backend process kill -> healthy in 6.3 seconds. This is not Windows acceptance.
- Compose stop logged application shutdown completion; services stopped cleanly.
- Focused health/config/backup/scheduler: **30 passed**. Full backend suite:
  **686 passed, 8 skipped, 1 failed**, plus 345 passing subtests. The unchanged
  baseline failure is
  `test_briefing.py::ChangesNoiseTestCase::test_technical_activity_is_filtered_but_user_changes_stay`:
  a seeded reminder writes an audit row using real wall-clock time, while the
  snapshot uses a fixed October 6 date; the extra row displaces the expected
  changes. It remains visible, not skipped or suppressed. MRK-22 has a test-fixture
  correction, but this branch does not depend on it being merged.
- Frontend **288 passed**; `npm run lint`, `tsc --noEmit`, backend changed-file
  `pyflakes` and `git diff --check` passed. An existing WoT test's reserved `module`
  variable was renamed to let Next.js lint pass; its assertions are unchanged.
- Independent review found no remaining important issues after the credential fix.
- **Exactly 0 real Groq requests**. Tests used fake providers, network-blocking
  pytest options and dummy client values; production smoke tests used a dead
  loopback LLM URL with scheduled AI disabled. Linear was unavailable in cloud;
  no status update or Done transition was performed.

Backend verification (virtualenv from requirements plus pytest/pytest-socket):

```sh
GROQ_API_KEY=validation-placeholder GROQ_BASE_URL=http://127.0.0.1:9 DATABASE_URL=sqlite:// python -m pytest backend/tests --disable-socket --allow-unix-socket
GROQ_API_KEY=validation-placeholder GROQ_BASE_URL=http://127.0.0.1:9 DATABASE_URL=sqlite:// python -m pytest backend/tests/test_production_health.py backend/tests/test_scheduler.py backend/tests/test_backup.py --disable-socket --allow-unix-socket
```

Frontend verification: `npm test`, `npm run lint`, `npx tsc --noEmit` from
`frontend/`; production build/start commands are above. The restricted cloud TLS
proxy required its existing trusted CA bundle as the optional BuildKit
`build_ca` secret for pip/npm installation. It was mounted only during builds;
TLS verification stayed enabled and the CA was not included in runtime images.
