"""Pure monitoring policy. Adapters supply observations; missing data stays unknown.

No scheduling, database writes, notifications, subprocesses or provider calls.
"""
import math
import re
from collections.abc import Mapping

BACKUP_MAX_AGE_SECONDS = 26 * 3600
JOB_FAILURE_THRESHOLD = 3
_GIB = 1024 ** 3


def backup_state(age_seconds: float | None, *, last_attempt_failed: bool = False) -> str:
    if last_attempt_failed:
        return 'warning'
    if age_seconds is None or not math.isfinite(age_seconds) or age_seconds < 0:
        return 'unknown'
    return 'warning' if age_seconds > BACKUP_MAX_AGE_SECONDS else 'ok'


def job_state(consecutive_failures: int | None) -> str:
    if consecutive_failures is None or consecutive_failures < 0:
        return 'unknown'
    return 'warning' if consecutive_failures >= JOB_FAILURE_THRESHOLD else 'ok'


def disk_state(total_bytes: int, free_bytes: int) -> str:
    if total_bytes <= 0 or free_bytes < 0 or free_bytes > total_bytes:
        return 'unknown'
    fraction = free_bytes / total_bytes
    if free_bytes < 512 * 1024 ** 2 or fraction < 0.03:
        return 'critical'
    if free_bytes < 2 * _GIB or fraction < 0.10:
        return 'warning'
    return 'ok'


def daily_budget_state(exhausted: bool | None) -> str:
    # Caller must observe TPD/RPD, not confuse transient TPM/RPM with daily exhaustion.
    if exhausted is None:
        return 'unknown'
    return 'warning' if exhausted else 'ok'


def version_metadata(env: Mapping[str, str]) -> dict[str, str | None]:
    """Explicit build metadata only; never shell out or publish arbitrary environment values."""
    version = env.get('APP_VERSION', '')
    commit = env.get('APP_COMMIT', '')
    return {
        'version': version if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?(?:\+[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?', version) else None,
        'commit': commit if re.fullmatch(r'[a-fA-F0-9]{7,40}', commit) else None,
    }
