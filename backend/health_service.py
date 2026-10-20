"""Bounded read-only operational health; public output contains no errors or paths."""
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from env_config import env_bool
from models import BackupLog
from monitoring_service import BACKUP_MAX_AGE_SECONDS, backup_state, version_metadata


@lru_cache(maxsize=1)
def code_revisions():
    """Resolve deployed code once; no git subprocess and no hard-coded migration head."""
    root = Path(__file__).resolve().parent
    config = Config()
    config.set_main_option('script_location', str(root / 'alembic'))
    scripts = ScriptDirectory.from_config(config)
    return sorted(scripts.get_heads()), frozenset(r.revision for r in scripts.walk_revisions())


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value):
    return _utc(value).isoformat() if value else None


def collect_health(engine, scheduler, *, backup_enabled=False, now=None, version=None, offsite=False):
    now = _utc(now or datetime.now(timezone.utc))
    result = {
        'status': 'healthy', 'checked_at': now.isoformat(),
        'version': version or {'version': None, 'commit': None},
        'database': {'status': 'unreachable'},
        'migrations': {'status': 'unknown', 'current': [], 'head': []},
        'scheduler': scheduler,
        'backup': {'status': 'unknown' if backup_enabled else 'disabled', 'state': 'unknown' if backup_enabled else 'disabled',
                   'last_attempt_status': None, 'last_attempt_at': None, 'last_success_at': None,
                   'age_seconds': None, 'max_age_seconds': BACKUP_MAX_AGE_SECONDS},
    }
    try:
        with engine.connect() as conn:
            # A separate NullPool probe is bounded independently of application pool pressure.
            if conn.dialect.name == 'postgresql':
                conn.execute(text('SET TRANSACTION READ ONLY'))
            conn.execute(text('SELECT 1'))
            result['database']['status'] = 'reachable'
            heads, known = code_revisions()
            current = sorted(MigrationContext.configure(conn).get_current_heads())
            result['migrations'] = {'status': 'current' if current == heads else 'mismatch',
                                    'current': [r if r in known else 'unknown' for r in current], 'head': heads}
            if current != heads:
                result['status'] = 'unhealthy'
            if backup_enabled:
                cols = (BackupLog.status, BackupLog.started_at, BackupLog.finished_at)
                latest = conn.execute(select(*cols).order_by(BackupLog.started_at.desc(), BackupLog.id.desc()).limit(1)).first()
                success = conn.execute(select(*cols).where(BackupLog.status == 'success', BackupLog.finished_at.is_not(None))
                                       .order_by(BackupLog.finished_at.desc(), BackupLog.id.desc()).limit(1)).first()
                backup = result['backup']
                backup['last_attempt_status'] = latest.status if latest and latest.status in {'running', 'success', 'failed'} else None
                backup['last_attempt_at'] = _timestamp(latest.started_at) if latest else None
                completed = success.finished_at if success else None
                age = (now - _utc(completed)).total_seconds() if completed else None
                # Future completion cannot masquerade as a fresh verified backup.
                backup['age_seconds'] = round(age) if age is not None and age >= 0 else None
                backup['last_success_at'] = _timestamp(completed)
                freshness = backup_state(age)
                backup['status'] = {'ok': 'fresh', 'warning': 'stale', 'unknown': 'unknown'}[freshness]
                backup['state'] = backup_state(age, last_attempt_failed=backup['last_attempt_status'] == 'failed')
    except Exception:
        # Never expose SQL, database URLs, driver/OS exception text or private filenames.
        result['status'] = 'unhealthy'
    if offsite:
        from offsite_restic import enabled as offsite_enabled, health_section
        try:
            with engine.connect() as conn:
                result['offsite'] = health_section(conn, now)
        except Exception:
            # Secret-safe fallback; an unknown off-site state only degrades health when off-site is configured.
            result['offsite'] = {'configured': offsite_enabled(), 'status': 'unknown', 'degraded': offsite_enabled()}
    if result['status'] != 'unhealthy' and (
        scheduler['status'] not in {'running', 'disabled'} or
        (backup_enabled and (result['backup']['state'] != 'ok' or not scheduler.get('backup_job_enabled', False))) or
        result.get('offsite', {}).get('degraded')   # MRK-57: no off-site copy for >26 h once configured
    ):
        result['status'] = 'degraded'
    return result


@lru_cache(maxsize=1)
def runtime_version():
    # Validate build-supplied metadata using MRK-26's allowlist, then freeze for this process.
    return version_metadata(os.environ)


@lru_cache(maxsize=1)
def probe_engine():
    from database import engine
    if engine.dialect.name == 'postgresql':
        # Preserve URL options (e.g. sslmode); impose bounded connect/query/lock waits.
        url = engine.url.update_query_dict({'connect_timeout': '3'})
        options = str(url.query.get('options', '')) + ' -c statement_timeout=3000 -c lock_timeout=3000'
        url = url.update_query_dict({'options': options})
        return create_engine(url, poolclass=NullPool)
    if engine.dialect.name == 'sqlite':
        return create_engine(engine.url, poolclass=NullPool, connect_args={'timeout': 3})
    raise ValueError('Unsupported health database')


def runtime_health():
    from scheduler_service import scheduler_snapshot
    try:
        return collect_health(probe_engine(), scheduler_snapshot(), backup_enabled=env_bool('BACKUP_ENABLED', False),
                              version=runtime_version(), offsite=True)
    except Exception:
        # Engine/config failures must still be a bounded, secret-safe 503 response.
        return {'status': 'unhealthy', 'version': runtime_version(), 'database': {'status': 'unreachable'},
                'migrations': {'status': 'unknown'}, 'scheduler': scheduler_snapshot(), 'backup': {'status': 'unknown'}}
