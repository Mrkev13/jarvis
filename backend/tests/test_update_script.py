"""MRK-92: static guards for scripts/windows/update.ps1 (no PowerShell in CI; Windows behaviour is verified locally)."""
import re
from pathlib import Path

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
    update = section('# ---------------------------------------------------------------- update', 'catch {\n    $reason')
    order = ['Stop-Hub', 'Install-And-Build $target', 'Invoke-Migration', 'Start-Backend', 'Start-Frontend']
    positions = [update.index(step) for step in order]
    assert positions == sorted(positions)
    build = section('function Install-And-Build', 'function Get-DbRevision')
    assert [build.index(s) for s in ('git checkout', 'pip install', 'npm ci', 'frontend build')] == \
        sorted(build.index(s) for s in ('git checkout', 'pip install', 'npm ci', 'frontend build'))
    migration = section('function Invoke-Migration', 'function Set-Heartbeat')
    assert migration.index('--check') < migration.index("Invoke-Native 'migration'"), 'config check before migrating'


def test_rollback_only_when_the_schema_did_not_change():
    failure = CODE[CODE.index('catch {\n    $reason'):]
    assert '$migrated = ((Get-DbRevision) -ne $revisionBefore)' in failure, 'decided from the live revision'
    assert 'catch { $migrated = $true }' in failure, 'unknown schema state never triggers a code rollback'
    migrated_branch = failure[failure.index('if ($migrated) {'):failure.index('Rolling back to')]
    assert 'exit 3' in migrated_branch and 'Install-And-Build' not in migrated_branch, 'no downgrade after migration'
    assert 'Start-Backend' in migrated_branch, 'keep reminders and backups running'
    rollback = failure[failure.index('Rolling back to'):]
    assert 'Install-And-Build $previous' in rollback and 'exit 1' in rollback


def test_preconditions_change_nothing_and_require_a_fresh_backup():
    pre = section('# ---------------------------------------------------------------- preconditions',
                  '# ---------------------------------------------------------------- update')
    for forbidden in ('Stop-Hub', 'Stop-ScheduledTask', 'checkout', 'Install-And-Build', 'Invoke-Migration', 'Set-Heartbeat'):
        assert forbidden not in pre, forbidden
    assert "$health.backup.status -ne 'fresh'" in pre and 'if (-not $AllowStaleBackup)' in pre
    assert 'IsInRole' in pre and '--untracked-files=no' in pre and 'Wait-SchedulerIdle' in pre
    assert 'exit 2' in pre and pre.count('exit 0') == 1, 'only "already up to date" exits 0 before changing anything'


def test_heartbeat_is_resumed_on_every_path_after_pausing():
    after_pause = CODE[CODE.index('Set-Heartbeat $false'):]
    exits = re.findall(r'exit [0-9]', after_pause)
    assert exits == ['exit 0', 'exit 3', 'exit 1', 'exit 3']
    assert after_pause.count('Set-Heartbeat $true') == len(exits)


def test_no_env_values_are_read_or_printed_by_powershell():
    assert 'Get-Content' not in CODE and 'ReadAllText' not in CODE and 'Select-String' not in CODE
    assert 'DATABASE_URL' not in ' '.join(line for line in CODE.splitlines() if '$code' not in line and "'from sqlalchemy" not in line)
    assert '$_.Exception.Message' in CODE  # fixed throw texts from this script, never env content
