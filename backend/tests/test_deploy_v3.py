"""MRK-108 v3 deployment (deploy/v3, PR #65) in isolation: the real updater, transaction, journal, release and backup
checks against a fake docker / curl / gh and a real git repository with a local origin. Nothing touches Docker,
the network or production paths; the scripts get their paths and the required UID through DEPLOY_* variables.

Covers the audit findings: an interrupted transaction in every phase ("prepared", "deploying", an interrupted rollback,
an incomplete or staging directory) is recoverable or blocks safely; target images are trusted by the provenance of
their build, not by the revision label; the CI gate is bound to the SHA, the production branch and ci.yml.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
V3 = REPO_ROOT / 'deploy' / 'v3'
FAKES = Path(__file__).resolve().parent / 'deploy_v3_fakes'
BRANCH = 'mrk-101-ubuntu-production'
API_URL = 'https://hub.example.test:8443'

pytestmark = pytest.mark.skipif(shutil.which('git') is None or shutil.which('flock') is None, reason='needs git')


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check, capture_output=True, text=True)


def image_id(seed):
    return 'sha256:' + hashlib.sha256(seed.encode()).hexdigest()


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.fake = tmp / 'fake'
        self.bin = tmp / 'bin'
        self.trusted = tmp / 'trusted'
        self.state = tmp / 'state'
        self.releases = tmp / 'releases'
        self.backups = tmp / 'backups'
        self.origin = tmp / 'origin.git'
        self.work = tmp / 'work'
        self.root = tmp / 'root'
        for d in (self.fake, self.bin, self.trusted, self.releases, self.backups / 'runs'):
            d.mkdir(parents=True)
        # pytest's tmp_path inherits the host umask (often 0002), while the
        # production trusted directory is installed root-owned, non-writable
        # by group/other. Model that secure baseline explicitly.
        self.trusted.chmod(0o755)
        self.state.mkdir(mode=0o700)
        for name in ('docker', 'curl', 'gh'):
            shutil.copy(FAKES / name, self.bin / name)
            (self.bin / name).chmod(0o755)
        for f in (V3 / 'mrk108').iterdir():
            destination = self.trusted / f.name
            shutil.copy(f, destination)
            destination.chmod(0o644)
        shutil.copy(REPO_ROOT / 'deploy' / 'scripts' / 'check-ci.sh', self.trusted / 'check-ci.sh')
        (self.trusted / 'check-ci.sh').chmod(0o755)
        self.transaction = tmp / 'deploy-transaction-v3.sh'
        self.updater = tmp / 'auto-update-v3.sh'
        shutil.copy(V3 / 'lib' / 'deploy-transaction-v3.sh', self.transaction)
        shutil.copy(V3 / 'lib' / 'auto-update-v3.sh', self.updater)
        self.transaction.chmod(0o755)
        self.updater.chmod(0o755)
        self.env_file = tmp / 'backend.env'
        self.env_file.write_text('DATABASE_URL=postgresql://user:secret@db/x\n')
        self.git_env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                        'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        self.env = {**self.git_env, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'FAKE_DIR': str(self.fake),
                    'DEPLOY_ROOT': str(self.root), 'DEPLOY_TRUSTED': str(self.trusted),
                    'DEPLOY_STATE_DIR': str(self.state), 'DEPLOY_RELEASES': str(self.releases),
                    'DEPLOY_BACKUP_ROOT': str(self.backups), 'DEPLOY_BACKEND_ENV_FILE': str(self.env_file),
                    'DEPLOY_NEXT_PUBLIC_API_URL': API_URL, 'DEPLOY_REQUIRED_UID': str(os.getuid()),
                    'DEPLOY_GIT_USER': '', 'DEPLOY_TRANSACTION': str(self.transaction),
                    'DEPLOY_HEALTH_TRIES': '2', 'DEPLOY_HEALTH_SLEEP': '0'}

        run('git', 'init', '-q', '--bare', '-b', BRANCH, str(self.origin), env=self.git_env)
        run('git', 'clone', '-q', str(self.origin), str(self.work), env=self.git_env)
        for sub in ('backend', 'frontend'):
            (self.work / sub).mkdir()
            (self.work / sub / 'Dockerfile').write_text(f'FROM scratch\n# {sub}\n')
            (self.work / sub / '.dockerignore').write_text('.env*\n')
        (self.work / 'backend' / 'ALEMBIC_HEAD').write_text('0028_school_progress\n')
        self.a = self.commit('A')
        run('git', 'clone', '-q', '-b', BRANCH, str(self.origin), str(self.root), env=self.git_env)
        self.deploy_running(self.a)
        self.fresh_backup()
        self.ci_success(self.a)

    # ---------- setup helpers ----------

    def commit(self, name, head=None):
        (self.work / 'app.txt').write_text(name)
        if head:
            (self.work / 'backend' / 'ALEMBIC_HEAD').write_text(head + '\n')
        run('git', 'add', '-A', cwd=self.work, env=self.git_env)
        run('git', 'commit', '-q', '-m', name, cwd=self.work, env=self.git_env)
        run('git', 'push', '-q', 'origin', f'HEAD:{BRANCH}', cwd=self.work, env=self.git_env)
        return run('git', 'rev-parse', 'HEAD', cwd=self.work, env=self.git_env).stdout.strip()

    def deploy_running(self, sha):
        """Production as the previous deployment left it: images tagged by SHA, containers with matching config hash."""
        def h(service, ref, env):
            resolved = {'image': ref, 'environment': env}
            return hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest()
        b, f = image_id('backend-' + sha), image_id('frontend-' + sha)
        state = {
            'tags': {f'standa-hub-backend:{sha}': b, f'standa-hub-frontend:{sha}': f},
            'meta': {b: {'revision': sha, 'head': '0028_school_progress'}, f: {'revision': sha, 'head': '-'}},
            'containers': {
                'standa-hub-backend': {'image_ref': f'standa-hub-backend:{sha}', 'image_id': b, 'app_commit': sha,
                                       'running': True, 'project': 'backend', 'service': 'backend',
                                       'hash': h('backend', f'standa-hub-backend:{sha}', {'APP_COMMIT': sha})},
                'standa-hub-frontend': {'image_ref': f'standa-hub-frontend:{sha}', 'image_id': f, 'app_commit': '',
                                        'running': True, 'project': 'frontend', 'service': 'frontend',
                                        'hash': h('frontend', f'standa-hub-frontend:{sha}', {'NEXT_PUBLIC_API_URL': API_URL})}},
            'unhealthy': [],
        }
        (self.fake / 'state.json').write_text(json.dumps(state))

    def fresh_backup(self):
        dump = self.backups / 'db.dump'
        dump.write_bytes(b'dump')
        (self.backups / 'runs' / 'backup_1.json').write_text(json.dumps({'status': 'success', 'database': {
            'filename': 'db.dump', 'size': 4, 'sha256': hashlib.sha256(b'dump').hexdigest()}}))

    def ci_success(self, *shas, branch=BRANCH, status='completed', conclusion='success', path='.github/workflows/ci.yml'):
        runs = self.ci_runs()
        for i, sha in enumerate(shas):
            runs.append({'id': len(runs) + 1 + i, 'head_sha': sha, 'head_branch': branch, 'event': 'push',
                         'path': path, 'status': status, 'conclusion': conclusion,
                         'created_at': f'2026-11-12T10:{len(runs) + i:02d}:00Z'})
        (self.fake / 'ci_runs.json').write_text(json.dumps({'workflow_runs': runs}))

    def ci_runs(self):
        p = self.fake / 'ci_runs.json'
        return json.loads(p.read_text())['workflow_runs'] if p.exists() else []

    def inject(self, **kw):
        (self.fake / 'inject.json').write_text(json.dumps(kw))

    def state_json(self):
        return json.loads((self.fake / 'state.json').read_text())

    def mutate(self, fn):
        s = self.state_json()
        fn(s)
        (self.fake / 'state.json').write_text(json.dumps(s))

    # ---------- running the scripts (fd 9 = the maintenance lock, as with-deployment-lock.sh provides) ----------

    def _locked(self, *argv, extra=None):
        lock = self.tmp / 'maintenance.lock'
        return subprocess.run(['bash', '-c', 'exec 9>"$0"; flock -n 9; exec "$@"', str(lock), 'bash', *argv],
                              cwd=self.root, env={**self.env, **(extra or {})}, capture_output=True, text=True)

    def update(self, mode='--apply', **extra):
        return self._locked(str(self.updater), mode, extra=extra)

    def tx(self, mode, sha, **extra):
        return self._locked(str(self.transaction), mode, sha, extra=extra)

    # ---------- observations ----------

    def running(self):
        c = self.state_json()['containers']
        return c['standa-hub-backend']['image_id'], c['standa-hub-frontend']['image_id']

    def running_commit(self):
        return self.state_json()['containers']['standa-hub-backend']['app_commit']

    def journal(self, sha, suffix=''):
        return json.loads((self.state / f'transaction-v3-{sha}{suffix}' / 'journal.json').read_text())

    def transactions(self):
        return sorted(p.name for p in self.state.iterdir() if p.name != 'provenance')


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def out(r):
    return r.stdout + r.stderr


# ---------- happy path and preflight ----------

def test_update_deploys_new_commit_with_provenance_and_journal(w):
    b = w.commit('B')
    w.ci_success(b)
    r = w.update()
    assert r.returncode == 0, out(r)
    assert 'AUTO_UPDATE_DEPLOYED' in r.stdout and 'TARGET_IMAGE_PROVENANCE_VERIFIED' in r.stdout
    assert w.running_commit() == b
    j = w.journal(b)
    assert j['state'] == 'deployed'
    assert w.running() == (j['target']['backend']['image_id'], j['target']['frontend']['image_id'])
    prov = json.loads((w.state / 'provenance' / f'{b}.json').read_text())
    assert prov['images']['backend']['image_id'] == j['target']['backend']['image_id']
    assert oct((w.state / 'provenance' / f'{b}.json').stat().st_mode & 0o777) == '0o600'
    assert not list(w.state.glob('.staging-v3-*')), 'staging published by rename'
    # next run: nothing to do
    again = w.update()
    assert again.returncode == 0 and 'NO_UPDATE_NEEDED' in again.stdout, out(again)


def test_check_mode_changes_no_container(w):
    b = w.commit('B')
    w.ci_success(b)
    before = w.running()
    r = w.update('--check')
    assert r.returncode == 0 and 'UPDATE_READY_CHECK_ONLY' in r.stdout, out(r)
    assert w.running() == before and w.transactions() == []


def test_placeholder_api_url_is_refused(w):
    r = w.update(DEPLOY_NEXT_PUBLIC_API_URL='https://<tailnet-host>:8443')
    assert r.returncode == 1 and 'NEXT_PUBLIC_API_URL_NOT_CONFIGURED' in out(r)


def test_migration_head_change_blocks_automatic_deploy(w):
    b = w.commit('B', head='0029_attendance_schedule')
    w.ci_success(b)
    before = w.running()
    r = w.update()
    assert r.returncode != 0 and 'MIGRATION_HEAD_CHANGED' in out(r)
    assert w.running() == before and w.transactions() == []


# ---------- failures after "deploying": automatic rollback ----------

def test_unhealthy_backend_rolls_back_to_previous_image_ids(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    w.update('--check')  # builds the images; mark the new backend unhealthy
    w.mutate(lambda s: s['unhealthy'].append(s['tags'][f'standa-hub-backend:{b}']))
    r = w.update()
    assert r.returncode != 0 and 'ROLLBACK_VERIFIED' in out(r), out(r)
    assert w.running() == old and w.running_commit() == w.a
    assert w.journal(b)['state'] == 'rolled_back'
    # the failed target is not retried automatically; other updates are not blocked by a terminal state
    again = w.update()
    assert again.returncode != 0 and 'TRANSACTION_ALREADY_EXISTS' in out(again)


def test_after_rollback_the_next_commit_deploys_without_compose_drift(w):
    """The audited rollback (snapshot + pull_policy override) changed the config-hash -> *_COMPOSE_DRIFT forever."""
    b = w.commit('B')
    w.ci_success(b)
    w.update('--check')
    w.mutate(lambda s: s['unhealthy'].append(s['tags'][f'standa-hub-backend:{b}']))
    assert w.update().returncode != 0 and w.journal(b)['state'] == 'rolled_back'
    (w.work / 'backend' / 'Dockerfile').write_text('FROM scratch\n# backend, fixed\n')
    c = w.commit('C fixes B')
    w.ci_success(c)
    r = w.update()
    assert r.returncode == 0 and 'COMPOSE_HASHES_MATCH_RUNNING' in r.stdout, out(r)
    assert w.running_commit() == c


def test_rollback_stops_when_managed_config_no_longer_matches_snapshot(w):
    b = w.commit('B')
    w.ci_success(b)
    w.inject(kill_on_up=['backend'])
    w.update()
    snap = w.state / f'transaction-v3-{b}' / 'backend.json'
    data = json.loads(snap.read_text())
    data['services']['backend']['environment']['APP_COMMIT'] = '0' * 40
    snap.write_text(json.dumps(data))
    rec = w.tx('--recover', b)
    assert rec.returncode != 0 and 'MANAGED_CONFIG_CHANGED_SINCE_SNAPSHOT' in out(rec)
    assert w.journal(b)['state'] == 'rollback_required'


def test_frontend_start_failure_rolls_back_both(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    w.inject(fail_up=['frontend'])
    r = w.update()
    assert r.returncode != 0
    # rollback recreates the frontend too, so allow it this time
    assert w.journal(b)['state'] in ('rolled_back', 'rollback_required')
    if w.journal(b)['state'] == 'rollback_required':
        w.inject()
        rec = w.tx('--recover', b)
        assert rec.returncode == 0, out(rec)
    assert w.running() == old and w.journal(b)['state'] == 'rolled_back'


# ---------- interruptions (SIGKILL = power loss) and --recover ----------

def test_power_loss_while_deploying_blocks_updates_until_recover(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    w.inject(kill_on_up=['backend'])
    r = w.update()
    assert r.returncode != 0
    assert w.journal(b)['state'] == 'deploying'
    blocked = w.update()
    assert blocked.returncode != 0 and 'PENDING_TRANSACTION' in out(blocked)
    rec = w.tx('--recover', b)
    assert rec.returncode == 0 and 'ROLLBACK_VERIFIED' in rec.stdout, out(rec)
    assert w.running() == old and w.journal(b)['state'] == 'rolled_back'


def test_interrupted_rollback_can_be_recovered_again(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    w.inject(kill_on_up=['backend'])
    w.update()
    w.inject(kill_on_up=['backend'])          # power loss again, during the rollback
    first = w.tx('--recover', b)
    assert first.returncode != 0
    assert w.journal(b)['state'] == 'rollback_required'
    second = w.tx('--recover', b)
    assert second.returncode == 0 and 'ROLLBACK_VERIFIED' in second.stdout, out(second)
    assert w.running() == old and w.journal(b)['state'] == 'rolled_back'
    assert 'NOT_RECOVERABLE' in out(w.tx('--recover', b)), 'a finished transaction is not recovered twice'


def _journal_wrapper(w, behaviour):
    """Replace the journal helper so the transition to "deploying" fails ('fail') or loses power ('kill')."""
    real = w.trusted / 'deployment-journal.real.py'
    shutil.move(w.trusted / 'deployment-journal.py', real)
    (w.trusted / 'deployment-journal.py').write_text(f'''import os, signal, subprocess, sys
if sys.argv[2] == "deploying":
    if {behaviour!r} == "kill":
        os.kill(os.getppid(), signal.SIGKILL)
    sys.exit("SIMULATED_FAILURE")
sys.exit(subprocess.call([sys.executable, "-I", {str(real)!r}, *sys.argv[1:]]))
''')


def test_failure_in_prepared_aborts_without_touching_production_and_allows_retry(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    _journal_wrapper(w, 'fail')
    r = w.update()
    assert r.returncode != 0 and 'TRANSACTION_ABORTED_NO_PRODUCTION_CHANGE' in out(r), out(r)
    assert w.running() == old
    aborted = [n for n in w.transactions() if n.startswith(f'transaction-v3-{b}.aborted-')]
    assert len(aborted) == 1 and json.loads((w.state / aborted[0] / 'journal.json').read_text())['state'] == 'aborted'
    shutil.move(w.trusted / 'deployment-journal.real.py', w.trusted / 'deployment-journal.py')
    (w.trusted / 'deployment-journal.py').chmod(0o644)
    retry = w.update()
    assert retry.returncode == 0 and w.running_commit() == b, out(retry)


def test_power_loss_in_prepared_is_recovered_as_aborted(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    _journal_wrapper(w, 'kill')
    w.update()
    shutil.move(w.trusted / 'deployment-journal.real.py', w.trusted / 'deployment-journal.py')
    (w.trusted / 'deployment-journal.py').chmod(0o644)
    assert w.journal(b)['state'] == 'prepared'
    assert 'PENDING_TRANSACTION' in out(w.update())
    rec = w.tx('--recover', b)
    assert rec.returncode == 0 and 'TRANSACTION_ABORTED_NO_PRODUCTION_CHANGE' in rec.stdout, out(rec)
    assert w.running() == old
    assert w.update().returncode == 0 and w.running_commit() == b


def test_prepared_with_changed_containers_needs_manual_recovery(w):
    b = w.commit('B')
    w.ci_success(b)
    _journal_wrapper(w, 'kill')
    w.update()
    shutil.move(w.trusted / 'deployment-journal.real.py', w.trusted / 'deployment-journal.py')
    (w.trusted / 'deployment-journal.py').chmod(0o644)
    w.mutate(lambda s: s['containers']['standa-hub-backend'].update(image_id=image_id('someone-else')))
    rec = w.tx('--recover', b)
    assert rec.returncode != 0 and 'MANUAL_RECOVERY_REQUIRED' in out(rec)
    assert w.journal(b)['state'] == 'prepared'


def test_incomplete_directory_from_old_script_is_removed_by_recover_only(w):
    b = w.commit('B')
    w.ci_success(b)
    legacy = w.state / f'transaction-v3-{b}'
    legacy.mkdir(mode=0o700)
    (legacy / 'backend.json').write_text('{"secret": "x"}')
    other = w.commit('C')
    w.ci_success(other)
    blocked = w.update()
    assert blocked.returncode != 0 and 'INCOMPLETE_TRANSACTION_DIRECTORY' in out(blocked)
    rec = w.tx('--recover', b)
    assert rec.returncode == 0 and 'INCOMPLETE_TRANSACTION_REMOVED_NO_PRODUCTION_CHANGE' in rec.stdout, out(rec)
    assert not legacy.exists()
    assert w.update().returncode == 0 and w.running_commit() == other


def test_stale_staging_directory_is_reported_by_check_and_removed_by_apply(w):
    stale = w.state / '.staging-v3-deadbeef.XXXX'
    stale.mkdir(mode=0o700)
    (stale / 'backend.json').write_text('{"secret": "x"}')
    b = w.commit('B')
    w.ci_success(b)
    chk = w.update('--check')
    assert 'STALE_STAGING_DIRECTORIES: 1' in chk.stdout and stale.exists(), out(chk)
    r = w.update()
    assert r.returncode == 0 and 'STALE_STAGING_REMOVED' in r.stdout, out(r)
    assert not stale.exists()


# ---------- image provenance ----------

def test_retagged_target_image_with_right_label_is_refused(w):
    b = w.commit('B')
    w.ci_success(b)
    assert w.update('--check').returncode == 0
    forged = image_id('forged')

    def retag(s):
        s['meta'][forged] = {'revision': b, 'head': '0028_school_progress'}
        s['tags'][f'standa-hub-backend:{b}'] = forged
    w.mutate(retag)
    before = w.running()
    r = w.tx('--apply', b)
    assert r.returncode != 0 and 'TARGET_IMAGE_NOT_FROM_VERIFIED_BUILD' in out(r)
    assert w.running() == before and w.transactions() == []


def test_missing_provenance_is_refused(w):
    b = w.commit('B')
    w.ci_success(b)
    w.update('--check')
    (w.state / 'provenance' / f'{b}.json').unlink()
    r = w.tx('--apply', b)
    assert r.returncode != 0 and 'TARGET_IMAGE_PROVENANCE_MISSING' in out(r)


def test_update_rebuilds_even_when_target_tag_already_exists(w):
    b = w.commit('B')
    w.ci_success(b)
    forged = image_id('preexisting')
    w.mutate(lambda s: (s['meta'].update({forged: {'revision': b, 'head': '0028_school_progress'}}),
                        s['tags'].update({f'standa-hub-backend:{b}': forged})))
    r = w.update()
    assert r.returncode == 0, out(r)
    assert w.running()[0] != forged


# ---------- CI gate ----------

def ci(w, sha):
    return run('bash', str(w.trusted / 'check-ci.sh'), sha, env=w.env, check=False)


def test_ci_gate_is_bound_to_sha_branch_and_workflow(w):
    b = w.commit('B')
    (w.fake / 'ci_runs.json').unlink()
    w.ci_success(b, branch='main')
    assert 'CI_NOT_FOUND' in ci(w, b).stdout, 'same SHA on another branch is no approval'
    w.ci_success(b, path='.github/workflows/review-gate.yml')
    assert 'CI_NOT_FOUND' in ci(w, b).stdout, 'another workflow is no approval'
    w.ci_success(b, status='in_progress', conclusion=None)
    assert 'CI_NOT_APPROVED' in ci(w, b).stdout
    w.ci_success(b)
    r = ci(w, b)
    assert r.returncode == 0 and 'CI_APPROVED' in r.stdout
    assert f'branch={BRANCH}' in (w.fake / 'calls.log').read_text()
    w.ci_success(b, conclusion='failure')
    assert 'CI_NOT_APPROVED: completed failure' in ci(w, b).stdout, 'the newest run decides'
    assert 'INVALID_COMMIT_SHA' in ci(w, 'HEAD').stdout


def test_update_without_ci_approval_builds_nothing(w):
    b = w.commit('B')
    r = w.update()
    assert r.returncode != 0 and 'CI_NOT_FOUND' in out(r)
    assert f'standa-hub-backend:{b}' not in w.state_json()['tags']


# ---------- journal ----------

def test_journal_transitions(w, tmp_path):
    j = tmp_path / 'j.json'
    journal = str(w.trusted / 'deployment-journal.py')

    def go(state):
        return run('python3', '-I', journal, str(j), state, check=False)
    j.write_text(json.dumps({'state': 'prepared'}))
    assert go('aborted').returncode == 0 and json.loads(j.read_text())['state'] == 'aborted'
    assert 'INVALID_TRANSITION' in go('deploying').stderr, 'aborted is terminal'
    j.write_text(json.dumps({'state': 'deploying'}))
    assert 'INVALID_TRANSITION' in go('aborted').stderr, 'after deploying only rollback'
    assert oct(j.stat().st_mode & 0o777) == '0o600'


# ---------- Codex review regressions: trust modes, crash window, Git UID ----------

@pytest.mark.parametrize('target,mode,entry', [
    ('trusted_dir', 0o777, 'UNTRUSTED_HELPER'),
    ('ci_helper', 0o666, 'UNTRUSTED_HELPER'),
    ('transaction', 0o777, 'UNTRUSTED_HELPER'),
])
def test_updater_rejects_group_or_world_writable_trusted_paths(w, target, mode, entry):
    paths = {
        'trusted_dir': w.trusted,
        'ci_helper': w.trusted / 'check-ci.sh',
        'transaction': w.transaction,
    }
    p = paths[target]
    p.chmod(mode)
    r = w.update('--check')
    assert r.returncode != 0 and entry in out(r), out(r)


@pytest.mark.parametrize('target,mode', [
    ('managed_yaml', 0o666),
    ('journal_helper', 0o775),
    ('transaction', 0o775),
    ('trusted_dir', 0o777),
])
def test_transaction_rejects_writable_trusted_inputs(w, target, mode):
    paths = {
        'managed_yaml': w.trusted / 'backend-managed.yaml',
        'journal_helper': w.trusted / 'deployment-journal.py',
        'transaction': w.transaction,
        'trusted_dir': w.trusted,
    }
    paths[target].chmod(mode)
    r = w.tx('--check', w.a)
    assert r.returncode != 0 and 'UNTRUSTED_PATH' in out(r), out(r)


def test_recover_aborted_canonical_journal_after_crash_before_rename(w):
    old = w.running()
    b = w.commit('B')
    w.ci_success(b)
    _journal_wrapper(w, 'kill')
    assert w.update().returncode != 0
    shutil.move(w.trusted / 'deployment-journal.real.py', w.trusted / 'deployment-journal.py')
    (w.trusted / 'deployment-journal.py').chmod(0o644)
    journal = w.state / f'transaction-v3-{b}' / 'journal.json'
    # Crash point: 'advance aborted' completed, 'mv -T' did not run.
    j = run('python3', '-I', str(w.trusted / 'deployment-journal.py'), str(journal), 'aborted')
    assert j.returncode == 0
    assert 'TRANSACTION_ALREADY_EXISTS' in out(w.update())
    recover = w.tx('--recover', b)
    assert recover.returncode == 0 and 'TRANSACTION_ABORTED_NO_PRODUCTION_CHANGE' in out(recover), out(recover)
    assert not journal.exists()
    assert w.running() == old
    archived = list(w.state.glob(f'transaction-v3-{b}.aborted-*'))
    assert len(archived) == 1
    assert json.loads((archived[0] / 'journal.json').read_text())['state'] == 'aborted'
    retry = w.update()
    assert retry.returncode == 0 and w.running_commit() == b, out(retry)


def test_verify_release_git_invoked_with_configured_checkout_user(w):
    # Test Git invocation boundary without requiring CI runner to be root.
    verifier = w.trusted / 'verify-release.py'
    marker = w.tmp / 'runuser-invoked.txt'
    fake = w.bin / 'runuser'
    fake.write_text('#!/usr/bin/env python3\n'
                    'import os,sys\n'
                    'with open(os.environ["RUNUSER_MARKER"],"a") as f: f.write(" ".join(sys.argv[1:4])+"\\n")\n'
                    'assert sys.argv[1:4] == ["-u","separate-git-user","--"]\n'
                    'os.execvp(sys.argv[4], sys.argv[4:])\n')
    fake.chmod(0o755)
    # Fake Git repository belongs to the CI test UID, but the verifier must
    # select a distinct configured identity through runuser, not Git as root.
    env = {**w.env, 'DEPLOY_GIT_USER': 'separate-git-user', 'RUNUSER_MARKER': str(marker)}
    # Force the entire release extraction via the normal updater first.
    b = w.commit('B')
    w.ci_success(b)
    assert w.update('--check').returncode == 0
    result = run('python3', '-I', str(verifier), b, cwd=w.tmp, env=env, check=False)
    assert result.returncode == 0, out(result)
    assert marker.exists() and '-u separate-git-user --' in marker.read_text()
