"""MRK-90: static guards for scripts/windows/heartbeat.ps1 (no PowerShell in CI; Windows behaviour is verified locally)."""
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'windows' / 'heartbeat.ps1'
TEXT = SCRIPT.read_text(encoding='utf-8')
CODE = [line for line in TEXT.splitlines() if not line.lstrip().startswith('#')]


def url_pattern():
    match = re.search(r"\$url -notmatch '([^']+)'", TEXT)
    assert match, 'ping URL is validated'
    return re.compile(match.group(1), re.IGNORECASE)  # PowerShell -match is case-insensitive


@pytest.mark.parametrize('url,ok', [
    ('https://hc-ping.com/0f4b1c2e-1111-4222-8333-444455556666', True),
    ('https://hc-ping.com/0f4b1c2e-1111-4222-8333-444455556666/', True),
    ('http://hc-ping.com/0f4b1c2e', False),          # never plain http
    ('https://hc-ping.com/', False),                  # no check id
    ('https://hc-ping.com', False),
    ('', False),
    ('hc-ping.com/abc', False),
    ('https://hc-ping.com/abc def', False),
])
def test_only_https_ping_urls_with_a_check_id_are_used(url, ok):
    assert bool(url_pattern().match(url)) is ok


def test_ping_url_never_reaches_output_or_task_arguments():
    printed = [m.group(1) for line in CODE for m in re.finditer(r'(?:Write-Output|WriteLine)\s*\(?(.*)', line)]
    assert printed
    for text in printed:
        assert '$url' not in text and '$target' not in text, text
    assert 'Write-Host' not in TEXT and 'Write-Verbose' not in TEXT
    task_args = next(line for line in CODE if '$taskArgs =' in line)
    assert '-Mode Ping -Directory' in task_args and 'url' not in task_args.lower()
    assert "$url = $null; $target = $null" in TEXT, 'secret dropped after sending'
    assert '$_.Exception.GetType().Name' in TEXT and '$_.Exception.Message' not in TEXT, 'errors never echo the URL'


def test_up_only_when_backend_and_frontend_serve_down_pings_fail():
    assert "$health.status -notin @('healthy', 'degraded')" in TEXT, 'degraded is reachable; unhealthy is down'
    assert "'/login'" in TEXT and '$page.StatusCode -eq 200' in TEXT
    assert "$target = if ($serves) { $url } else { $url + '/fail' }" in TEXT
    assert "[string]$BackendUrl = 'http://127.0.0.1:8000'" in TEXT and "[string]$FrontendUrl = 'http://127.0.0.1:3000'" in TEXT


def test_secret_file_is_admin_and_system_only_and_never_overwritten():
    sids = set(re.findall(r"'(S-1-5-[0-9-]+)'", TEXT))
    assert sids == {'S-1-5-18', 'S-1-5-32-544'}
    assert 'SetAccessRuleProtection($true, $false)' in TEXT
    assert "if (-not (Test-Path -LiteralPath $file)) {" in TEXT, 'Prepare keeps an existing URL'


def test_task_runs_as_system_every_five_minutes_without_overlap():
    assert "New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount" in TEXT
    assert '-RepetitionInterval (New-TimeSpan -Minutes 5)' in TEXT
    assert '-MultipleInstances IgnoreNew' in TEXT and '-ExecutionTimeLimit (New-TimeSpan -Minutes 2)' in TEXT
    assert "$TaskName = 'StandaHub-Heartbeat'" in TEXT
    # Check must not report ready for a registered but disabled task (review on PR #41).
    assert "$state.task_enabled = [bool]$task -and ($task.State -ne 'Disabled')" in TEXT


def test_planned_maintenance_reports_up_only_until_a_near_expiry():
    # MRK-92: update.ps1 marks a planned outage; an expired, far-future or unreadable marker is ignored.
    assert "$serves = $maintenance -or (Test-HubServes)" in TEXT
    assert "Join-Path $Dir 'maintenance-until.txt'" in TEXT and 'Test-Maintenance $Directory' in TEXT
    assert "($until -gt $now) -and (($until - $now).TotalHours -le 2)" in TEXT
    assert '} catch { return $false }' in TEXT, 'unparsable marker = no maintenance'
    assert "if ($maintenance) { 'maintenance' }" in TEXT
