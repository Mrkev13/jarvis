"""MRK-93: `-Mode Check` of the Windows scripts must report `ready: False` when any check is False.

Regression: `-not ($state.Values | Where-Object { $_ -eq $false })` – Where-Object yields the value `$false` itself,
and `-not $false` is True, so a missing ping URL / restic key still printed `ready: True`. No PowerShell in CI, so
this is a static guard; the behaviour is verified locally on Windows.
"""
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts' / 'windows'


def test_every_ready_summary_uses_contains_false():
    found = 0
    for path in sorted(SCRIPTS.glob('*.ps1')):
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'Where-Object\s*\{\s*\$_\s*-eq\s*\$false\s*\}', text), path.name
        for line in (l for l in text.splitlines() if re.match(r'\s*\$ready\s*=', l)):
            found += 1
            assert '-not ($state.Values -contains $false)' in line, f'{path.name}: {line.strip()}'
    assert found >= 2, 'heartbeat.ps1 and offsite-secrets.ps1 both summarise their checks'
