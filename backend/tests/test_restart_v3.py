"""MRK-120: env-only backend restart (deploy/v3/lib/restart-v3.sh) in isolation.

Builds on the v3 world of test_deploy_v3.py (fake docker / curl / gh, real journal helpers). The fake docker runs with
FAKE_COMPOSE_ENV_FILE=1: like real Compose it inlines the raw env file into the backend config, so the config-hash
covers the values, and `run --env-file ... python -c` executes the restart's validation with the real production.py.

Covers: an edited .env.production makes the updater stop on BACKEND_COMPOSE_DRIFT until the restart; the restart
keeps image and commit, reconstructs the previous environment from the running container (hash-proven) as the rollback
source, validates the new file without touching production, names changed variables but never values, rolls back an
unhealthy result, recovers after a crash, and blocks / is blocked by pending deployments and migrations.
"""
import json
import shutil
import subprocess
import sys

import bcrypt
import pytest

from tests.test_deploy_v3 import REPO_ROOT, V3, World, out
from tests.test_deploy_migration_v3 import MigWorld

CANARY = 'secret-canary'
PIN_HASH = bcrypt.hashpw(b'1234', bcrypt.gensalt(4)).decode()
BASE_ENV = {
    'APP_ENV': 'production',
    'DATABASE_URL': f'postgresql+psycopg2://hub:{CANARY}-db@standa-postgres:5432/standa_hub',
    'PRODUCTION_DATABASE_NAME': 'standa_hub',
    'FRONTEND_ORIGINS': 'https://hub.example.test:8443',
    'AUTH_PIN_HASH': PIN_HASH,
    'AUTH_COOKIE_SECURE': 'true',
    'AUTH_TRUSTED_PROXIES': '',
    'MEDIA_DIR': '/data/media',
    'BACKUP_DIR': '/data/backups',
    'GROQ_API_KEY': f'gsk_{CANARY}',
    'SCHEDULER_ENABLED': 'false',
    'REMINDERS_CHECK_ENABLED': 'false',
    'DAILY_BRIEFING_ENABLED': 'false',
    'WEEKLY_REVIEW_ENABLED': 'false',
    'EXTERNAL_DELIVERY_ENABLED': 'false',
    'BACKUP_ENABLED': 'false',
    'RUN_ALEMBIC_UPGRADE_AT_STARTUP': 'false',
    'WEB_PUSH_VAPID_PRIVATE_KEY': '',
    'WEB_PUSH_VAPID_PUBLIC_KEY': '',
    'WEB_PUSH_CONTACT': '',
}
NEW_ENV = {**BASE_ENV, 'SCHEDULER_ENABLED': 'true', 'REMINDERS_CHECK_ENABLED': 'true',
           'EXTERNAL_DELIVERY_ENABLED': 'true', 'WEB_PUSH_VAPID_PRIVATE_KEY': f'vapid-private-{CANARY}',
           'WEB_PUSH_VAPID_PUBLIC_KEY': 'vapid-public', 'WEB_PUSH_CONTACT': 'mailto:hub@example.test',
           'GOOGLE_ICS_URL': f'https://calendar.example.test/private-{CANARY}/basic.ics'}


def env_text(values, comment=True):
    lines = ['# production env (test)'] if comment else []
    return '\n'.join(lines + [f'{k}={v}' for k, v in values.items()]) + '\n'


class RestartMixin:
    def setup_restart(self):
        self.restart = self.tmp / 'restart-v3.sh'
        shutil.copy(V3 / 'lib' / 'restart-v3.sh', self.restart)
        self.restart.chmod(0o755)
        self.env.update(FAKE_COMPOSE_ENV_FILE='1', FAKE_PYTHON=sys.executable, FAKE_BACKEND_DIR=str(REPO_ROOT / 'backend'))
        self.write_env(BASE_ENV)
        self.recreate_backend_from_env()

    def write_env(self, values, comment=True):
        self.env_file.write_text(env_text(values, comment))
        self.env_file.chmod(0o600)

    def recreate_backend_from_env(self):
        """Production as the last deployment left it: the backend created from the current env file."""
        c = self.state_json()['containers']['standa-hub-backend']
        r = subprocess.run(['docker', 'compose', '-p', 'backend', '-f', str(self.trusted / 'backend-managed.yaml'),
                            'up', '-d', 'backend'], capture_output=True, text=True,
                           env={**self.env, 'BACKEND_IMAGE': c['image_ref'], 'BACKEND_ENV_FILE': str(self.env_file),
                                'APP_COMMIT': c['app_commit']})
        assert r.returncode == 0, r.stderr
        (self.fake / 'calls.log').unlink(missing_ok=True)  # observations start after the simulated deployment

    def rs(self, mode, **extra):
        return self._locked(str(self.restart), mode, extra=extra)

    def backend(self):
        return self.state_json()['containers']['standa-hub-backend']

    def restarts(self):
        return sorted(p for p in self.state.glob('restart-v3-*'))

    def rjournal(self):
        (d,) = self.restarts()
        return json.loads((d / 'journal.json').read_text())

    def staging(self):
        return sorted(p.name for p in self.state.glob('.staging-restart-v3-*'))

    def up_calls(self):
        log = self.fake / 'calls.log'
        return [line for line in log.read_text().splitlines() if line.startswith('up backend')] if log.exists() else []


class RestartWorld(RestartMixin, World):
    def __init__(self, tmp):
        super().__init__(tmp)
        self.setup_restart()


@pytest.fixture
def r(tmp_path):
    return RestartWorld(tmp_path)


def no_secret(*texts):
    for text in texts:
        assert CANARY not in text, 'a secret value leaked'


# ---------- the problem and the happy path ----------

def test_edited_env_file_blocks_the_updater_until_the_restart(r):
    a = r.running_commit()
    assert r.tx('--check', a).returncode == 0
    r.write_env(NEW_ENV)
    blocked = r.tx('--check', a)
    assert blocked.returncode != 0 and 'BACKEND_COMPOSE_DRIFT' in out(blocked)

    result = r.rs('--apply')
    assert result.returncode == 0, out(result)
    assert 'RESTART_OK' in result.stdout
    after = r.tx('--check', a)
    assert after.returncode == 0 and 'ALREADY_DEPLOYED' in after.stdout, out(after)


def test_apply_keeps_image_and_commit_and_loads_the_new_env(r):
    before = r.backend()
    r.write_env(NEW_ENV)
    result = r.rs('--apply')
    assert result.returncode == 0, out(result)
    for marker in ('NO_PENDING_TRANSACTIONS', 'PRODUCTION_BACKEND_VERIFIED', 'PREVIOUS_ENV_RECONSTRUCTED', 'ENV_VALID',
                   'RESTART_PREFLIGHT_OK', 'JOURNAL_UPDATED: prepared -> recreating', 'RESTART_OK'):
        assert marker in result.stdout, marker
    assert 'ENV_ADDED: GOOGLE_ICS_URL' in result.stdout
    assert ('ENV_CHANGED: EXTERNAL_DELIVERY_ENABLED, REMINDERS_CHECK_ENABLED, SCHEDULER_ENABLED, WEB_PUSH_CONTACT, '
            'WEB_PUSH_VAPID_PRIVATE_KEY, WEB_PUSH_VAPID_PUBLIC_KEY') in result.stdout
    after = r.backend()
    assert (after['image_id'], after['image_ref'], after['app_commit']) == (before['image_id'], before['image_ref'],
                                                                          before['app_commit'])
    assert after['env']['SCHEDULER_ENABLED'] == 'true' and after['env']['GOOGLE_ICS_URL'] == NEW_ENV['GOOGLE_ICS_URL']
    assert after['hash'] != before['hash']
    journal = r.rjournal()
    assert journal['state'] == 'restarted' and journal['previous_hash'] == before['hash']
    assert journal['target_hash'] == after['hash'] and journal['app_commit'] == before['app_commit']
    (d,) = r.restarts()
    assert oct(d.stat().st_mode & 0o777) == '0o700'
    for f in ('env.previous', 'env.target', 'journal.json'):
        assert oct((d / f).stat().st_mode & 0o777) == '0o600', f
    no_secret(result.stdout, result.stderr, (d / 'journal.json').read_text())
    assert r.staging() == []


def test_check_changes_nothing_and_leaves_no_secrets_behind(r):
    before = r.backend()
    r.write_env(NEW_ENV)
    result = r.rs('--check')
    assert result.returncode == 0, out(result)
    assert 'RESTART_PREFLIGHT_OK' in result.stdout and 'NO_PRODUCTION_CHANGES' in result.stdout
    assert r.backend() == before and r.up_calls() == []
    assert r.restarts() == [] and r.staging() == []
    no_secret(result.stdout, result.stderr)


def test_nothing_to_restart_when_the_file_matches_the_running_env(r):
    r.write_env(BASE_ENV, comment=False)  # comments and order do not matter, values do
    result = r.rs('--apply')
    assert result.returncode == 0, out(result)
    assert 'NOTHING_TO_RESTART' in result.stdout and r.up_calls() == [] and r.restarts() == []


def test_previous_env_is_reconstructed_even_after_the_file_was_edited(r):
    """The rollback source comes from the running container, not from the (already edited) file."""
    r.write_env(NEW_ENV)
    r.rs('--apply')
    (d,) = r.restarts()
    previous = dict(line.split('=', 1) for line in (d / 'env.previous').read_text().splitlines())
    assert previous == BASE_ENV


# ---------- validation before any change ----------

@pytest.mark.parametrize('change, message', [
    ({'EXTERNAL_DELIVERY_ENABLED': 'true'},
     'EXTERNAL_DELIVERY_ENABLED=true requires WEB_PUSH_VAPID_PRIVATE_KEY, WEB_PUSH_VAPID_PUBLIC_KEY, WEB_PUSH_CONTACT'),
    ({'APP_ENV': 'development'}, 'APP_ENV must be production'),
    ({'SCHEDULER_ENABLED': 'maybe'}, 'SCHEDULER_ENABLED must be an explicit boolean'),
    ({'BACKUP_ENABLED': 'true'}, 'BACKUP_ENABLED requires the hourly scheduler owner'),
    ({'DATABASE_URL': f'sqlite:///{CANARY}.db'}, 'DATABASE_URL must be an explicit PostgreSQL URL'),
])
def test_invalid_env_is_refused_before_the_container_is_touched(r, change, message):
    before = r.backend()
    r.write_env({**BASE_ENV, **change})
    result = r.rs('--apply')
    assert result.returncode != 0
    assert f'ENV_INVALID: {message}' in result.stderr, out(result)
    assert r.backend() == before and r.up_calls() == [] and r.restarts() == [] and r.staging() == []
    no_secret(result.stdout, result.stderr)


def test_validation_runs_without_network_on_the_running_image(r):
    r.write_env(NEW_ENV)
    r.rs('--check')
    calls = (r.fake / 'calls.log').read_text()
    assert f'run-python none {r.backend()["image_id"]}' in calls
    assert '--network none --pull never --env-file' in calls


# ---------- rollback and recovery ----------

def test_unhealthy_backend_is_rolled_back_to_the_previous_env(r):
    before = r.backend()
    r.write_env({**NEW_ENV, 'FAKE_UNHEALTHY': '1'})
    result = r.rs('--apply')
    assert result.returncode != 0
    assert 'BACKEND_HEALTH_FAILED' in result.stderr and 'ROLLBACK_VERIFIED' in result.stdout, out(result)
    assert 'RESTART_ROLLED_BACK' in result.stderr
    after = r.backend()
    assert after['hash'] == before['hash'] and after['env'] == before['env'] and after['image_id'] == before['image_id']
    assert r.rjournal()['state'] == 'rolled_back'
    # the updater keeps refusing while the file still differs from the running container
    assert 'BACKEND_COMPOSE_DRIFT' in out(r.tx('--check', r.running_commit()))
    no_secret(result.stdout, result.stderr)


def test_crash_during_recreate_blocks_everything_until_recover(r):
    before = r.backend()
    r.write_env(NEW_ENV)
    r.inject(kill_on_up=['backend'])
    crashed = r.rs('--apply')
    assert crashed.returncode != 0
    assert r.rjournal()['state'] == 'recreating'
    assert 'PENDING_RESTART' in out(r.tx('--check', r.running_commit()))
    assert 'PENDING_RESTART' in out(r.rs('--check'))

    recovered = r.rs('--recover')
    assert recovered.returncode == 0, out(recovered)
    assert 'ROLLBACK_VERIFIED' in recovered.stdout and r.rjournal()['state'] == 'rolled_back'
    assert r.backend()['hash'] == before['hash']
    assert 'NO_PENDING_RESTART' in r.rs('--recover').stdout

    again = r.rs('--apply')
    assert again.returncode == 0, out(again)
    assert r.backend()['env']['SCHEDULER_ENABLED'] == 'true'


def test_recover_aborts_a_prepared_restart_without_touching_the_backend(r):
    before = r.backend()
    d = r.state / 'restart-v3-20261121T170000Z-1'
    d.mkdir(mode=0o700)
    (d / 'journal.json').write_text(json.dumps({
        'state': 'prepared', 'app_commit': before['app_commit'], 'image_reference': before['image_ref'],
        'image_id': before['image_id'], 'previous_hash': before['hash'], 'target_hash': 'x'}))
    result = r.rs('--recover')
    assert result.returncode == 0, out(result)
    assert 'RESTART_ABORTED_NO_PRODUCTION_CHANGE' in result.stdout
    assert r.rjournal()['state'] == 'aborted' and r.backend() == before and r.up_calls() == []


def test_stale_staging_directory_is_removed(r):
    stale = r.state / '.staging-restart-v3-leftover'
    stale.mkdir(mode=0o700)
    (stale / 'env.target').write_text(f'GROQ_API_KEY={CANARY}\n')
    result = r.rs('--check')
    assert 'STALE_STAGING_REMOVED: .staging-restart-v3-leftover' in result.stdout
    assert not stale.exists()


# ---------- refusals ----------

def test_pending_deployment_blocks_the_restart(r):
    d = r.state / 'transaction-v3-deadbeef'
    d.mkdir()
    (d / 'journal.json').write_text(json.dumps({'state': 'deploying'}))
    r.write_env(NEW_ENV)
    result = r.rs('--apply')
    assert result.returncode != 0 and 'PENDING_TRANSACTION' in result.stderr
    assert r.up_calls() == []


def test_unprovable_previous_env_is_refused(r):
    """A file variable equal to an image variable cannot be told apart from it: refuse instead of guessing."""
    r.write_env({**BASE_ENV, 'PATH': '/usr/bin'})
    r.recreate_backend_from_env()
    r.write_env(NEW_ENV)
    result = r.rs('--apply')
    assert result.returncode != 0 and 'PREVIOUS_ENV_NOT_RECONSTRUCTABLE' in result.stderr, out(result)
    assert r.restarts() == [] and r.staging() == []


def test_env_file_writable_by_others_is_refused(r):
    r.env_file.chmod(0o666)
    result = r.rs('--check')
    assert result.returncode != 0 and 'UNTRUSTED_ENV_FILE' in result.stderr


def test_maintenance_lock_is_required(r):
    result = subprocess.run(['bash', str(r.restart), '--check'], env=r.env, capture_output=True, text=True)
    assert result.returncode != 0 and 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' in result.stderr


def test_usage(r):
    result = r.rs('--force')
    assert result.returncode == 2 and 'Usage' in result.stderr


# ---------- a pending restart also blocks a controlled migration ----------

class MigRestartWorld(RestartMixin, MigWorld):
    def __init__(self, tmp):
        super().__init__(tmp)
        self.setup_restart()


def test_pending_restart_blocks_the_controlled_migration(tmp_path):
    m = MigRestartWorld(tmp_path)
    b = m.migration_release()
    d = m.state / 'restart-v3-20261121T170000Z-1'
    d.mkdir(mode=0o700)
    (d / 'journal.json').write_text(json.dumps({'state': 'verifying'}))
    result = m.mig('--check', b)
    assert result.returncode != 0 and 'PENDING_TRANSACTION' in out(result) and 'restart-v3-' in out(result)
