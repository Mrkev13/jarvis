"""Read-only health checks. Never return URLs, paths, payloads or exception text."""
from datetime import datetime, timezone
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from env_config import env_bool, env_int
from models import BackupLog


def migration_config():
    root = Path(__file__).resolve().parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("version_locations", str(root / "alembic" / "versions"))
    return config


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value):
    return _utc(value).isoformat() if value else None


def collect_health(engine, scheduler, *, backup_enabled=False, now=None, max_backup_age_hours=36):
    now = now or datetime.now(timezone.utc)
    result = {
        "status": "healthy", "checked_at": now.isoformat(),
        "database": {"status": "unreachable"},
        "migrations": {"status": "unknown", "current": [], "head": []},
        "scheduler": scheduler,
        "backup": {"status": "disabled" if not backup_enabled else "unknown", "last_attempt_status": None, "last_attempt_at": None, "last_success_at": None, "age_seconds": None, "max_age_seconds": max_backup_age_hours * 3600},
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            result["database"]["status"] = "reachable"
            current = sorted(MigrationContext.configure(conn).get_current_heads())
            head = sorted(ScriptDirectory.from_config(migration_config()).get_heads())
            result["migrations"] = {"status": "current" if current == head else "behind", "current": current, "head": head}
            if current != head:
                result["status"] = "unhealthy"
            if backup_enabled:
                columns = (BackupLog.status, BackupLog.started_at, BackupLog.finished_at)
                latest = conn.execute(select(*columns).order_by(BackupLog.started_at.desc(), BackupLog.id.desc()).limit(1)).first()
                success = conn.execute(select(*columns).where(BackupLog.status == "success").order_by(BackupLog.started_at.desc(), BackupLog.id.desc()).limit(1)).first()
                backup = result["backup"]
                backup["last_attempt_status"] = latest.status if latest and latest.status in ("running", "success", "failed") else None
                backup["last_attempt_at"] = _timestamp(latest.started_at) if latest else None
                completed = (success.finished_at or success.started_at) if success else None
                backup["last_success_at"] = _timestamp(completed)
                age = max(0, int((now - _utc(completed)).total_seconds())) if completed else None
                backup["age_seconds"] = age
                backup["status"] = (
                    "failed" if latest and latest.status == "failed" else
                    "missing" if not success else
                    "stale" if age > backup["max_age_seconds"] else "current"
                )
                if latest and latest.status == "running" and (now - _utc(latest.started_at)).total_seconds() > 3600:
                    backup["status"] = "stalled"
    except Exception:
        # A DB/schema read failed. Do not leak SQL, driver errors or credentials.
        result["status"] = "unhealthy"
    if result["status"] != "unhealthy" and (
        scheduler["status"] not in ("running", "disabled") or
        (backup_enabled and result["backup"]["status"] != "current") or
        (backup_enabled and not scheduler.get("backup_job_enabled", True))
    ):
        result["status"] = "degraded"
    return result


def runtime_health():
    from database import engine
    from scheduler_service import scheduler_snapshot
    # Separate pool and bounded PostgreSQL connect/query timeouts: don't wait on
    # an exhausted application pool. No writes or job execution in this endpoint.
    args = {"connect_timeout": 3, "options": "-c statement_timeout=3000"} if engine.dialect.name == "postgresql" else {"timeout": 3} if engine.dialect.name == "sqlite" else {}
    probe = create_engine(engine.url, poolclass=NullPool, connect_args=args)
    try:
        return collect_health(probe, scheduler_snapshot(), backup_enabled=env_bool("BACKUP_ENABLED", False), max_backup_age_hours=env_int("HEALTH_BACKUP_MAX_AGE_HOURS", 36, minimum=1))
    finally:
        probe.dispose()
