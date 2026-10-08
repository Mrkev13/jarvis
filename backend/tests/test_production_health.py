"""Read-only operational health: real SQLite schema, no network or AI."""
import importlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def service():
    try:
        return importlib.import_module("health_service")
    except ModuleNotFoundError:
        pytest.fail("production health service has not been implemented")


@pytest.fixture
def database(tmp_path):
    health = service()
    engine = create_engine(f"sqlite:///{tmp_path / 'health.sqlite'}")
    config = health.migration_config()
    with patch.dict("os.environ", {"DATABASE_URL": str(engine.url)}):
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


def snapshot(engine, scheduler=None, now=None, backup_enabled=False):
    return service().collect_health(
        engine, scheduler or {"status": "running", "jobs": []},
        backup_enabled=backup_enabled, now=now,
    )


def test_healthy_current_schema(database):
    result = snapshot(database)
    assert result["status"] == "healthy"
    assert result["database"] == {"status": "reachable"}
    assert result["migrations"]["current"] == result["migrations"]["head"]


def test_schema_mismatch_unhealthy(database):
    with database.begin() as conn:
        conn.execute(text("DELETE FROM alembic_version"))
    assert snapshot(database)["status"] == "unhealthy"


def test_db_failure_has_no_private_exception(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'missing' / 'private.sqlite'}")
    result = snapshot(engine)
    assert result["status"] == "unhealthy"
    assert result["database"]["status"] == "unreachable"
    assert str(tmp_path) not in json.dumps(result)
    assert "private.sqlite" not in json.dumps(result)


def test_scheduler_stopped_is_degraded(database):
    result = snapshot(database, {"status": "stopped", "jobs": []})
    assert result["status"] == "degraded"


def test_backup_missing_stale_failed_and_fresh(database):
    from models import BackupLog
    now = datetime.now(timezone.utc)
    assert snapshot(database, now=now, backup_enabled=True)["backup"]["status"] == "missing"
    with Session(database) as session:
        session.add(BackupLog(status="success", started_at=now.replace(tzinfo=None)-timedelta(hours=50), finished_at=now.replace(tzinfo=None)-timedelta(hours=49), filename="PRIVATE", error_message="SECRET"))
        session.commit()
    stale = snapshot(database, now=now, backup_enabled=True)
    assert stale["status"] == "degraded"
    assert stale["backup"]["status"] == "stale"
    with Session(database) as session:
        session.add(BackupLog(status="success", started_at=now.replace(tzinfo=None), finished_at=now.replace(tzinfo=None)))
        session.commit()
    assert snapshot(database, now=now, backup_enabled=True)["status"] == "healthy"
    with Session(database) as session:
        session.add(BackupLog(status="failed", started_at=now.replace(tzinfo=None)+timedelta(seconds=1), error_message="SECRET"))
        session.commit()
    failed = snapshot(database, now=now, backup_enabled=True)
    assert failed["backup"]["status"] == "failed"
    assert "SECRET" not in json.dumps(failed)
    assert "PRIVATE" not in json.dumps(failed)


def test_tracker_records_swallowed_and_uncaught_failures():
    tracker = importlib.import_module("scheduler_health") if importlib.util.find_spec("scheduler_health") else None
    assert tracker is not None, "scheduler health tracking has not been implemented"
    @tracker.tracked_job("test")
    def caught():
        tracker.job_failed("test")
    caught()
    assert tracker.job_history("test")["last_result"] == "failed"
    @tracker.tracked_job("test")
    def failure():
        raise RuntimeError("SECRET")
    with pytest.raises(RuntimeError):
        failure()
    assert tracker.job_history("test")["last_result"] == "failed"
    assert "SECRET" not in json.dumps(tracker.job_history("test"))
    @tracker.tracked_job("test")
    def success():
        pass
    success()
    assert tracker.job_history("test")["last_result"] == "success"


def test_health_endpoint_public_with_auth_enabled(database):
    from fastapi.testclient import TestClient
    import main
    health = service()
    with patch.object(main, "auth_enabled", return_value=True), patch.object(health, "runtime_health", return_value=snapshot(database)):
        response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.headers["cache-control"] == "no-store"
    with patch.object(main, "auth_enabled", return_value=True), patch.object(health, "runtime_health", return_value={"status": "unhealthy"}):
        assert TestClient(main.app).get("/health").status_code == 503


def test_production_refuses_missing_or_wrong_database():
    module = importlib.import_module("production") if importlib.util.find_spec("production") else None
    assert module is not None, "production launcher has not been implemented"
    with pytest.raises(ValueError, match="DATABASE_URL"):
        module.validate_environment({"APP_ENV": "production"})
    with pytest.raises(ValueError, match="PostgreSQL"):
        module.validate_environment({"APP_ENV": "production", "DATABASE_URL": "sqlite:///dev.db"})
    with pytest.raises(ValueError, match="PRODUCTION_DATABASE_NAME"):
        module.validate_environment({"APP_ENV": "production", "DATABASE_URL": "postgresql://u:p@localhost/dev", "PRODUCTION_DATABASE_NAME": "prod"})


def test_actual_scheduler_stop_degrades_health(database):
    from apscheduler.schedulers.background import BackgroundScheduler
    import scheduler_service as scheduler
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(lambda: None, "interval", seconds=60, id="standa_hub_reminders")
    sched.start()
    with patch.multiple(scheduler, _scheduler=sched, SCHEDULER_ENABLED=False, REMINDERS_CHECK_ENABLED=True, DAILY_BRIEFING_ENABLED=False, WEEKLY_REVIEW_ENABLED=False):
        assert scheduler.scheduler_snapshot()["status"] == "running"
        scheduler.stop_scheduler()
        state = scheduler.scheduler_snapshot()
        assert state["status"] == "stopped"
        assert snapshot(database, state)["status"] == "degraded"


def test_stalled_backup_and_missing_backup_owner(database):
    from models import BackupLog
    now = datetime.now(timezone.utc)
    with Session(database) as session:
        session.add(BackupLog(status="success", started_at=now.replace(tzinfo=None)-timedelta(hours=3), finished_at=now.replace(tzinfo=None)-timedelta(hours=2)))
        session.add(BackupLog(status="running", started_at=now.replace(tzinfo=None)-timedelta(hours=1, minutes=1)))
        session.commit()
    result = snapshot(database, now=now, backup_enabled=True)
    assert result["backup"]["status"] == "stalled"
    assert result["status"] == "degraded"
    assert snapshot(database, {"status": "running", "jobs": [], "backup_job_enabled": False}, now=now, backup_enabled=True)["status"] == "degraded"


def test_valid_production_config_and_invalid_auth_or_paths(tmp_path):
    import bcrypt
    import production
    env = {name: "false" for name in ("SCHEDULER_ENABLED", "REMINDERS_CHECK_ENABLED", "DAILY_BRIEFING_ENABLED", "WEEKLY_REVIEW_ENABLED", "BACKUP_ENABLED", "RUN_ALEMBIC_UPGRADE_AT_STARTUP")}
    env.update(APP_ENV="production", DATABASE_URL="postgresql://u:p@localhost/prod", PRODUCTION_DATABASE_NAME="prod", FRONTEND_ORIGINS="http://localhost:3000", AUTH_PIN_HASH=bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode(), MEDIA_DIR=str(tmp_path / "media"), BACKUP_DIR=str(tmp_path / "backups"), GROQ_API_KEY="dummy")
    production.validate_environment(env)
    with pytest.raises(ValueError, match="absolute"):
        production.validate_environment({**env, "MEDIA_DIR": "./dev-media"})
    with pytest.raises(ValueError, match="bcrypt"):
        production.validate_environment({**env, "AUTH_PIN_HASH": "dummy-not-hash"})


def test_postgres_backup_decodes_url_credentials(tmp_path):
    """A valid SQLAlchemy URL must use the same password when passed to pg_dump."""
    import io
    import backup_service
    commands = []
    class Process:
        stdout = io.BytesIO(b"-- dummy pg dump\n")
        returncode = 0
        def __init__(self, cmd, **kwargs):
            commands.append((cmd, kwargs["env"]["PGPASSWORD"]))
        def communicate(self, timeout):
            return None, b""
    with patch.object(backup_service, "_DATABASE_URL", "postgresql+psycopg2://test%40user:dummy%40%3A%2F%25@localhost:5433/prod"), patch.object(backup_service, "find_pg_dump", return_value="pg_dump"), patch.object(backup_service.subprocess, "Popen", Process):
        ok, _ = backup_service._backup_postgres(tmp_path / "dump.gz")
    assert ok
    assert commands[0][1] == "dummy@:/%"
    assert "--username=test@user" in commands[0][0]
    assert "--port=5433" in commands[0][0]


def test_production_refuses_invalid_boolean_flags(tmp_path):
    import bcrypt
    import production
    with pytest.raises(ValueError, match="SCHEDULER_ENABLED"):
        production.validate_environment({"APP_ENV": "production", "DATABASE_URL": "postgresql://u:p@localhost/prod", "PRODUCTION_DATABASE_NAME": "prod", "FRONTEND_ORIGINS": "http://localhost:3000", "AUTH_PIN_HASH": bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode(), "MEDIA_DIR": str(tmp_path), "BACKUP_DIR": str(tmp_path), "GROQ_API_KEY": "dummy", "SCHEDULER_ENABLED": "tru", "REMINDERS_CHECK_ENABLED": "false", "DAILY_BRIEFING_ENABLED": "false", "WEEKLY_REVIEW_ENABLED": "false", "BACKUP_ENABLED": "false", "RUN_ALEMBIC_UPGRADE_AT_STARTUP": "true"})
