"""MRK-92: static guards for scripts/windows/update.ps1 (no PowerShell in CI; Windows behaviour is verified locally)."""
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'windows' / 'update.ps1'
TEXT = SCRIPT.read_text(encoding='utf-8')
CODE = '\n'.join(line for line in TEXT.splitlines() if not line.lstrip().startswith('#'))


def python_snippets():
    """Python passed with -c: `$code = '...' + '...'` joined, PowerShell '' unescaped to '."""
    snippets = []
    for block in re.findall(r"\$code = ((?:'(?:[^']|'')*'\s*\+?\s*)+)", TEXT):
        parts = re.findall(r"'((?:[^']|'')*)'", block)
        snippets.append(''.join(p.replace("''", "'") for p in parts))
    return snippets


def section(start, end):
    return TEXT[TEXT.index(start):TEXT.index(end)]


def test_python_snippets_compile_and_avoid_double_quotes():
    snippets = python_snippets()
    assert len(snippets) == 2, 'schema revision + migration'
    for src in snippets:
        compile(src, '<update.ps1>', 'exec')
        assert '"' not in src, 'Windows PowerShell 5.1 mangles embedded double quotes in native arguments'
        assert 'load_production_environment(sys.argv[1])' in src, 'env file loaded only inside Python'
    assert any("command.upgrade(Config('alembic.ini'), 'head')" in s for s in snippets)


def test_everything_that_can_fail_runs_before_the_migration():
    update = section('# ---------------------------------------------------------------- update', "[update] FAILED")
    order = ['Stop-Hub', 'Install-And-Build $target', 'Invoke-Migration', 'Start-Backend', 'Start-Frontend']
    positions = [update.index(step) for step in order]
    assert positions == sorted(positions)
    build = section('function Install-And-Build', 'function Get-DbRevision')
    assert [build.index(s) for s in ('git checkout', 'pip install', 'npm ci', 'frontend build')] == \
        sorted(build.index(s) for s in ('git checkout', 'pip install', 'npm ci', 'frontend build'))
    migration = section('function Invoke-Migration', 'function Enter-Maintenance')
    assert migration.index('--check') < migration.index("Invoke-Native 'migration'"), 'config check before migrating'


def test_rollback_only_when_the_schema_did_not_change():
    failure = CODE[CODE.index("[update] FAILED"):CODE.index('} finally {\n    Exit-Maintenance')]
    assert '$migrated = ((Get-DbRevision) -ne $revisionBefore)' in failure, 'decided from the live revision'
    assert 'catch { $migrated = $true }' in failure, 'unknown schema state never triggers a code rollback'
    migrated_branch = failure[failure.index('if ($migrated) {'):failure.index('Rolling back to')]
    assert '$exitCode = 3' in migrated_branch and 'Install-And-Build' not in migrated_branch, 'no downgrade after migration'
    assert 'Start-Backend' in migrated_branch, 'keep reminders and backups running'
    rollback = failure[failure.index('Rolling back to'):]
    assert 'Install-And-Build $previous' in rollback and '$exitCode = 1' in rollback


def test_preconditions_change_nothing_and_require_a_fresh_backup():
    pre = section('# ---------------------------------------------------------------- preconditions',
                  '# ---------------------------------------------------------------- update')
    for forbidden in ('Stop-Hub', 'Stop-ScheduledTask', 'checkout', 'Install-And-Build', 'Invoke-Migration', 'Set-Heartbeat'):
        assert forbidden not in pre, forbidden
    assert "$health.backup.status -ne 'fresh'" in pre and 'if (-not $AllowStaleBackup)' in pre
    assert 'IsInRole' in pre and '--untracked-files=no' in pre and 'Wait-SchedulerIdle' in pre
    assert 'exit 2' in pre and pre.count('exit 0') == 1, 'only "already up to date" exits 0 before changing anything'


def test_heartbeat_uses_an_expiring_maintenance_marker_never_a_disabled_task():
    # Review on PR #42: disabling the task does not stop a running instance and can strand monitoring after a crash.
    assert 'Disable-ScheduledTask' not in CODE and 'Enable-ScheduledTask' not in CODE
    assert "$MaintenanceMinutes = 45" in TEXT and '.AddMinutes($MaintenanceMinutes)' in TEXT, 'marker expires by itself'
    assert "$task.State -ne 'Running'" in TEXT, 'waits for a heartbeat run already in progress'
    pre = section('# ---------------------------------------------------------------- preconditions',
                  '# ---------------------------------------------------------------- update')
    assert pre.index('Enter-Maintenance') > pre.index('Get-DbRevision'), 'marker only once everything else is checked'
    assert 'Exit-Maintenance' in pre[pre.index('} catch {'):], 'marker removed if entering maintenance itself fails'
    update = TEXT[TEXT.index('# ---------------------------------------------------------------- update'):]
    assert update.index('} finally {\n    Exit-Maintenance\n}') < update.index('exit $exitCode')
    assert re.findall(r'exit [0-9$a-zA-Z]+', update) == ['exit $exitCode'], 'single exit after the cleanup'
    assert sorted(set(re.findall(r'\$exitCode = ([0-9])', update))) == ['0', '1', '3']


def test_refuses_to_discard_a_commit_that_is_not_in_the_target():
    pre = section('# ---------------------------------------------------------------- preconditions',
                  '# ---------------------------------------------------------------- update')
    assert 'git -C $root merge-base --is-ancestor $previous $target' in pre
    assert pre.index('--is-ancestor') < pre.index('Already up to date'), 'checked before anything else happens'


def _git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=cwd,
                          capture_output=True, text=True)


@pytest.mark.parametrize('local_commit,expected', [(False, 0), (True, 1)])
def test_is_ancestor_semantics_on_a_real_repository(tmp_path, local_commit, expected):
    """The exact check the script runs: the production commit must be reachable from the target."""
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'base')
    base = _git(tmp_path, 'rev-parse', 'HEAD').stdout.strip()
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'main moves on')
    target = _git(tmp_path, 'rev-parse', 'HEAD').stdout.strip()
    previous = base
    if local_commit:   # a hotfix committed on the production checkout, never pushed
        _git(tmp_path, 'checkout', '-q', '--detach', base)
        _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'local hotfix')
        previous = _git(tmp_path, 'rev-parse', 'HEAD').stdout.strip()
    assert _git(tmp_path, 'merge-base', '--is-ancestor', previous, target).returncode == expected


def test_bootstrap_from_a_revision_without_the_script():
    # Review on PR #42: production (f3da60e) predates update.ps1, so the first run uses a copy from origin/main.
    assert TEXT.isascii(), 'the documented `git show | Set-Content -Encoding ASCII` bootstrap must be lossless'
    assert '$PSScriptRoot' not in CODE and '$PSCommandPath' not in CODE, 'works from any location via -ProjectDirectory'
    docs = (SCRIPT.parents[2] / 'docs' / 'operations.md').read_text(encoding='utf-8')
    assert 'git -C C:\\StandaHub show origin/main:scripts/windows/update.ps1 | Set-Content -Encoding ASCII' in docs
    assert '-ProjectDirectory C:\\StandaHub' in docs


def test_no_env_values_are_read_or_printed_by_powershell():
    assert 'Get-Content' not in CODE and 'ReadAllText' not in CODE and 'Select-String' not in CODE
    assert 'DATABASE_URL' not in ' '.join(line for line in CODE.splitlines() if '$code' not in line and "'from sqlalchemy" not in line)
    assert '$_.Exception.Message' in CODE  # fixed throw texts from this script, never env content
