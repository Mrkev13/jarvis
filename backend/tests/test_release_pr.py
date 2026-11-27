"""MRK-113: .github/scripts/release_pr.py - controlled propagation main -> production branch (release PR).

Real git (a local bare origin with main and the production branch), fake `gh` on PATH: GitHub API answers come from
$FAKE_DIR/api.json, every call is logged. No network.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.github' / 'scripts' / 'release_pr.py'
WORKFLOW = ROOT / '.github' / 'workflows' / 'release-to-production.yml'
PROD = 'mrk-101-ubuntu-production'

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='needs git')

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, re, sys
fake = os.environ["FAKE_DIR"]
args = sys.argv[1:]
method, path = args[args.index("-X") + 1], args[args.index("-X") + 2]
body = json.load(sys.stdin) if "--input" in args else None
with open(os.path.join(fake, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"method": method, "path": path, "body": body}) + "\n")
api = json.load(open(os.path.join(fake, "api.json")))
if method == "GET" and "/actions/workflows/ci.yml/runs" in path:
    print(json.dumps({"workflow_runs": api.get("runs", [])}))
elif method == "GET" and "/pulls?" in path and "head=" in path:
    print(json.dumps(api.get("open_prs", [])))
elif method == "GET" and "/pulls?" in path:  # MRK-150: všechny otevřené PR do produkce
    print(json.dumps(api.get("all_prs", [])))
elif method == "POST" and path.endswith("/pulls"):
    print(json.dumps({"number": 77}))
elif method == "POST" and path.endswith("/labels") and "/issues/" not in path:
    if body["name"] in api.get("existing_labels", []):
        print("gh: Validation Failed (HTTP 422) already_exists", file=sys.stderr)
        sys.exit(1)
    print("{}")
else:
    print("{}")
'''


def git(*args, cwd, env):
    return subprocess.run(['git', *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


MIGRATION = '''"""x"""
revision = "{rev}"
down_revision = {down}
'''


class World:
    def __init__(self, tmp: Path):
        self.tmp, self.fake, bin_dir = tmp, tmp / 'fake', tmp / 'bin'
        self.fake.mkdir()
        bin_dir.mkdir()
        (bin_dir / 'gh').write_text(FAKE_GH)
        (bin_dir / 'gh').chmod(0o755)
        self.genv = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                     'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        self.env = {**self.genv, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'FAKE_DIR': str(self.fake),
                    'REPO': 'Mrkev13/jarvis'}
        self.origin, self.work, self.clone = tmp / 'origin.git', tmp / 'work', tmp / 'clone'
        git('init', '-q', '--bare', '-b', 'main', str(self.origin), cwd=tmp, env=self.genv)
        git('clone', '-q', str(self.origin), str(self.work), cwd=tmp, env=self.genv)
        self.write('backend/alembic/versions/0027_a.py', MIGRATION.format(rev='0027_a', down='"0026_z"'))
        self.write('backend/alembic/versions/0028_b.py', MIGRATION.format(rev='0028_b', down='"0027_a"'))
        self.write('app.txt', 'v1\n')
        self.base = self.commit('base')
        git('push', '-q', 'origin', 'HEAD:main', f'HEAD:refs/heads/{PROD}', cwd=self.work, env=self.genv)
        # production has its own commits (deploy files) that main does not have
        git('checkout', '-q', '-b', 'prod', f'origin/{PROD}', cwd=self.work, env=self.genv)
        self.write('deploy/v3/README.md', 'prod only\n')
        self.commit('MRK-108: prod-only deploy files')
        git('push', '-q', 'origin', f'HEAD:{PROD}', cwd=self.work, env=self.genv)
        git('checkout', '-q', 'main', cwd=self.work, env=self.genv)
        self.api({})

    def write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg):
        git('add', '-A', cwd=self.work, env=self.genv)
        git('commit', '-q', '-m', msg, cwd=self.work, env=self.genv)
        return git('rev-parse', 'HEAD', cwd=self.work, env=self.genv)

    def push_main(self):
        git('push', '-q', 'origin', 'HEAD:main', cwd=self.work, env=self.genv)

    def api(self, data):
        (self.fake / 'api.json').write_text(json.dumps(data))

    def ci(self, sha, status='completed', conclusion='success', branch='main', path='.github/workflows/ci.yml',
           created='2026-11-15T10:00:00Z', run_id=1, extra=None):
        runs = (extra or []) + [{'id': run_id, 'head_sha': sha, 'head_branch': branch, 'event': 'push', 'path': path,
                                 'status': status, 'conclusion': conclusion, 'created_at': created}]
        data = json.loads((self.fake / 'api.json').read_text())
        data['runs'] = data.get('runs', []) + runs
        self.api(data)

    def run(self, *args):
        if self.clone.exists():
            shutil.rmtree(self.clone)
        git('clone', '-q', str(self.origin), str(self.clone), cwd=self.tmp, env=self.genv)
        git('fetch', '-q', 'origin', 'main', PROD, cwd=self.clone, env=self.genv)
        return subprocess.run(['python3', str(SCRIPT), *args], cwd=self.clone, env=self.env, capture_output=True,
                              text=True)

    def calls(self):
        p = self.fake / 'calls.jsonl'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def remote_branch(self, name):
        out = git('ls-remote', str(self.origin), f'refs/heads/{name}', cwd=self.tmp, env=self.genv)
        return out.split()[0] if out else None


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def created_pr(w):
    return next(c for c in w.calls() if c['method'] == 'POST' and c['path'].endswith('/pulls'))['body']


def test_release_pr_pinned_to_exact_commit_with_changes_and_no_migration(w):
    w.write('app.txt', 'v2\n')
    w.commit('Merge pull request #64 from x/feature')
    w.write('app.txt', 'v3\n')
    sha = w.commit('MRK-200: direct fix')
    w.push_main()
    w.ci(sha)
    r = w.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert f'SOURCE_COMMIT={sha}' in r.stdout and 'NO_MIGRATION' in r.stdout and 'RELEASE_PR_CREATED: #77' in r.stdout
    assert w.remote_branch(f'release/main-{sha[:12]}') == sha, 'release branch = exact source commit'
    pr = created_pr(w)
    assert pr['base'] == PROD and pr['head'] == f'release/main-{sha[:12]}'
    assert pr['title'] == f'Release: main@{sha[:12]} → produkce'
    assert sha in pr['body'] and '#64' in pr['body'] and 'MRK-200: direct fix' in pr['body']
    assert 'automatický updater' in pr['body'] and 'MIGRACE' not in pr['title']
    labels = [c for c in w.calls() if c['path'].endswith('/77/labels')][0]['body']['labels']
    assert labels == ['release']
    assert not any(c['method'] in ('PUT', 'MERGE') or '/merge' in c['path'] for c in w.calls()), 'never merges'


def test_migration_release_is_labelled_and_warned(w):
    w.write('backend/alembic/versions/0029_c.py', MIGRATION.format(rev='0029_c', down='"0028_b"'))
    sha = w.commit('Merge pull request #64 from x/attendance')
    w.push_main()
    w.ci(sha)
    r = w.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'ALEMBIC_HEADS: 0028_b -> 0029_c' in r.stdout and 'MIGRATION_RELEASE' in r.stdout
    pr = created_pr(w)
    assert pr['title'].endswith('(MIGRACE)')
    assert 'vyžaduje řízený migrační deployment (MRK-114)' in pr['body'] and 'nenasadí' in pr['body']
    assert '`0028_b` → release `0029_c`' in pr['body']
    labels = [c for c in w.calls() if c['path'].endswith('/77/labels')][0]['body']['labels']
    assert labels == ['release', 'migration', 'manual-merge']


@pytest.mark.parametrize('ci', [
    None,
    {'conclusion': 'failure'},
    {'status': 'in_progress', 'conclusion': None},
    {'branch': PROD},
    {'path': '.github/workflows/review-gate.yml'},
])
def test_missing_or_failed_ci_blocks_the_propagation(w, ci):
    w.write('app.txt', 'v2\n')
    sha = w.commit('change')
    w.push_main()
    if ci is not None:
        w.ci(sha, **ci)
    r = w.run()
    assert r.returncode == 1 and 'CI_NOT_APPROVED' in r.stdout
    assert w.remote_branch(f'release/main-{sha[:12]}') is None
    assert not any(c['method'] == 'POST' for c in w.calls()), 'no PR, no labels'


def test_newest_ci_run_decides(w):
    w.write('app.txt', 'v2\n')
    sha = w.commit('change')
    w.push_main()
    w.ci(sha, created='2026-11-15T10:00:00Z', run_id=1)
    w.ci(sha, conclusion='failure', created='2026-11-15T11:00:00Z', run_id=2)
    assert 'CI_NOT_APPROVED: completed failure' in w.run().stdout


def test_already_in_production_does_nothing(w):
    r = w.run('--sha', w.base)
    assert r.returncode == 0 and 'ALREADY_IN_PRODUCTION' in r.stdout
    assert w.calls() == []


def test_commit_not_on_main_is_refused(w):
    git('checkout', '-q', '-b', 'side', cwd=w.work, env=w.genv)
    w.write('app.txt', 'side\n')
    side = w.commit('side work')
    git('push', '-q', 'origin', 'HEAD:side', cwd=w.work, env=w.genv)
    r = w.run('--sha', side)
    assert r.returncode == 1 and 'SOURCE_NOT_ON_MAIN' in r.stderr


def test_specific_older_main_commit_is_released_exactly(w):
    w.write('app.txt', 'v2\n')
    older = w.commit('older')
    w.write('app.txt', 'v3\n')
    w.commit('newer')
    w.push_main()
    w.ci(older)
    r = w.run('--sha', older)
    assert r.returncode == 0, r.stdout + r.stderr
    assert w.remote_branch(f'release/main-{older[:12]}') == older
    assert 'newer' not in created_pr(w)['body']


def test_existing_release_pr_is_updated_not_duplicated(w):
    w.write('app.txt', 'v2\n')
    sha = w.commit('change')
    w.push_main()
    w.ci(sha)
    assert w.run().returncode == 0
    data = json.loads((w.fake / 'api.json').read_text())
    data['open_prs'] = [{'number': 77}]
    data['existing_labels'] = ['release']
    w.api(data)
    (w.fake / 'calls.jsonl').unlink()
    r = w.run()
    assert r.returncode == 0 and 'RELEASE_PR_UPDATED: #77' in r.stdout, r.stdout + r.stderr
    assert not any(c['method'] == 'POST' and c['path'].endswith('/pulls') for c in w.calls())


def test_moved_release_branch_is_refused(w):
    w.write('app.txt', 'v2\n')
    sha = w.commit('change')
    w.push_main()
    w.ci(sha)
    git('push', '-q', 'origin', f'{w.base}:refs/heads/release/main-{sha[:12]}', cwd=w.work, env=w.genv)
    r = w.run()
    assert r.returncode == 1 and 'RELEASE_BRANCH_MOVED' in r.stderr


def test_merge_conflicts_are_reported_in_the_pr(w):
    w.write('deploy/v3/README.md', 'main changed it too\n')
    sha = w.commit('conflicting docs')
    w.push_main()
    w.ci(sha)
    r = w.run()
    assert r.returncode == 0 and 'MERGE_CONFLICTS: 1' in r.stdout, r.stdout + r.stderr
    assert '`deploy/v3/README.md`' in created_pr(w)['body']


def test_dry_run_pushes_and_creates_nothing(w):
    w.write('app.txt', 'v2\n')
    sha = w.commit('change')
    w.push_main()
    w.ci(sha)
    r = w.run('--dry-run')
    assert r.returncode == 0 and 'DRY_RUN: Release:' in r.stdout
    assert w.remote_branch(f'release/main-{sha[:12]}') is None
    assert [c['method'] for c in w.calls()] == ['GET']


def test_older_release_prs_are_superseded_newer_and_manual_ones_kept(w):
    """MRK-150: nový release zavře starší otevřené release PR (jejich commit obsahuje), nic jiného."""
    w.write('app.txt', 'v2\n')
    old = w.commit('first change')
    w.write('app.txt', 'v3\n')
    sha = w.commit('second change')
    w.write('app.txt', 'v4\n')
    newer = w.commit('third change (not released yet)')
    git('push', '-q', 'origin', f'{sha}:main', cwd=w.work, env=w.genv)
    w.ci(sha)
    data = json.loads((w.fake / 'api.json').read_text())
    data['all_prs'] = [
        {'number': 70, 'head': {'ref': f'release/main-{old[:12]}', 'sha': old}},       # starší → zavřít
        {'number': 71, 'head': {'ref': 'stanislavpetr06/mrk-1-x', 'sha': old}},       # ruční PR → nechat
        {'number': 72, 'head': {'ref': f'release/main-{newer[:12]}', 'sha': newer}},   # novější → nechat
        {'number': 77, 'head': {'ref': f'release/main-{sha[:12]}', 'sha': sha}},       # sám sebe → nechat
    ]
    w.api(data)
    r = w.run()
    assert r.returncode == 0 and 'RELEASE_PR_SUPERSEDED: #70' in r.stdout, r.stdout + r.stderr
    closed = [c['path'] for c in w.calls() if c['method'] == 'PATCH' and c['body'] == {'state': 'closed'}]
    assert closed == ['repos/Mrkev13/jarvis/pulls/70']
    comment = next(c for c in w.calls() if c['path'].endswith('/issues/70/comments'))
    assert '#77' in comment['body']['body']
    assert not any('/merge' in c['path'] for c in w.calls())


def test_workflow_runs_after_green_ci_on_main_and_never_merges():
    text = WORKFLOW.read_text()
    triggers = text.split('jobs:')[0]
    assert 'workflow_dispatch:' in text and 'pull_request' not in triggers.replace('pull-requests', '')
    assert 'workflow_run:' in triggers and 'workflows: [CI]' in triggers and 'branches: [main]' in triggers
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.event == 'push'" in text
    assert "github.ref != 'refs/heads/main'" in text
    assert '${{ inputs.sha }}' not in text.split('run:')[-1], 'input only via env (no script injection)'
    script = SCRIPT.read_text()
    assert '/merge' not in script and '"PUT"' not in script, 'the script never calls the merge API'
