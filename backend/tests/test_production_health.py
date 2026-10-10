"""Operational health uses scratch data and dummy canaries only."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from database import Base
from models import BackupLog

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    target = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(target)
    from health_service import code_revisions
    heads, _known = code_revisions()
    with target.begin() as connection:
        connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)'))
        connection.execute(text('INSERT INTO alembic_version VALUES (:head)'), {'head': heads[0]})
    yield target
    target.dispose()


def snapshot(**changes):
    return {'status': 'running', 'backup_job_enabled': True, 'jobs': [], **changes}


def health(engine, **kwargs):
    from health_service import collect_health
    return collect_health(engine, snapshot(), now=NOW, backup_enabled=True,
                          version={'version': '1.0.0', 'commit': 'abcdef1'}, **kwargs)


def add_backup(engine, hours=1, status='success', completed=True):
    with Session(engine) as db:
        db.add(BackupLog(started_at=(NOW-timedelta(hours=hours, minutes=1)).replace(tzinfo=None),
                         finished_at=(NOW-timedelta(hours=hours)).replace(tzinfo=None) if completed else None,
                         status=status, filename='/private/secret-canary.dump',
                         error_message='postgres://user:secret-canary@host/db',
                         size_bytes=20, checksum='a'*64))
        db.commit()


def test_healthy_and_safe_version(engine):
    add_backup(engine)
    result = health(engine)
    assert result['status'] == 'healthy'
    assert result['database']['status'] == 'reachable'
    assert result['migrations']['status'] == 'current'
    assert result['backup']['status'] == 'fresh'
    assert result['backup']['age_seconds'] == 3600
    assert result['version']['commit'] == 'abcdef1'
    assert 'secret-canary' not in json.dumps(result)


@pytest.mark.parametrize('hours,state,overall', [(26, 'fresh', 'healthy'), (27, 'stale', 'degraded'), (-1, 'unknown', 'degraded')])
def test_backup_threshold_and_future_unknown(engine, hours, state, overall):
    add_backup(engine, hours)
    result = health(engine)
    assert result['backup']['status'] == state
    assert result['status'] == overall
    assert result['backup']['max_age_seconds'] == 26*3600


def test_only_completed_success_is_valid_and_failed_attempt_warns(engine):
    add_backup(engine, 27)
    add_backup(engine, 1, completed=False)
    assert health(engine)['backup']['status'] == 'stale'
    add_backup(engine, 0, status='failed')
    result = health(engine)
    assert result['backup']['last_attempt_status'] == 'failed'
    assert result['backup']['status'] == 'stale'
    assert result['status'] == 'degraded'


def test_missing_and_disabled_backup(engine):
    assert health(engine)['backup']['status'] == 'unknown'
    from health_service import collect_health
    result = collect_health(engine, snapshot(), now=NOW, backup_enabled=False)
    assert result['backup']['status'] == 'disabled'
    assert result['status'] == 'healthy'


def test_database_failure_is_safe():
    target = Mock()
    target.connect.side_effect = RuntimeError('postgres://secret-canary/path?token=secret-canary')
    result = health(target)
    assert result['status'] == 'unhealthy'
    assert result['database']['status'] == 'unreachable'
    assert 'secret-canary' not in json.dumps(result)


def test_migration_mismatch_and_unknown_revision_redacted(engine):
    with engine.begin() as connection:
        connection.execute(text('UPDATE alembic_version SET version_num=:revision'), {'revision': 'secret-canary'})
    result = health(engine)
    assert result['status'] == 'unhealthy'
    assert result['migrations']['status'] == 'mismatch'
    assert 'secret-canary' not in json.dumps(result)


@pytest.mark.parametrize('state', ['stopped', 'degraded'])
def test_scheduler_degrades_health(engine, state):
    add_backup(engine)
    from health_service import collect_health
    result = collect_health(engine, snapshot(status=state), now=NOW, backup_enabled=True)
    assert result['status'] == 'degraded'


def test_missing_backup_owner_degrades(engine):
    add_backup(engine)
    from health_service import collect_health
    assert collect_health(engine, snapshot(backup_job_enabled=False), now=NOW, backup_enabled=True)['status'] == 'degraded'


def test_public_endpoint_http_policy(monkeypatch):
    import main
    import health_service
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, 'auth_enabled', lambda: True)
    # No lifespan: endpoint authentication and policy only; no scheduler/seed/LLM.
    client = TestClient(main.app)
    for state, code in [('healthy', 200), ('degraded', 200), ('unhealthy', 503)]:
        monkeypatch.setattr(health_service, 'runtime_health', lambda state=state: {'status': state})
        result = client.get('/health')
        assert result.status_code == code
        assert result.json()['status'] == state


def test_health_bypasses_unbounded_business_module_db_dependency(monkeypatch):
    import main
    import health_service
    from fastapi.testclient import TestClient
    def blocked():
        raise AssertionError('Health must not wait on module settings/application pool')
    monkeypatch.setattr(main, 'current_access', blocked)
    monkeypatch.setattr(health_service, 'runtime_health', lambda: {'status':'unhealthy'})
    assert TestClient(main.app).get('/health').status_code == 503
