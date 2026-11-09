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
# Plays `docker run`: records the arguments, then runs the REAL in-container script with the mounted paths; its
# stdout (the tar) goes back to the caller like a real container's stdout.
d="$FAKE_DIR"
case "$1" in
  image) exit 0 ;;
  rm) echo "rm $*" >>"$d/docker.calls"; exit 0 ;;
  run) printf '%s\0' "$@" >"$d/docker.args"; echo run >>"$d/docker.calls" ;;
  *) exit 9 ;;
esac
src="" prompt="" envfile=""
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    -v) case "$2" in *:/src:ro) src="${2%:/src:ro}" ;; *:/prompt.md:ro) prompt="${2%:/prompt.md:ro}" ;; esac; shift 2 ;;
    --env-file) envfile="$2"; shift 2 ;;
    --name|--user|--security-opt|--tmpfs|-e|--pids-limit|--memory|--cpus|--network|--cap-drop) shift 2 ;;
    *) shift ;;
  esac
done
[[ -r "$envfile" ]] || exit 7
if [[ -f "$d/evil_tar" ]]; then cat "$d/evil_tar"; exit 0; fi
box="$(mktemp -d)"; mkdir "$box/work" "$box/stage"
set -a; . "$envfile"; set +a   # the token is in the container's environment, like --env-file
SRC_DIR="$src" WORK_DIR="$box/work" STAGE_DIR="$box/stage" PROMPT_FILE="$prompt" bash "$INNER"
'''

FAKE_CLAUDE = r'''#!/usr/bin/env bash
# Runs in the container's /work (a plain file tree): records its arguments, edits files when asked.
d="$FAKE_DIR"; printf '%s\0' "$@" >"$d/claude.args"; echo call >>"$d/claude.calls"
[[ -e .git ]] && echo "has-git" >>"$d/claude.calls"
[[ -f "$d/claude_edit" ]] && echo fixed >>fix.txt
[[ -f "$d/claude_evil" ]] && { mkdir -p .github; echo x >.github/evil.yml; }
[[ -f "$d/claude_leak" ]] && echo "token: $CLAUDE_CODE_OAUTH_TOKEN" >leak.txt
[[ -f "$d/claude_big" ]] && head -c 3000000 /dev/zero >big.bin
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
    (work / 'app.py').write_text('print(1)\n')
    git('add', 'app.py', cwd=work)
    git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'pr', cwd=work)
    head = git('rev-parse', 'HEAD', cwd=work)
    origin = tmp_path / 'origin.git'
    git('clone', '-q', '--bare', str(work), str(origin), cwd=tmp_path)
    fix, review = tmp_path / 'fix', tmp_path / 'review'
    for d in (fix, review):
        git('clone', '-q', str(origin), str(d), cwd=tmp_path)
    (fake / 'prs').write_text(f'7 {head} feature\n')
    (fake / 'reviews.tsv').write_text(tsv((head, BLOCK)))
    (fake / 'claude_edit').write_text('1')
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


def file_at(env, rev, path):
    return git('show', f'{rev}:{path}', cwd=env['origin'])


def test_blocked_head_is_fixed_and_the_host_builds_and_pushes_the_commit(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    args = read(env, 'claude.args').split('\0')[:-1]
    assert args[0] == '-p' and args[args.index('--permission-mode') + 1] == 'dontAsk'
    allowed = args[args.index('--allowedTools') + 1:args.index('--disallowedTools')]
    assert allowed == ['Read', 'Edit', 'Write', 'Glob', 'Grep'], 'no shell: no code from the PR can run'
    assert 'Bash' in args[args.index('--disallowedTools') + 1:]
    prompt = args[1]
    assert 'chybí test pro prázdný vstup' in prompt and 'round 1 of 3' in prompt
    assert 'Codex-Verdict: BLOCK' not in prompt.split('REVIEW (Codex')[1], 'the verdict line itself is not passed on'
    assert 'has-git' not in read(env, 'claude.calls'), 'the container gets no .git'
    new = remote_head(env)
    assert new != env['head'] and git('rev-parse', f'{new}^', cwd=env['origin']) == env['head'], 'one commit on top'
    assert file_at(env, new, 'fix.txt') == 'fixed' and file_at(env, new, 'app.py') == 'print(1)'
    assert git('log', '-1', '--format=%an|%s', new, cwd=env['origin']).startswith('Claude (autofix)|Autofix PR #7')
    comments = read(env, 'comments.md')
    assert 'Opraveno' in comments and 'Codex-Verdict' not in comments, 'the author never writes a verdict'
    assert 'fix pushed (round 1/3)' in last_result(env)
    assert run(env).returncode == 0 and read(env, 'claude.calls').count('call') == 1, 'one attempt per commit'
    assert not list(env['state'].glob('work.*')), 'the work folder is removed afterwards'


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


def test_no_change_from_claude_means_no_push_and_needs_human(env):
    (env['fake'] / 'claude_edit').unlink()
    (env['fake'] / 'claude_answer').write_text('Nález je chybný: test už existuje (tests/test_x.py).\n')
    assert run(env).returncode == 0
    assert remote_head(env) == env['head']
    assert 'Nález je chybný' in read(env, 'comments.md')
    assert '--add-label needs-human' in read(env, 'labels') and 'nic nezměnil' in last_result(env)


def test_round_limit_stops_and_asks_standa(env):
    old = [(c * 40, BLOCK) for c in 'abc']
    (env['fake'] / 'reviews.tsv').write_text(tsv(*old, (env['head'], BLOCK)))   # 4th block
    assert run(env).returncode == 0
    assert read(env, 'claude.calls') == '', 'no 4th automatic fix'
    assert '--add-label needs-human' in read(env, 'labels') and 'limit 3' in read(env, 'comments.md')
    (env['fake'] / 'reviews.tsv').write_text(tsv(*old[:2], (env['head'], BLOCK)))   # 3rd block is still fixed
    (env['state'] / 'pr-7.txt').unlink()
    run(env)
    assert read(env, 'claude.calls').count('call') == 1 and 'round 3 of 3' in read(env, 'claude.args')


def test_someone_pushed_during_the_fix_is_not_overwritten(env):
    other = git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit-tree',
                git('rev-parse', f'{env["head"]}^{{tree}}', cwd=env['origin']), '-p', env['head'], '-m', 'human',
                cwd=env['origin'])
    (env['fake'] / 'move_remote').write_text(other)
    assert run(env).returncode == 0
    assert remote_head(env) == other, 'the human push stays'
    assert 'someone pushed during the fix' in last_result(env)


def test_claude_runs_only_in_a_locked_down_container(env):
    """Review MRK-97 P1: no PR code near the token, nothing of the host inside, every write size-limited."""
    assert run(env).returncode == 0
    args = read(env, 'docker.args').split('\0')[:-1]
    assert args[0] == 'run' and '--rm' in args and '--read-only' in args
    flag = lambda name: args[args.index(name) + 1]  # noqa: E731
    assert flag('--cap-drop') == 'ALL' and flag('--security-opt') == 'no-new-privileges'
    assert flag('--user') == f'{os.getuid()}:{os.getgid()}', 'never root in the container'
    assert flag('--env-file') == env['env']['CLAUDE_ENV_FILE'], 'only the dedicated Claude token goes in'
    assert {'--pids-limit', '--memory', '--cpus'} <= set(args)
    tmpfs = [args[i + 1] for i, a in enumerate(args) if a == '--tmpfs']
    assert {t.split(':')[0] for t in tmpfs} == {'/work', '/tmp', '/home/autofix'} and all('size=' in t for t in tmpfs)
    mounts = [args[i + 1] for i, a in enumerate(args) if a == '-v']
    assert len(mounts) == 2 and all(m.endswith(':ro') for m in mounts), 'only read-only inputs, no writable host folder'
    assert not any(env['env']['FIX_DIR'] + ':' in m for m in mounts)
    assert args[-1] == 'autofix-run'


def test_a_leaked_token_is_never_published(env):
    (env['fake'] / 'claude_edit').unlink()
    (env['fake'] / 'claude_leak').write_text('1')
    (env['fake'] / 'claude_answer').write_text('Hotovo, token je test-not-a-secret\n')
    assert run(env).returncode == 0
    assert remote_head(env) == env['head'], 'not pushed'
    assert 'test-not-a-secret' not in read(env, 'comments.md'), 'not in a comment either'
    assert '--add-label needs-human' in read(env, 'labels') and 'token' in last_result(env)
    # review MRK-97 P2: not even unreachable git objects or stored logs keep it
    objects = subprocess.run(['git', 'cat-file', '--batch-all-objects', '--batch'], cwd=env['fix'],
                             capture_output=True).stdout
    assert b'test-not-a-secret' not in objects, 'never written into the fix clone'
    for f in env['state'].rglob('*'):
        if f.is_file():
            assert b'test-not-a-secret' not in f.read_bytes(), f


def test_output_over_the_cap_is_refused(env):
    (env['fake'] / 'claude_big').write_text('1')
    env['env']['MAX_OUT_BYTES'] = '1000000'
    assert run(env).returncode == 0
    assert remote_head(env) == env['head'] and 'větší než' in last_result(env)


def test_a_tar_escaping_the_folder_is_refused(env):
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name in ('answer.md', '../escaped.txt'):
            data = b'x'
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (env['fake'] / 'evil_tar').write_bytes(buf.getvalue())
    assert run(env).returncode == 0
    assert not (env['state'] / 'escaped.txt').exists() and not list(env['state'].rglob('escaped.txt'))
    assert remote_head(env) == env['head'] and 'neplatný' in last_result(env)


def test_fix_touching_the_automation_is_never_pushed(env):
    (env['fake'] / 'claude_evil').write_text('1')
    assert run(env).returncode == 0
    assert remote_head(env) == env['head']
    assert '--add-label needs-human' in read(env, 'labels') and 'protected paths' in last_result(env)


def test_token_file_readable_by_others_stops_the_run(env):
    Path(env['env']['CLAUDE_ENV_FILE']).chmod(0o644)
    r = run(env)
    assert r.returncode == 1 and 'token file' in last_result(env)
    assert read(env, 'docker.calls') == ''


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
    for key in ('docker_installed: true', 'sandbox_image: true', 'claude_token_file: true', 'safe_unpack: true',
                'fix_clone_ready: true', 'max_rounds: 3'):
        assert key in r.stdout, r.stdout
    assert 'test-not-a-secret' not in r.stdout + r.stderr, 'names and booleans only'
    assert r.returncode == 2, 'timer not enabled in the test environment'


def test_scripts_never_merge_never_force_and_write_no_verdict():
    code = '\n'.join(line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith('#'))
    assert 'gh pr merge' not in code and 'gh pr review' not in code, 'the developer never merges or reviews'
    pushes = [line for line in code.splitlines() if 'push' in line and 'git' in line]
    assert pushes and all('--force' not in p and ' -f' not in p and '+HEAD' not in p for p in pushes), pushes
    assert 'claude -p' not in code, 'Claude never runs on the host'
    inner = INNER.read_text()
    assert '--permission-mode dontAsk' in inner and 'ALLOWED_TOOLS=(Read Edit Write Glob Grep)' in inner


def test_systemd_units_run_the_installed_copy():
    units = SCRIPT.parent / 'systemd'
    service = (units / 'standa-claude-fix.service').read_text()
    assert 'ExecStart=%h/.local/bin/standa-claude-fix run' in service
    assert 'OnUnitActiveSec=10min' in (units / 'standa-claude-fix.timer').read_text()
