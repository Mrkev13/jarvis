import io
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('scheme', ['postgresql', 'postgresql+psycopg2', 'postgres'])
def test_encoded_credentials_query_parameters(scheme, tmp_path, monkeypatch):
    import backup_service as service
    url = scheme + '://user:p%40ss%3A%2F%25%3F@localhost:5434/test_db?sslmode=require&application_name=backup'
    monkeypatch.setattr(service, '_DATABASE_URL', url)
    monkeypatch.setattr(service, 'find_pg_dump', lambda: 'pg_dump')
    observed = {}
    def popen(cmd, **kwargs):
        observed.update(cmd=cmd, **kwargs)
        return Mock(stdout=io.BytesIO(b'SELECT 1;'), returncode=0, communicate=lambda **_: (None, b''))
    monkeypatch.setattr(service.subprocess, 'Popen', popen)
    assert service._backup_postgres(tmp_path/'test.gz') == (True, '')
    assert observed['env']['PGPASSWORD'] == 'p@ss:/%?'
    assert observed['env']['PGSSLMODE'] == 'require'
    assert observed['env']['PGAPPNAME'] == 'backup'
    assert '--host=localhost' in observed['cmd']
    assert '--port=5434' in observed['cmd']
    assert observed['cmd'][-1] == 'test_db'
    assert url not in str(observed['cmd'])


@pytest.mark.parametrize('url', ['invalid-secret-canary', 'postgresql://user:secret-canary@host/db?unsupported=secret-canary'])
def test_invalid_url_errors_safe(url, tmp_path, monkeypatch):
    import backup_service as service
    monkeypatch.setattr(service, '_DATABASE_URL', url)
    result = service._backup_postgres(tmp_path/'test.gz')
    assert result[0] is False
    assert 'secret-canary' not in str(result)


def test_pg_dump_error_redacted(tmp_path, monkeypatch, caplog):
    import backup_service as service
    monkeypatch.setattr(service, '_DATABASE_URL', 'postgresql://user:secret-canary@localhost/test_db')
    monkeypatch.setattr(service, 'find_pg_dump', lambda: 'pg_dump')
    process = Mock(stdout=io.BytesIO(b''), returncode=1, communicate=lambda **_: (None, b'secret-canary /private/path'))
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: process)
    assert service._backup_postgres(tmp_path/'test.gz') == (False, 'pg_dump failed')
    assert 'secret-canary' not in caplog.text


def test_entire_failed_run_log_and_metadata_are_safe(tmp_path, monkeypatch, caplog):
    import backup_service as service
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database import Base
    from models import BackupLog
    import json
    target=create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(target)
    monkeypatch.setattr(service, 'BACKUP_ENABLED', True)
    monkeypatch.setattr(service, 'BACKUP_DIR', str(tmp_path/'backup'))
    monkeypatch.setattr(service, '_DATABASE_URL', 'postgresql://user:secret-canary@host/test_db')
    monkeypatch.setattr(service, '_backup_postgres', lambda path: (path.write_bytes(b'dump') and True, ''))
    monkeypatch.setattr(service, 'sync_media_archive', Mock(side_effect=RuntimeError('secret-canary')))
    with Session(target) as db:
        backup_id=service.run_backup(db)
        assert db.get(BackupLog, backup_id).status == 'failed'
        assert 'secret-canary' not in db.get(BackupLog, backup_id).error_message
    metadata=next((tmp_path/'backup'/'runs').glob('*.json')).read_text()
    assert 'secret-canary' not in caplog.text+metadata
    assert json.loads(metadata)['status']=='failed'
    target.dispose()
