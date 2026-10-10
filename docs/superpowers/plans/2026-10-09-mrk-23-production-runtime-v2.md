# MRK-23 Production Runtime v2 Implementation Plan

Goal: native Windows production launches with safe, truthful operational health; cloud-only proof.
Architecture: read-only health router, process-local job observations, existing MRK-26 policy and MRK-25 completed backup records. No schema change or scheduler business redesign.

## Old branch audit

| Old change | Decision | Current implementation |
| --- | --- | --- |
| Public health / DB / migration probe | REWRITE | Dynamic code heads; bounded independent probe; safe HTTP 503 for DB/schema failure |
| Scheduler observations | REWRITE | Current module hourly steps and MRK-19 retention retained; failure streaks and aware timestamps |
| Backup health | REWRITE | Existing completed BackupLog metadata; canonical MRK-26 26h threshold; no filesystem scanner |
| PostgreSQL make_url parsing | KEEP | Small port with decoded credentials/query handling and fixed error categories |
| Production validation/launcher | REWRITE | Explicit production env, native Windows processes, one worker; platform-neutral Python launch |
| Operations documentation | REWRITE | Native Task Scheduler instructions and unverified Windows checklist |
| Dockerfiles/Compose | DROP | Docker Desktop not required |
| Fonts/layout/Next standalone | DROP | Superseded; current frontend build retained |
| WoT tests | DROP | Unrelated and stale |
| Frontend health endpoint | DROP | Existing /login production page probe plus authoritative backend /health is sufficient |

## Execution

- [x] Add failing health/backup/scheduler/production tests; prove missing behavior.
- [x] Implement health_service/router and scheduler_health. Decorate existing jobs and mark caught errors without changing job order, transactions or scheduling.
- [x] Port safe PostgreSQL parsing and failure categories; keep MRK-25 media/metadata behavior.
- [x] Add platform-neutral production launcher, env template, PowerShell start/check/register helpers and operations docs.
- [x] Run focused and full backend checks; verify disposable PostgreSQL matching/mismatched/unavailable cases; production start/shutdown and frontend build/start smoke.
- [ ] Review safe output, current migration head and diff; commit/push fresh branch and open PR if GitHub API permits. Leave MRK-23 In Review (not Done).

Review focus: secrets in driver errors; environment fallback to dev DB; scheduler swallowed failures; startup/restart observation reset; Task Scheduler foreground child exit propagation and paths with spaces.
