"""MRK-98: static guards for scripts/windows/auto-update.ps1 (no PowerShell in CI; Windows behaviour is verified locally)."""
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'windows' / 'auto-update.ps1'
TEXT = SCRIPT.read_text(encoding='utf-8')
CODE = [line for line in TEXT.splitlines() if not line.lstrip().startswith('#')]


def run_section():
    return TEXT[TEXT.index("if ($Mode -eq 'Run') {"):TEXT.index('    # Check\n')]


def test_ascii_only_like_update_ps1():
    # Windows PowerShell 5.1 reads a BOM-less script as ANSI; ASCII keeps it byte-exact everywhere.
    TEXT.encode('ascii')


@pytest.mark.parametrize('url,ok', [
    ('https://hc-ping.com/0f4b1c2e-1111-4222-8333-444455556666', True),
    ('http://hc-ping.com/0f4b1c2e', False),
    ('https://hc-ping.com/', False),
    ('', False),
])
def test_only_https_alert_urls_with_a_check_id_are_used(url, ok):
    pattern = re.search(r"\$url -notmatch '([^']+)'", TEXT).group(1)
    assert bool(re.compile(pattern, re.IGNORECASE).match(url)) is ok


def test_alert_url_and_password_never_reach_output_logs_or_task_arguments():
    printed = [m.group(1) for line in CODE for m in re.finditer(r'(?:Write-Output|WriteLine|Step|Write-Result)\s*\(?(.*)', line)]
    assert printed
    for text in printed:
        assert '$url' not in text and '$pingTarget' not in text and 'Password' not in text, text
    assert 'Write-Host' not in TEXT and 'Write-Verbose' not in TEXT
    assert '$url = $null; $pingTarget = $null' in TEXT, 'secret dropped after sending'
    task_args = next(line for line in CODE if '$taskArgs =' in line)
    assert '-Mode Run' in task_args and 'url' not in task_args.lower() and 'password' not in task_args.lower()
    # The Windows password goes only to Register-ScheduledTask (Windows stores it); nothing writes it anywhere else.
    assert TEXT.count('GetNetworkCredential().Password') == 1
    register = next(line for line in CODE if 'Register-ScheduledTask' in line)
    assert '-Password $cred.GetNetworkCredential().Password' in register and '-RunLevel Highest' in register
    assert '$cred = $null' in TEXT


def test_task_every_ten_minutes_without_overlap_as_the_current_user():
    assert "$TaskName = 'StandaHub-AutoUpdate'" in TEXT
    assert '-RepetitionInterval (New-TimeSpan -Minutes 10)' in TEXT
    # Review on PR #55: a start boundary in the past + StartWhenAvailable can deploy right at registration.
    assert '$firstStart = (Get-Date).AddMinutes(15)' in TEXT and '-Once -At $firstStart' in TEXT
    assert '(Get-Date).Date' not in TEXT
    assert '-MultipleInstances IgnoreNew' in TEXT
    assert "[System.IO.File]::Open((Join-Path $Directory 'run.lock'), 'OpenOrCreate', 'ReadWrite', 'None')" in TEXT, \
        'second run (manual + task) exits instead of deploying twice'
    assert "$state.task_enabled = [bool]$task -and ($task.State -ne 'Disabled')" in TEXT


def test_failed_commit_is_never_retried_automatically():
    run = run_section()
    # The failed-commit guard comes before update.ps1 is started.
    assert run.index("if ($failed -and $failed -eq $target) {") < run.index('Start-Process')
    guard = run[run.index("if ($failed -and $failed -eq $target) {"):run.index('$stamp =')]
    assert 'Send-Ping $false' in guard and 'exit 0' in guard and 'Start-Process' not in guard
    # exit 1 (rolled back) and 3 (failed after migration) mark the commit; 0 clears it; 2 only counts.
    outcome = run[run.index('if ($code -eq 0) {'):]
    ok = outcome[:outcome.index('} elseif ($code -eq 2) {')]
    not_started = outcome[outcome.index('} elseif ($code -eq 2) {'):outcome.index('} else {')]
    failed = outcome[outcome.index('} else {'):outcome.index('Remove-OldLogs')]
    assert "Clear-State 'failed-commit.txt'" in ok and 'Send-Ping $true' in ok
    assert "failed-commit.txt" not in not_started and 'Send-Ping ($count -lt $NotStartedAlertRuns)' in not_started
    assert "Write-State 'failed-commit.txt' $target" in failed and 'Send-Ping $false' in failed
    # Up to date (e.g. a manual update.ps1 fixed it) clears the pending failure.
    up_to_date = run[run.index('if ($target -eq $current) {'):run.index("if ($failed -and $failed -eq $target) {")]
    assert "Clear-State 'failed-commit.txt'" in up_to_date


def test_deploys_exactly_the_commit_it_evaluated_through_update_ps1():
    run = run_section()
    assert "'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{0}\" -ProjectDirectory \"{1}\" -Ref {2}' -f $updateScript, $root, $target" in run
    assert "Join-Path $root 'scripts\\windows\\update.ps1'" in run
    assert '$null = $process.Handle' in run and '$code = $process.ExitCode' in run
    # Paused = nothing deployed, but the run still reports in (no false "auto-update died" alert).
    paused = run[run.index("if (Read-State 'paused') {"):run.index('$root = (Resolve-Path')]
    assert 'Send-Ping $true' in paused and 'Start-Process' not in paused


def test_logs_are_bounded_and_git_runs_without_stderr_redirection():
    assert '$KeepLogs = 30' in TEXT and 'Select-Object -Skip $KeepLogs' in TEXT
    git = TEXT[TEXT.index('function Git-Line'):TEXT.index('function Get-Revision')]
    assert '$out = @(& git -C $root @GitArgs)' in git and '2>' not in git
    assert "if ($sha -notmatch '^[0-9a-f]{40}$')" in TEXT, 'an empty or odd rev-parse never reaches .Substring()'
    assert 'ScriptLineNumber' in TEXT
    assert "@('fetch', '--quiet', 'origin')" in TEXT
