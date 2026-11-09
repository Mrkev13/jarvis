"""MRK-108: deploy/scripts/deploy.sh - automatic deploy after a merge to main, with backup, migrations, health check
and rollback. Real git (a local bare "origin"), fake docker / curl / backup / systemctl on PATH; no network.

The fake docker keeps images and running containers as files: an image's content is what was built into it, a
running container remembers its image and APP_COMMIT, and the fake curl answers /health from that state.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'deploy' / 'scripts' / 'deploy.sh'
UNITS = ROOT / 'deploy' / 'systemd'

FAKE_DOCKER = r'''#!/usr/bin/env bash
S="$FAKE_STATE"; echo "docker $* | APP_COMMIT=${APP_COMMIT-} | dir=$(basename "$PWD")" >>"$S/calls.log"
case "$1 $2" in
  "image inspect") [[ -f "$S/images/$3" ]]; exit ;;
  "image tag") cp "$S/images/$3" "$S/images/$4"; exit ;;
esac
[[ "$1" == compose ]] || exit 9
shift
svc="$(basename "$PWD")"
case "$1" in
  build)
    [[ "${FAIL_BUILD-}" == "$svc" ]] && { echo "build error" >&2; exit 1; }
    echo "$svc@$(git -C .. rev-parse HEAD)" >"$S/images/standa-hub-$svc:local"; exit 0 ;;
  up)
    nodeps=false; [[ " $* " == *" --no-deps "* ]] && nodeps=true
    if [[ "$svc" == backend && "$nodeps" == false ]]; then
      echo "migrate" >>"$S/calls.log"
      [[ "${FAIL_MIGRATE-}" == 1 ]] && { echo "migrate failed" >&2; exit 1; }
      git -C .. rev-parse HEAD >"$S/schema"   # the schema now matches this commit's head
    fi
    cp "$S/images/standa-hub-$svc:local" "$S/running-$svc"
    [[ "$svc" == backend ]] && echo "${APP_COMMIT-}" >"$S/running-commit"
    exit 0 ;;
esac
exit 9
'''

# /health from the fake state: a schema newer than the running code = mismatch = unhealthy (503), like health_service
FAKE_CURL = r'''#!/usr/bin/env bash
S="$FAKE_STATE"; url="${@: -1}"; echo "curl $url" >>"$S/calls.log"
[[ -n "${HEALTH_DOWN-}" ]] && exit 7
if [[ "$url" == */health ]]; then
  [[ -f "$S/running-backend" ]] || exit 7
  commit="$(cat "$S/running-commit")"; image="$(cat "$S/running-backend")"; schema="$(cat "$S/schema")"
  status=healthy; mig=current
  [[ "$image" == "backend@$schema" ]] || { status=unhealthy; mig=mismatch; }
  [[ -n "${BROKEN_COMMIT-}" && "$image" == "backend@$BROKEN_COMMIT" ]] && status=unhealthy
  printf '{"status":"%s","version":{"commit":"%s"},"migrations":{"status":"%s"}}' "$status" "$commit" "$mig"
  exit 0
fi
[[ -f "$S/running-frontend" ]] || exit 7
'''


def sh(*args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def write_exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


class World:
    def __init__(self, tmp):
        self.tmp = tmp
        self.origin = tmp / 'origin.git'
        self.work = tmp / 'work'   # where "merges to main" happen
        self.repo = tmp / 'srv'    # the server checkout
        self.state = tmp / 'fake'
        self.deploy_state = tmp / 'state'
        (self.state / 'images').mkdir(parents=True)
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        write_exe(bin_dir / 'docker', FAKE_DOCKER)
        write_exe(bin_dir / 'curl', FAKE_CURL)
        write_exe(bin_dir / 'systemctl', '#!/bin/sh\nexit 0\n')
        self.backup = tmp / 'backup.sh'
        write_exe(self.backup, '#!/bin/sh\necho backup >>"$FAKE_STATE/calls.log"\n[ -z "$FAIL_BACKUP" ]\n')
        self.git_env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                        'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        self.env = {**self.git_env, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'FAKE_STATE': str(self.state),
                    'REPO_DIR': str(self.repo), 'REPO_USER': '', 'STATE_DIR': str(self.deploy_state),
                    'BACKUP_CMD': str(self.backup), 'HEALTH_TIMEOUT': '1', 'HEALTH_INTERVAL': '0.05'}

        sh('git', 'init', '-q', '--bare', '-b', 'main', str(self.origin), env=self.git_env)
        sh('git', 'clone', '-q', str(self.origin), str(self.work), env=self.git_env)
        for d in ('backend', 'frontend'):
            (self.work / d).mkdir()
            (self.work / d / 'compose.yaml').write_text('services: {}\n')
        self.first = self.commit('initial')
        sh('git', 'clone', '-q', str(self.origin), str(self.repo), env=self.git_env)
        sh('git', 'checkout', '-q', '--detach', self.first, cwd=self.repo, env=self.git_env)
        (self.repo / 'backend' / '.env.production').write_text('DATABASE_URL=postgresql://user:sup3rsecret@db/x\n')
        (self.repo / 'frontend' / '.env').write_text('NEXT_PUBLIC_API_URL=https://hidden.example\n')
        # what runs before the first automatic deploy
        for svc in ('backend', 'frontend'):
            (self.state / 'images' / f'standa-hub-{svc}:local').write_text(f'{svc}@{self.first}\n')
            (self.state / f'running-{svc}').write_text(f'{svc}@{self.first}\n')
        (self.state / 'running-commit').write_text(self.first + '\n')
        (self.state / 'schema').write_text(self.first + '\n')

    def commit(self, name):
        (self.work / f'{name}.txt').write_text(name)
        sh('git', 'add', '-A', cwd=self.work, env=self.git_env)
        sh('git', 'commit', '-q', '-m', name, cwd=self.work, env=self.git_env)
        sh('git', 'push', '-q', 'origin', 'HEAD:main', cwd=self.work, env=self.git_env)
        return sh('git', 'rev-parse', 'HEAD', cwd=self.work, env=self.git_env)

    def run(self, mode='run', **extra):
        (self.state / 'calls.log').unlink(missing_ok=True)
        return subprocess.run(['bash', str(SCRIPT), mode], env={**self.env, **extra}, capture_output=True, text=True)

    def head(self):
        return sh('git', 'rev-parse', 'HEAD', cwd=self.repo, env=self.git_env)

    def calls(self):
        p = self.state / 'calls.log'
        return p.read_text().splitlines() if p.exists() else []

    def running(self, svc):
        return (self.state / f'running-{svc}').read_text().strip()

    def result(self):
        return (self.deploy_state / 'last-result.txt').read_text()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_nothing_new_means_no_backup_and_no_docker(world):
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert world.calls() == []
    assert 'up to date' in world.result()


def test_new_commit_is_backed_up_built_migrated_and_health_checked(world):
    target = world.commit('feature')
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    calls = world.calls()
    assert calls[0] == 'backup', 'backup before anything else'
    build = next(i for i, c in enumerate(calls) if 'compose build backend' in c)
    up = next(i for i, c in enumerate(calls) if 'compose up -d' in c and 'dir=backend' in c)
    assert build < up and calls[up + 1] == 'migrate', 'migrate runs with the backend start'
    assert f'APP_COMMIT={target}' in calls[up], '/health reports the deployed commit'
    assert world.head() == target
    assert world.running('backend') == f'backend@{target}' and world.running('frontend') == f'frontend@{target}'
    assert (world.state / 'images' / 'standa-hub-backend:previous').read_text().strip() == f'backend@{world.first}'
    assert (world.deploy_state / 'deployed').read_text().strip() == target
    assert 'deployed' in world.result() and target[:7] in world.result()
    assert any(c.endswith('/health') for c in calls) and any(c.endswith('/login') for c in calls)
    # next pass: nothing to do
    assert world.run().returncode == 0 and world.calls() == []


def test_failed_backup_stops_the_deploy_before_any_change(world):
    world.commit('feature')
    r = world.run(FAIL_BACKUP='1')
    assert r.returncode == 1
    assert world.calls() == ['backup']
    assert world.head() == world.first
    assert 'backup failed' in world.result()
    # not marked as failed: the next pass tries again once the backup works
    assert world.run().returncode == 0 and world.head() != world.first


def test_failed_build_changes_nothing_running_and_is_not_retried(world):
    target = world.commit('broken-build')
    r = world.run(FAIL_BUILD='frontend')
    assert r.returncode == 1
    assert world.head() == world.first, 'checkout back on the running commit'
    assert not any('compose up' in c for c in world.calls())
    assert world.running('backend') == f'backend@{world.first}'
    assert (world.state / 'images' / 'standa-hub-backend:local').read_text().strip() == f'backend@{world.first}', \
        'the freshly built backend image is replaced by the running one'
    assert 'build' in world.result() and target[:7] in world.result()
    again = world.run()
    assert again.returncode == 0 and world.calls() == [], 'a failed commit is not retried'
    fixed = world.commit('fix')
    assert world.run().returncode == 0 and world.head() == fixed


def test_failed_migration_rolls_back_without_running_migrate_on_old_code(world):
    world.commit('bad-migration')
    r = world.run(FAIL_MIGRATE='1')
    assert r.returncode == 1
    assert world.head() == world.first
    rollback = [c for c in world.calls() if '--no-deps' in c]
    assert rollback and 'compose up -d --no-build --no-deps backend' in rollback[0]
    assert f'APP_COMMIT={world.first}' in rollback[0]
    assert world.running('backend') == f'backend@{world.first}'
    assert 'rolled back' in world.result()


def test_unhealthy_deploy_rolls_back_and_old_code_runs_on_newer_schema(world):
    target = world.commit('unhealthy')
    r = world.run(BROKEN_COMMIT=target)
    assert r.returncode == 1, r.stdout
    assert world.head() == world.first
    assert world.running('backend') == f'backend@{world.first}' and world.running('frontend') == f'frontend@{world.first}'
    # the schema stays migrated (never downgraded) - the old code answers 503 "mismatch", the rollback still counts
    assert (world.state / 'schema').read_text().strip() == target
    assert 'rolled back' in world.result() and 'NOT healthy' not in world.result()
    assert 'Database not rolled back' in world.result()
    assert (world.deploy_state / f'failed-{target}').exists()


def test_rollback_that_does_not_come_up_says_so(world):
    world.commit('feature')
    r = world.run(HEALTH_DOWN='1')
    assert r.returncode == 1
    assert world.head() == world.first
    assert 'NOT healthy - manual action needed' in world.result()


def test_modified_checkout_is_refused(world):
    world.commit('feature')
    (world.repo / 'backend' / 'compose.yaml').write_text('services: {changed: {}}\n')
    r = world.run()
    assert r.returncode == 1
    assert world.calls() == [], 'no backup, no docker'
    assert 'modified' in world.result()


def test_rewritten_history_is_refused(world):
    sh('git', 'checkout', '-q', '--orphan', 'other', cwd=world.work, env=world.git_env)
    (world.work / 'x.txt').write_text('x')
    sh('git', 'add', '-A', cwd=world.work, env=world.git_env)
    sh('git', 'commit', '-q', '-m', 'rewritten', cwd=world.work, env=world.git_env)
    sh('git', 'push', '-q', '--force', 'origin', 'HEAD:main', cwd=world.work, env=world.git_env)
    r = world.run()
    assert r.returncode == 1
    assert world.calls() == [] and world.head() == world.first
    assert 'does not descend' in world.result()


def test_concurrent_run_is_skipped(world):
    world.commit('feature')
    world.deploy_state.mkdir()
    holder = subprocess.Popen(['flock', str(world.deploy_state / 'run.lock'), 'sleep', '5'])
    try:
        import time
        for _ in range(50):
            if subprocess.run(['flock', '-n', str(world.deploy_state / 'run.lock'), 'true']).returncode:
                break
            time.sleep(0.05)
        r = world.run()
    finally:
        holder.kill()
        holder.wait()
    assert r.returncode == 0 and 'another deploy' in r.stdout
    assert world.calls() == []


def test_check_prints_names_and_booleans_never_secrets(world):
    r = world.run('check')
    assert r.returncode == 0, r.stdout
    assert 'sup3rsecret' not in r.stdout and 'hidden.example' not in r.stdout
    lines = dict(line.split(': ', 1) for line in r.stdout.splitlines())
    for key in ('checkout_clean', 'backend_env_file', 'frontend_env_file', 'backup_script', 'timer_enabled'):
        assert lines[key] == 'true'
    assert lines['ready'] == 'true' and lines['deployed'] == world.first[:7]
    (world.repo / 'frontend' / '.env').unlink()
    r = world.run('check')
    assert r.returncode == 2 and 'frontend_env_file: false' in r.stdout


def test_health_check_requires_current_migrations_and_the_new_commit(world):
    check = lambda body, mode, want='abc1234': subprocess.run(  # noqa: E731
        ['bash', '-c', f'source <(sed -n "/^health_ok()/,/^}}/p" {SCRIPT}); health_ok {want} {mode}'],
        input=json.dumps(body), text=True).returncode
    good = {'status': 'healthy', 'version': {'commit': 'abc1234'}, 'migrations': {'status': 'current'}}
    assert check(good, 'strict') == 0
    assert check({**good, 'status': 'degraded'}, 'strict') == 0, 'a backup/scheduler warning is not a failed deploy'
    assert check({**good, 'status': 'unhealthy'}, 'strict') == 1
    assert check({**good, 'migrations': {'status': 'mismatch'}}, 'strict') == 1
    assert check({**good, 'version': {'commit': None}}, 'strict') == 1
    assert check({**good, 'status': 'unhealthy', 'migrations': {'status': 'mismatch'}}, 'loose') == 0
    assert check({**good, 'version': {'commit': 'fff0000'}}, 'loose') == 1


def test_systemd_units_run_the_installed_copy_on_a_timer():
    service = (UNITS / 'standa-hub-deploy.service').read_text()
    timer = (UNITS / 'standa-hub-deploy.timer').read_text()
    assert 'ExecStart=/usr/bin/bash /usr/local/lib/standa-hub/deploy.sh run' in service
    assert 'Type=oneshot' in service and 'After=docker.service' in service
    assert 'OnUnitInactiveSec=10min' in timer and 'Unit=standa-hub-deploy.service' in timer
    assert 'WantedBy=timers.target' in timer
    assert os.access(SCRIPT, os.X_OK)
