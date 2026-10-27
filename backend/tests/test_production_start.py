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


HTTPS_ORIGIN = 'https://hub.example-tailnet.ts.net'


@pytest.mark.parametrize('origins,secure', [
    ('http://localhost:3000', None),                          # today's HTTP-only runtime stays valid
    ('http://localhost:3000', 'false'),
    (HTTPS_ORIGIN, 'true'),                                     # MRK-24: Tailscale Serve HTTPS
    (f'http://127.0.0.1:3000,{HTTPS_ORIGIN}', 'true'),          # local upstream origin kept next to HTTPS
])
def test_cookie_security_matches_frontend_origins(tmp_path, origins, secure):
    from production import validate_environment
    env = {**config(tmp_path), 'FRONTEND_ORIGINS': origins}
    if secure is not None:
        env['AUTH_COOKIE_SECURE'] = secure
    validate_environment(env)


@pytest.mark.parametrize('origins,secure', [
    (HTTPS_ORIGIN, None),        # HTTPS frontend must not issue a session cookie usable over plain HTTP
    (HTTPS_ORIGIN, 'false'),
    (f'http://localhost:3000, {HTTPS_ORIGIN}', 'false'),
    ('http://localhost:3000', 'true'),   # Secure cookie with no HTTPS origin = login can never succeed
    (HTTPS_ORIGIN, 'maybe'),
])
def test_cookie_security_mismatch_is_rejected(tmp_path, origins, secure):
    from production import validate_environment
    env = {**config(tmp_path), 'FRONTEND_ORIGINS': origins}
    if secure is not None:
        env['AUTH_COOKIE_SECURE'] = secure
    with pytest.raises(ValueError) as error:
        validate_environment(env)
    assert 'AUTH_COOKIE_SECURE' in str(error.value) and 'ts.net' not in str(error.value)


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
    # MRK-73: Uvicorn must not rewrite the client address from X-Forwarded-For (it trusts 127.0.0.1 by default)
    from uvicorn.main import main as uvicorn_cli
    params = uvicorn_cli.make_context('uvicorn', captured['args'][3:]).params
    assert params['proxy_headers'] is False


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


SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts' / 'windows'


@pytest.mark.parametrize('name', ['start-backend.ps1', 'start-frontend.ps1', 'register-tasks.ps1'])
def test_bind_address_is_allowlisted_and_defaults_to_current_behaviour(name):
    # MRK-24: 127.0.0.1 after Tailscale Serve acceptance; the default keeps today's direct tailnet HTTP.
    text = (SCRIPTS / name).read_text(encoding='utf-8')
    assert "[string]$BindAddress = '0.0.0.0'" in text
    assert "$BindAddress -notin @('0.0.0.0', '127.0.0.1')" in text
    assert "'0.0.0.0' --port" not in text and "'--hostname', '0.0.0.0'" not in text, 'no hard-coded bind left'


def test_tailscale_serve_script_is_tailnet_only():
    text = (SCRIPTS / 'tailscale-serve.ps1').read_text(encoding='utf-8')
    commands = [line for line in text.splitlines() if '& $ts ' in line]
    assert commands and not any('funnel' in line.lower() for line in commands), 'never enables Funnel'
    serve_bg = [line for line in commands if '--bg' in line]
    assert serve_bg and all(line.rstrip().endswith('$route.Expected | Out-Null') for line in serve_bg)
    assert 'Expected = "http://127.0.0.1:$FrontendPort"' in text and 'Expected = "http://127.0.0.1:$BackendPort"' in text, \
        'loopback upstreams only'
    # Fail closed: a failed `serve status` must never read as "nothing configured", and Funnel is detected anywhere
    # in the JSON (including foreground sessions), refusing Apply and failing every mode at the end.
    assert "if ($LASTEXITCODE -ne 0) { throw 'tailscale serve status failed" in text
    assert '"AllowFunnel"' in text and 'if (Test-Funnel $before) { throw' in text and 'if (Test-Funnel $after) { throw' in text
