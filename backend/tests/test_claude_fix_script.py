"""MRK-97: behaviour of scripts/linux/claude-fix.sh with fake `gh` and `claude` (no network, no real Claude).

A local bare repository plays GitHub's `origin` with the PR branch `feature`. The fake gh answers from files in the
test's directory and records every call. The fake docker records its arguments and runs the REAL in-container script
(scripts/linux/autofix/autofix-run.sh) in the mounted work folder with a fake claude, which records its arguments
and, when asked, commits a fix - so the bundle hand-off back to the host is exercised for real.
"""
import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'linux' / 'claude-fix.sh'
INNER = SCRIPT.parent / 'autofix' / 'autofix-run.sh'
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

FAKE_DOCKER = r'''#!/usr/bin/env bash
d="$FAKE_DIR"
case "$1" in
  image) exit 0 ;;
  rm) echo "rm $*" >>"$d/docker.calls"; exit 0 ;;
  run) printf '%s\0' "$@" >"$d/docker.args"; echo run >>"$d/docker.calls" ;;
  *) exit 9 ;;
esac
work="" out="" prompt="" envfile="" image_seen=0 args=()
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    -v) case "$2" in *:/work) work="${2%:/work}" ;; *:/out) out="${2%:/out}" ;; *:/prompt.md:ro) prompt="${2%:/prompt.md:ro}" ;; esac; shift 2 ;;
    --env-file) envfile="$2"; shift 2 ;;
    --name|--user|--security-opt|--tmpfs|-e|--pids-limit|--memory|--cpus|--network|-w|--cap-drop) shift 2 ;;
    --rm|--read-only) shift ;;
    *) args+=("$1"); shift ;;
  esac
done
# args = image autofix-run <head>
[[ -r "$envfile" ]] || exit 7
cd "$work" && OUT_DIR="$out" PROMPT_FILE="$prompt" bash "$INNER" "${args[2]}"
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
    for name, body in (('gh', FAKE_GH), ('claude', FAKE_CLAUDE), ('docker', FAKE_DOCKER)):
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
    token = tmp_path / 'claude-autofix.env'
    token.write_text('CLAUDE_CODE_OAUTH_TOKEN=test-not-a-secret\n')
    token.chmod(0o600)
    e = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'FAKE_DIR': str(fake), 'FIX_DIR': str(fix),
         'REVIEW_DIR': str(review), 'STATE_DIR': str(state), 'REPO': 'Mrkev13/jarvis', 'HOME': str(tmp_path),
         'ORIGIN': str(origin), 'INNER': str(INNER), 'CLAUDE_ENV_FILE': str(token)}
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
    for key in ('docker_installed: true', 'sandbox_image: true', 'claude_token_file: true', 'fix_clone_ready: true',
                'max_rounds: 3'):
        assert key in r.stdout, r.stdout
    assert 'test-not-a-secret' not in r.stdout + r.stderr, 'names and booleans only'
    assert r.returncode == 2, 'timer not enabled in the test environment'


def test_script_never_merges_never_forces_and_writes_no_verdict():
    code = '\n'.join(line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith('#'))
    assert 'gh pr merge' not in code and 'gh pr review' not in code, 'the developer never merges or reviews'
    pushes = [line for line in code.splitlines() if 'push' in line and 'git' in line]
    assert pushes and all('--force' not in p and ' -f' not in p and '+HEAD' not in p for p in pushes), pushes
    inner = INNER.read_text()
    assert '--permission-mode dontAsk' in inner and '"Bash(git push:*)"' in inner
    assert 'git push' not in '\n'.join(l for l in inner.splitlines() if not l.lstrip().startswith(('#', 'DENIED')))
    assert 'claude -p' not in code and '"$CLAUDE"' not in code, 'Claude never runs on the host'


def test_systemd_units_run_the_installed_copy():
    units = SCRIPT.parent / 'systemd'
    service = (units / 'standa-claude-fix.service').read_text()
    assert 'ExecStart=%h/.local/bin/standa-claude-fix run' in service
    assert 'OnUnitActiveSec=10min' in (units / 'standa-claude-fix.timer').read_text()


def docker_args(env):
    return read(env, 'docker.args').split('\0')[:-1]


def test_claude_runs_only_in_a_locked_down_container(env):
    """Review MRK-97 P1: PR code (tests, setup, npm scripts) must never run on the host with the user's logins."""
    assert run(env).returncode == 0
    args = docker_args(env)
    assert args[0] == 'run' and '--rm' in args and '--read-only' in args
    flag = lambda name: args[args.index(name) + 1]  # noqa: E731
    assert flag('--cap-drop') == 'ALL' and flag('--security-opt') == 'no-new-privileges'
    assert flag('--user') == f'{os.getuid()}:{os.getgid()}', 'never root in the container'
    assert flag('--env-file') == env['env']['CLAUDE_ENV_FILE'], 'only the dedicated Claude token goes in'
    assert {'--pids-limit', '--memory', '--cpus'} <= set(args)
    mounts = [args[i + 1] for i, a in enumerate(args) if a == '-v']
    assert len(mounts) == 3 and all(m.endswith((':/work', ':/prompt.md:ro', ':/out')) for m in mounts)
    assert not any(env['env']['FIX_DIR'] + ':' in m or str(env['tmp']) + ':' in m for m in mounts), 'no host folders'
    assert all('/work.' in m for m in mounts), 'a disposable work folder per fix'
    assert args[-2:] == ['autofix-run', env['head']]
    assert not list(env['state'].glob('work.*')), 'the work folder is removed afterwards'


def test_token_file_readable_by_others_stops_the_run(env):
    Path(env['env']['CLAUDE_ENV_FILE']).chmod(0o644)
    r = run(env)
    assert r.returncode == 1 and 'token file' in last_result(env)
    assert read(env, 'docker.calls') == ''


def test_fix_touching_the_automation_is_never_pushed(env):
    fake_claude = env['tmp'] / 'bin' / 'claude'
    fake_claude.write_text(fake_claude.read_text().replace('echo fixed >>fix.txt; git add fix.txt',
                                                            'mkdir -p .github; echo x >.github/evil.yml; git add .github'))
    assert run(env).returncode == 0
    assert remote_head(env) == env['head']
    assert '--add-label needs-human' in read(env, 'labels') and 'protected paths' in last_result(env)
