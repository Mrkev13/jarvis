"""MRK-121: frontend template change + recreate (deploy/v3/lib/frontend-template-v3.sh) in isolation.

Builds on the v3 world of test_deploy_v3.py. The fake docker runs with FAKE_COMPOSE_TEMPLATE_HASH=1: like real Compose
the config-hash covers the template (the game-assets volume changes it) and `inspect` shows the frontend env.

Covers: installing the new template alone makes the updater stop on FRONTEND_COMPOSE_DRIFT; the script proves the
installed template against the running frontend (API URL taken from the container, never printed), recreates with the
same image, installs the template only after a healthy start, rolls back container AND template, recovers after a
crash, and blocks / is blocked by the other v3 operations.
"""
import json
import shutil
import subprocess

import pytest

from tests.test_deploy_v3 import V3, World, out

NEW_TEMPLATE = V3 / 'mrk108' / 'frontend-managed.yaml'
# Production today = the template without the MRK-121 volume block (derived here: CI has a shallow checkout without
# the older commit, so no `git show`).
VOLUME_BLOCK = '''
    # MRK-121: game images (not in Git/image) from the host; read-only. Next serves the files present at start,
    # app/game-assets/[...path]/route.ts the ones fetched later. Missing directory -> fallback icons.
    volumes:
      - /srv/standa-hub-data/game-assets:/app/public/game-assets:ro
'''
assert NEW_TEMPLATE.read_text().count(VOLUME_BLOCK) == 1
OLD_TEMPLATE = NEW_TEMPLATE.read_text().replace(VOLUME_BLOCK, '')
API_HOST = 'hub.example.test'


class TemplateWorld(World):
    def __init__(self, tmp):
        super().__init__(tmp)
        self.script = tmp / 'frontend-template-v3.sh'
        shutil.copy(V3 / 'lib' / 'frontend-template-v3.sh', self.script)
        self.script.chmod(0o755)
        self.env['FAKE_COMPOSE_TEMPLATE_HASH'] = '1'
        self.installed = self.trusted / 'frontend-managed.yaml'
        self.installed.write_text(OLD_TEMPLATE)  # production today: the template without the volume
        self.installed.chmod(0o644)
        self.candidate = tmp / 'frontend-managed.new.yaml'
        shutil.copy(NEW_TEMPLATE, self.candidate)
        self.candidate.chmod(0o644)
        assert 'game-assets' in self.candidate.read_text() and 'game-assets' not in OLD_TEMPLATE
        self.recreate('backend')
        self.recreate('frontend')
        (self.fake / 'calls.log').unlink(missing_ok=True)

    def recreate(self, service):
        """Production as the last deployment left it: containers created from the installed templates."""
        c = self.state_json()['containers'][f'standa-hub-{service}']
        extra = ({'BACKEND_IMAGE': c['image_ref'], 'BACKEND_ENV_FILE': str(self.env_file), 'APP_COMMIT': c['app_commit']}
                 if service == 'backend' else {'FRONTEND_IMAGE': c['image_ref'], 'NEXT_PUBLIC_API_URL': f'https://{API_HOST}:8443'})
        r = subprocess.run(['docker', 'compose', '-p', service, '-f', str(self.trusted / f'{service}-managed.yaml'),
                            'up', '-d', service], capture_output=True, text=True, env={**self.env, **extra})
        assert r.returncode == 0, r.stderr

    def ft(self, *args, **extra):
        return self._locked(str(self.script), *args, extra=extra)

    def frontend(self):
        return self.state_json()['containers']['standa-hub-frontend']

    def changes(self):
        return sorted(self.state.glob('template-v3-*'))

    def tjournal(self):
        (d,) = self.changes()
        return json.loads((d / 'journal.json').read_text())

    def staging(self):
        return sorted(self.state.glob('.staging-template-v3-*'))

    def frontend_ups(self):
        log = self.fake / 'calls.log'
        return [x for x in log.read_text().splitlines() if x.startswith('up frontend')] if log.exists() else []


@pytest.fixture
def t(tmp_path):
    return TemplateWorld(tmp_path)


def no_host(*texts):
    for text in texts:
        assert API_HOST not in text, 'the API URL (tailnet hostname in production) must not be printed'


def test_installing_the_template_alone_blocks_the_updater(t):
    a = t.running_commit()
    assert t.tx('--check', a).returncode == 0
    t.installed.write_text(NEW_TEMPLATE.read_text())
    blocked = t.tx('--check', a)
    assert blocked.returncode != 0 and 'FRONTEND_COMPOSE_DRIFT' in out(blocked)


def test_apply_recreates_with_the_volume_and_then_installs_the_template(t):
    before = t.frontend()
    result = t.ft('--apply', str(t.candidate))
    assert result.returncode == 0, out(result)
    for marker in ('NO_PENDING_TRANSACTIONS', 'PRODUCTION_FRONTEND_VERIFIED', 'INSTALLED_TEMPLATE_MATCHES_RUNNING',
                   'TEMPLATE_PREFLIGHT_OK', 'JOURNAL_UPDATED: verifying -> restarted', 'FRONTEND_TEMPLATE_APPLIED'):
        assert marker in result.stdout, marker
    assert '+      - /srv/standa-hub-data/game-assets:/app/public/game-assets:ro' in result.stdout
    after = t.frontend()
    assert (after['image_id'], after['image_ref']) == (before['image_id'], before['image_ref'])
    assert after['hash'] != before['hash']
    assert t.installed.read_text() == NEW_TEMPLATE.read_text()
    assert oct(t.installed.stat().st_mode & 0o777) == '0o644'
    assert t.tjournal()['state'] == 'restarted' and t.tjournal()['previous_hash'] == before['hash']
    ok = t.tx('--check', t.running_commit())
    assert ok.returncode == 0 and 'ALREADY_DEPLOYED' in ok.stdout, out(ok)
    no_host(result.stdout, result.stderr, json.dumps(t.tjournal()))
    assert t.staging() == []


def test_check_changes_nothing(t):
    before = t.frontend()
    result = t.ft('--check', str(t.candidate))
    assert result.returncode == 0, out(result)
    assert 'TEMPLATE_PREFLIGHT_OK' in result.stdout and 'NO_PRODUCTION_CHANGES' in result.stdout
    assert t.frontend() == before and t.frontend_ups() == [] and t.installed.read_text() == OLD_TEMPLATE
    assert t.changes() == [] and t.staging() == []


def test_nothing_to_change_for_the_installed_template(t):
    same = t.tmp / 'same.yaml'
    same.write_text(OLD_TEMPLATE)
    same.chmod(0o644)
    result = t.ft('--apply', str(same))
    assert result.returncode == 0 and 'NOTHING_TO_CHANGE' in result.stdout and t.frontend_ups() == []


def test_installed_template_that_does_not_match_the_running_frontend_is_refused(t):
    t.installed.write_text(OLD_TEMPLATE + '\n# edited by hand\n')
    result = t.ft('--apply', str(t.candidate))
    assert result.returncode != 0 and 'INSTALLED_TEMPLATE_DRIFT' in result.stderr
    assert t.frontend_ups() == [] and t.changes() == []


def test_unhealthy_frontend_rolls_back_container_and_template(t):
    before = t.frontend()
    t.candidate.write_text(NEW_TEMPLATE.read_text() + '\n# FAKE_UNHEALTHY\n')
    result = t.ft('--apply', str(t.candidate))
    assert result.returncode != 0
    assert 'FRONTEND_HEALTH_FAILED' in result.stderr and 'ROLLBACK_VERIFIED' in result.stdout, out(result)
    assert t.frontend()['hash'] == before['hash'] and t.installed.read_text() == OLD_TEMPLATE
    assert t.tjournal()['state'] == 'rolled_back'
    assert t.tx('--check', t.running_commit()).returncode == 0


def test_crash_during_recreate_blocks_everything_until_recover(t):
    before = t.frontend()
    t.inject(kill_on_up=['frontend'])
    crashed = t.ft('--apply', str(t.candidate))
    assert crashed.returncode != 0 and t.tjournal()['state'] == 'recreating'
    assert 'PENDING_RESTART' in out(t.tx('--check', t.running_commit()))
    assert 'PENDING_TEMPLATE' in out(t.ft('--check', str(t.candidate)))

    recovered = t.ft('--recover')
    assert recovered.returncode == 0, out(recovered)
    assert 'ROLLBACK_VERIFIED' in recovered.stdout and t.tjournal()['state'] == 'rolled_back'
    assert t.frontend()['hash'] == before['hash'] and t.installed.read_text() == OLD_TEMPLATE
    assert 'NO_PENDING_TEMPLATE_CHANGE' in t.ft('--recover').stdout

    again = t.ft('--apply', str(t.candidate))
    assert again.returncode == 0, out(again)
    assert t.installed.read_text() == NEW_TEMPLATE.read_text()


def test_recover_after_template_installed_but_not_finished_restores_both(t):
    """Crash between installing the template and the terminal state: --recover puts the old template back too."""
    before = t.frontend()
    assert t.ft('--apply', str(t.candidate)).returncode == 0
    (d,) = t.changes()
    j = json.loads((d / 'journal.json').read_text())
    j['state'] = 'verifying'
    (d / 'journal.json').write_text(json.dumps(j))
    recovered = t.ft('--recover')
    assert recovered.returncode == 0, out(recovered)
    assert t.installed.read_text() == OLD_TEMPLATE and t.frontend()['hash'] == before['hash']
    assert t.tx('--check', t.running_commit()).returncode == 0


def test_pending_backend_restart_blocks_the_template_change(t):
    d = t.state / 'restart-v3-20261121T180000Z-1'
    d.mkdir(mode=0o700)
    (d / 'journal.json').write_text(json.dumps({'state': 'recreating'}))
    result = t.ft('--apply', str(t.candidate))
    assert result.returncode != 0 and 'PENDING_RESTART' in result.stderr and t.frontend_ups() == []


def test_untrusted_template_is_refused(t):
    t.candidate.chmod(0o666)
    result = t.ft('--check', str(t.candidate))
    assert result.returncode != 0 and 'UNTRUSTED_TEMPLATE' in result.stderr


def test_lock_and_usage(t):
    no_lock = subprocess.run(['bash', str(t.script), '--check', str(t.candidate)], env=t.env, capture_output=True, text=True)
    assert no_lock.returncode != 0 and 'ROOT_AND_MAINTENANCE_LOCK_REQUIRED' in no_lock.stderr
    assert t.ft('--apply').returncode == 2
