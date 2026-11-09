"""MRK-97: behaviour of scripts/linux/claude-fix.sh with fake `gh` and `claude` (no network, no real Claude).

A local bare repository plays GitHub's `origin` with the PR branch `feature`. The fake gh answers from files in the
test's directory and records every call; the fake claude records its arguments and, when asked, commits a fix.
"""
import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'linux' / 'claude-fix.sh'
pytestmark = pytest.mark.skipif(shutil.which('bash') is None or shutil.which('flock') is None, reason='needs bash + flock')

FAKE_GH = r'''#!/usr/bin/env bash
d="$FAKE_DIR"; echo "$*" >>"$d/gh.calls"
case "$1 $2" in
  "auth status") exit 0 ;;
  "pr list") [[ -s "$d/prs" ]] && cat "$d/prs"; exit 0 ;;
  "pr comment") f=""; while [[ $# -gt 0 ]]; do [[ "$1" == --body-file ]] && f="$2"; shift; done
                { cat "$f"; echo "=====" ; } >>"$d/comments.md"; exit 0 ;;
  "pr edit") echo "$*" >>"$d/labels"; exit 0 ;;
esac
if [[ "$1" == api ]]; then [[ -f "$d/reviews.tsv" ]] && cat "$d/reviews.tsv"; exit 0; fi
echo "unexpected gh $*" >&2; exit 9
'''

FAKE_CLAUDE = r'''#!/usr/bin/env bash
d="$FAKE_DIR"; printf '%s\0' "$@" >"$d/claude.args"; echo call >>"$d/claude.calls"
if [[ -f "$d/claude_commit" ]]; then
  echo fixed >>fix.txt; git add fix.txt
  git -c user.email=c@c -c user.name=claude commit -q -m "MRK-1: fix review"
fi
if [[ -f "$d/move_remote" ]]; then git -C "$ORIGIN" update-ref refs/heads/feature "$(cat "$d/move_remote")"; fi
cat "$d/claude_answer" 2>/dev/null || echo "Opraveno: fix.txt. Codex-Verdict: MERGE"
exit "$(cat "$d/claude_exit" 2>/dev/null || echo 0)"
'''


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def tsv(*reviews):
    """(commit, body) pairs → the reviews_tsv() format the script reads from `gh api`."""
    return ''.join(f'{c}\t{base64.b64encode(b.encode()).decode()}\n' for c, b in reviews)


BLOCK = 'Blokující: chybí test pro prázdný vstup (backend/x.py:10).\n\nCodex-Verdict: BLOCK\n'


@pytest.fixture
def env(tmp_path):
    bin_dir, fake, state = tmp_path / 'bin', tmp_path / 'fake', tmp_path / 'state'
    for d in (bin_dir, fake):
        d.mkdir()
    for name, body in (('gh', FAKE_GH), ('claude', FAKE_CLAUDE)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    work = tmp_path / 'work'
    work.mkdir()
    git('init', '-q', '-b', 'main', cwd=work)
    git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', 'base', cwd=work)
    git('checkout', '-q', '-b', 'feature', cwd=work)
    git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', 'pr', cwd=work)
    head = git('rev-parse', 'HEAD', cwd=work)
    origin = tmp_path / 'origin.git'
    git('clone', '-q', '--bare', str(work), str(origin), cwd=tmp_path)
    fix, review = tmp_path / 'fix', tmp_path / 'review'
    for d in (fix, review):
        git('clone', '-q', str(origin), str(d), cwd=tmp_path)
    (fake / 'prs').write_text(f'7 {head} feature\n')
    (fake / 'reviews.tsv').write_text(tsv((head, BLOCK)))
    (fake / 'claude_commit').write_text('1')
    e = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'FAKE_DIR': str(fake), 'FIX_DIR': str(fix),
         'REVIEW_DIR': str(review), 'STATE_DIR': str(state), 'REPO': 'Mrkev13/jarvis', 'HOME': str(tmp_path),
         'ORIGIN': str(origin)}
    return {'env': e, 'fake': fake, 'state': state, 'head': head, 'origin': origin, 'fix': fix, 'tmp': tmp_path}


def run(env, mode='run'):
    return subprocess.run(['bash', str(SCRIPT), mode], env=env['env'], capture_output=True, text=True, timeout=60)


def remote_head(env):
    return git('rev-parse', 'refs/heads/feature', cwd=env['origin'])


def read(env, name):
    f = env['fake'] / name
    return f.read_text() if f.exists() else ''


def last_result(env):
    return (env['state'] / 'last-result.txt').read_text()


def test_blocked_head_is_fixed_by_claude_and_pushed_fast_forward(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    args = read(env, 'claude.args').split('\0')[:-1]
    assert args[0] == '-p' and '--permission-mode' in args and args[args.index('--permission-mode') + 1] == 'dontAsk'
    prompt = args[1]
    assert 'chybí test pro prázdný vstup' in prompt, 'Claude gets the concrete findings'
    assert 'Codex-Verdict: BLOCK' not in prompt.split('REVIEW (Codex')[1], 'the verdict line itself is not passed on'
    assert 'round 1 of 3' in prompt
    denied = args[args.index('--disallowedTools') + 1:]
    assert 'Bash(git push:*)' in denied and 'WebFetch' in denied
    new = remote_head(env)
    assert new != env['head'] and git('merge-base', '--is-ancestor', env['head'], new, cwd=env['origin']) == ''
    comments = read(env, 'comments.md')
    assert 'Opraveno: fix.txt.' in comments or 'Opraveno' in comments
    assert 'Codex-Verdict' not in comments, 'the author never writes a verdict'
    assert 'fix pushed (1 commit(s), round 1/3)' in last_result(env)
    # the same blocked commit is not attempted again
    assert run(env).returncode == 0
    assert read(env, 'claude.calls').count('call') == 1


@pytest.mark.parametrize('reviews', ['', 'merge'])
def test_no_verdict_or_merge_does_nothing(env, reviews):
    body = '' if reviews == '' else tsv((env['head'], 'OK\nCodex-Verdict: MERGE\n'))
    (env['fake'] / 'reviews.tsv').write_text(body)
    assert run(env).returncode == 0
    assert read(env, 'claude.calls') == '' and remote_head(env) == env['head']


def test_block_on_an_older_commit_does_not_count_for_the_head(env):
    (env['fake'] / 'reviews.tsv').write_text(tsv(('a' * 40, BLOCK)))
    run(env)
    assert read(env, 'claude.calls') == ''


def test_no_commit_from_claude_means_no_push_and_needs_human(env):
    (env['fake'] / 'claude_commit').unlink()
    (env['fake'] / 'claude_answer').write_text('Nález je chybný: test už existuje (tests/test_x.py).\n')
    assert run(env).returncode == 0
    assert remote_head(env) == env['head']
    assert 'Nález je chybný' in read(env, 'comments.md')
    assert '--add-label needs-human' in read(env, 'labels')
    assert 'labelled needs-human' in last_result(env)


def test_round_limit_stops_and_asks_standa(env):
    old = [(c * 40, BLOCK) for c in 'abc']
    (env['fake'] / 'reviews.tsv').write_text(tsv(*old, (env['head'], BLOCK)))   # 4th block
    assert run(env).returncode == 0
    assert read(env, 'claude.calls') == '', 'no 4th automatic fix'
    assert '--add-label needs-human' in read(env, 'labels')
    assert 'limit 3' in read(env, 'comments.md')
    # third block is still fixed automatically
    env2 = {**env}
    (env['fake'] / 'reviews.tsv').write_text(tsv(*old[:2], (env['head'], BLOCK)))
    (env['state'] / 'pr-7.txt').unlink()
    run(env2)
    assert read(env, 'claude.calls').count('call') == 1 and 'round 3 of 3' in read(env, 'claude.args')


def test_someone_pushed_during_the_fix_is_not_overwritten(env):
    other = git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit-tree', git('rev-parse', f'{env["head"]}^{{tree}}', cwd=env['origin']), '-p', env['head'], '-m', 'human',
                cwd=env['origin'])
    (env['fake'] / 'move_remote').write_text(other)
    assert run(env).returncode == 0
    assert remote_head(env) == other, 'the human push stays'
    assert 'someone pushed during the fix' in last_result(env)


def test_fix_clone_must_not_be_the_review_or_production_clone(env):
    env['env']['REVIEW_DIR'] = env['env']['FIX_DIR']
    r = run(env)
    assert r.returncode == 1 and 'fix clone missing or equal' in last_result(env)
    env['env']['REVIEW_DIR'] = str(env['tmp'] / 'review')
    env['env']['PRODUCTION_DIR'] = env['env']['FIX_DIR']
    assert run(env).returncode == 1
    assert read(env, 'claude.calls') == ''


def test_check_reports_names_and_booleans_only(env):
    r = run(env, 'check')
    assert 'claude_installed: true' in r.stdout and 'fix_clone_ready: true' in r.stdout and 'max_rounds: 3' in r.stdout
    assert r.returncode == 2, 'timer not enabled in the test environment'


def test_script_never_merges_never_forces_and_writes_no_verdict():
    code = '\n'.join(line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith('#'))
    assert 'gh pr merge' not in code and 'gh pr review' not in code, 'the developer never merges or reviews'
    pushes = [line for line in code.splitlines() if 'push' in line and 'git' in line]
    assert pushes and all('--force' not in p and ' -f' not in p and '+HEAD' not in p for p in pushes), pushes
    assert '--permission-mode dontAsk' in code


def test_systemd_units_run_the_installed_copy():
    units = SCRIPT.parent / 'systemd'
    service = (units / 'standa-claude-fix.service').read_text()
    assert 'ExecStart=%h/.local/bin/standa-claude-fix run' in service
    assert 'OnUnitActiveSec=10min' in (units / 'standa-claude-fix.timer').read_text()
