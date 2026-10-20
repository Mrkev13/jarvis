# Monitoring foundation (MRK-26)

Audit baseline: origin/main `cf783a0`; MRK-23 inspected read-only at
`78fe88f`. No MRK-23 merge or dependency import. No MRK-25 branch was
available. This branch provides policy and logging helpers, **not live alerts**.
No new endpoint, scheduler task, push registration or System panel is installed.

## Signal inventory

| Signal | Current source | Available? / missing data | Proposed threshold | Delivery |
| --- | --- | --- | --- | --- |
| External uptime | MRK-23 `/health` (not on baseline) | Pending MRK-23 deployment | 2 consecutive failures at 60-second intervals; JSON status also checked | Independent email/push outside Hub |
| Repeated job failure | `scheduler_service.py`; MRK-23 `scheduler_health.py` run history | Baseline has no run tracker; MRK-23 has last result, no failure streak; process restart resets history | 3 consecutive failures per job; reset on success | Hub system notification + existing push queue after integration |
| Backup | `BackupLog`, `backup_service.py` | Last attempt/status and last successful finish available; raw errors/filenames private | Last success older than 26h or latest attempt failed | Hub notification + push |
| Off-machine copy | MRK-25/MRK-57 | `/health.offsite` (restic → B2): last attempt/outcome, last success, age, check/prune status | Failed attempt immediately; daily successful copy older than 26h | Hub notification + push |
| Groq daily exhaustion | `ai.DailyLimitError`, `llm_usage.py`, `structured_llm.py` | TPD/RPD classified per call; no shared durable exhausted/reset state. `llm_budget.py` estimates request size, not daily spending | Observed TPD/RPD; TPM/RPM are transient, not daily exhaustion | One Hub notification per exhaustion incident + push |
| Disk space | No current check | OS sample needed for DB, media, backup volumes; sample errors mean unknown | Warning: free <2 GiB OR <10%; critical: <512 MiB OR <3% | Hub notification + push |
| Running version | No current metadata exposure | Helper accepts explicit `APP_VERSION` and `APP_COMMIT`; injection not configured | Informational, unset/invalid means unknown | Authenticated System panel |
| Logs | Stream handlers, raw prints; no rotation | Isolated rotating monitoring helper available; existing logs still need call-site hardening | 2 MiB/file, 3 rotated files plus current | Protected local files |

## Implemented independent foundations

`backend/monitoring_service.py` contains deterministic threshold functions. Backup
age must come from the latest **successful** finish (fallback start if legacy data
requires it), never a failed attempt. Exactly 26h is current; greater is stale.
Invalid/future age is unknown. Explicit failure warns even with a recent success.
`None` is unknown, never evidence of health. Job streaks must be supplied by a
future tracker; do not infer repeated failure from one MRK-23 last-result field.
Daily budget input requires an explicit observation; no polling or Groq calls.

`version_metadata(mapping)` reads only supplied APP_VERSION (an ASCII three-part release label with optional prerelease/build suffix)
and APP_COMMIT (7–40 hexadecimal characters). It does not run git or expose paths
or arbitrary environment values. Runtime/build integration remains deferred.

`backend/monitoring_logging.py` supplies an explicit opt-in logger. Example from
an application adapter (no startup hook added here):

```python
from monitoring_logging import configure_monitoring_logger
logger = configure_monitoring_logger("/protected/logs/monitoring.log")
logger.info("", extra={"monitoring": {
    "signal": "backup", "state": "warning", "age_seconds": 95000,
}})
```

Use an existing writable directory with restricted permissions (Windows ACLs or
Linux owner-only directory); path is deployment configuration, never published.
Repeated configuration with identical rotation settings keeps one handler.
This logger is isolated and does not change root/Uvicorn/application logging.

### No-secrets rules

Only allowlisted signal/state enums and finite nonnegative numeric measurements
up to the signed 64-bit maximum are emitted. Logging failures emit only the fixed
`monitoring_log_write_failed` category to stderr, never the original record.
Arbitrary messages, arguments, exception text/tracebacks, stack
information, unknown fields, paths, URLs, user content and secrets are dropped.
Never log prompts, chat, notification bodies, personal records, auth/cookie
headers, DB URLs, VAPID keys, tokens, backup names or off-machine destinations.
Do not add string fields without an explicit allowlist and regression tests.
These guarantees apply **only to the monitoring logger**. Existing scheduler
prints, backup error/retention logging and startup exception paths can include
raw exceptions. Audit/harden those call sites before collecting application
stdout/stderr centrally; rotation does not sanitize them.

## Deferred integration and System panel contract

After MRK-23/MRK-25 stabilize, add an authenticated read-only status endpoint:

```json
{
  "version": {"version": null, "commit": null},
  "observed_at": "UTC ISO-8601 timestamp",
  "jobs": [{"id": "standa_hub_hourly", "last_run": null,
            "last_result": null, "consecutive_failures": null}],
  "backup": {"last_attempt_at": null, "last_attempt_status": null,
             "last_success_at": null, "age_seconds": null, "state": "unknown"},
  "off_machine": {"last_attempt_at": null, "last_attempt_status": null,
                  "last_success_at": null, "age_seconds": null, "state": "unknown"},
  "disk": {"free_bytes": null, "free_percent": null, "state": "unknown"},
  "groq_budget": {"exhausted": null, "observed_at": null, "reset_at": null,
                  "state": "unknown"}
}
```

This is a proposed contract, not a shipped API. Display unknown/disabled explicitly.
Allowlist job IDs; include no raw error messages, paths, DB details or personal
content. Sample each configured storage volume internally; expose only the worst
state and aggregate safe measurements or allowlisted logical volume names.
Panel: compact job rows, backup/copy timestamps and status, version/commit.
No panel now because truthful job/copy observations are unfinished.

Reuse MRK-23 tracker and health observations. Add failure counts at its existing
tracking boundary, without changing scheduling/reminder behavior. Document
restart semantics (prefer persistent incidents if alerts must survive restarts).
MRK-23 v2 uses this canonical 26h threshold directly (no 36h override).
Its process-local scheduler tracker supplies failure streaks; see [operations](operations.md).
Reuse MRK-25 copy metadata, never implement a second copy job here.

Reuse existing notification dedupe/recovery and delivery queue. Currently
`delivery_service.deliverable_types()` allows reminder/briefing/review, **not
system alerts**. Integration must explicitly enable system delivery, dedupe one
notification per signal/job/incident, avoid push on every check, resolve on
recovery, and keep monitoring failures from blocking reminder delivery. Groq
reset time must come from observed provider state; do not assume local midnight.

## External uptime recommendation and acceptance

For a single-user private deployment, start with a managed uptime monitor only
if `/health` is already reachable over HTTPS. Require both successful HTTP and
JSON `status == healthy`; MRK-23 returns HTTP 200 for degraded state. Keep the
endpoint free of private data. Never open public access solely for monitoring.
For Tailscale-only access, use an independent always-on device on the tailnet
with a simple scheduled probe and its own alert delivery. A monitor on the same
PC cannot detect PC/power outages. No hosting/Funnel/phone configuration here.

Local acceptance after dependency merges: confirm running commit; test scheduler
failure/recovery, >26h backup, copy failure/recovery, fake daily-limit observation,
and disk samples. Verify dedupe and push delivery with test subscriptions; check
unknown states and restart behavior. Kill Hub to verify independent uptime alert.
Inspect protected rotated files for secrets using dummy canaries, not real keys.

## Cloud verification

Focused regressions cover backup/failure/disk boundaries, unknown observations,
release metadata, rotation, idempotence, unsafe handler replacement, and dummy
private-content canaries during normal logging, formatter failure and I/O failure.
Run from the repository root with backend development dependencies installed:

```sh
python -m pytest backend/tests/test_monitoring.py --disable-socket --allow-unix-socket -q
python -m pyflakes backend/*.py backend/scripts/*.py
```

The complete backend suite uses the exact CI dummy environment and
`python -m pytest backend/tests --disable-socket --allow-unix-socket -x -q`.
Network sockets are prohibited; there are zero real Groq requests. No frontend
files or schema changed. Cloud tests do not prove live alert delivery, off-machine
copy, Windows disk/ACL behavior or independent uptime detection.
