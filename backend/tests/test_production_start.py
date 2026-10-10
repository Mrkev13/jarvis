from pathlib import Path

import bcrypt
import pytest


def config(tmp_path):
    return dict(APP_ENV='production', DATABASE_URL='postgresql+psycopg2://user:placeholder@localhost/standa_test',
                PRODUCTION_DATABASE_NAME='standa_test', AUTH_PIN_HASH=bcrypt.hashpw(b'dummy', bcrypt.gensalt(rounds=4)).decode(),
                FRONTEND_ORIGINS='http://localhost:3000', MEDIA_DIR=str(tmp_path/'media'), BACKUP_DIR=str(tmp_path/'backup'),
                GROQ_API_KEY='dummy', SCHEDULER_ENABLED='true', REMINDERS_CHECK_ENABLED='true',
                DAILY_BRIEFING_ENABLED='false', WEEKLY_REVIEW_ENABLED='false', EXTERNAL_DELIVERY_ENABLED='false',
                BACKUP_ENABLED='true', RUN_ALEMBIC_UPGRADE_AT_STARTUP='false')


def test_validate_explicit_production_config(tmp_path):
    from production import validate_environment
    validate_environment(config(tmp_path))


@pytest.mark.parametrize('key,value', [('DATABASE_URL','sqlite:///secret-canary.db'), ('PRODUCTION_DATABASE_NAME','wrong'),
                                      ('SCHEDULER_ENABLED','false'), ('RUN_ALEMBIC_UPGRADE_AT_STARTUP','true'),
                                      ('AUTH_PIN_HASH','secret-canary'), ('BACKUP_DIR','relative'), ('GROQ_API_KEY','')])
def test_unsafe_config_rejected_without_values(tmp_path, key, value):
    from production import validate_environment
    env = config(tmp_path)
    env[key] = value
    with pytest.raises(ValueError) as error:
        validate_environment(env)
    assert 'secret-canary' not in str(error.value)


def test_file_overrides_inherited_dev_config_and_disables_dotenv(tmp_path, monkeypatch):
    from production import load_production_environment
    env = config(tmp_path)
    target=tmp_path/'production.env'
    target.write_text('\n'.join(f'{k}={v}' for k,v in env.items()))
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///development.db')
    # Restore mutations through monkeypatch teardown.
    for key in [*env, 'PYTHON_DOTENV_DISABLED']:
        monkeypatch.setenv(key, '')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///development.db')
    load_production_environment(target)
    import os
    assert os.environ['DATABASE_URL'] == env['DATABASE_URL']
    assert os.environ['PYTHON_DOTENV_DISABLED'] == 'true'


def test_missing_file_config_cannot_inherit_dev_db(tmp_path, monkeypatch):
    from production import load_production_environment
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:secret-canary@host/dev')
    target=tmp_path/'empty.env'
    target.write_text('APP_ENV=production\n')
    with pytest.raises(ValueError) as error:
        load_production_environment(target)
    assert 'secret-canary' not in str(error.value)


def test_foreground_exec_one_worker_explicit_cwd(tmp_path, monkeypatch):
    import production
    captured={}
    env=config(tmp_path)
    target=tmp_path/'production.env'
    target.write_text('\n'.join(f'{k}={v}' for k,v in env.items()))
    for key in [*env, 'PYTHON_DOTENV_DISABLED', 'APP_COMMIT']:
        monkeypatch.setenv(key, '')
    monkeypatch.setattr(production.os, 'chdir', lambda path: captured.update(cwd=path))
    # Capture the command on every platform (Windows runs a supervised child, POSIX execs) – never start a server.
    monkeypatch.setattr(production, 'run_server', lambda args: captured.update(args=args) or 0)
    production.main(['--env-file',str(target)])
    assert captured['cwd'] == Path(production.__file__).resolve().parent
    assert '--reload' not in captured['args']
    assert captured['args'][-2:] == ['--workers','1']
    assert captured['args'][1:4] == ['-m','uvicorn','main:app']


def test_commit_is_resolved_once_at_start_and_safe_fallback(monkeypatch):
    import production
    from unittest.mock import Mock
    calls=[]
    def run(*args, **kwargs):
        calls.append(args)
        return Mock(returncode=0, stdout='a'*40+'\n')
    monkeypatch.setattr(production.subprocess, 'run', run)
    assert production.resolve_commit() == 'a'*40
    assert len(calls) == 1
    monkeypatch.setattr(production.subprocess, 'run', lambda *a, **k: Mock(returncode=1, stdout='secret-canary'))
    assert production.resolve_commit() == ''


def test_windows_waits_for_worker_and_propagates_failure(monkeypatch):
    import production
    from unittest.mock import Mock
    calls=[]
    monkeypatch.setattr(production.os, 'name', 'nt')
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return Mock(returncode=17)
    monkeypatch.setattr(production.subprocess, 'run', run)
    assert production.run_server(['python', '-m', 'uvicorn', 'main:app']) == 17
    assert calls == [(['python', '-m', 'uvicorn', 'main:app'], {'check':False})]
