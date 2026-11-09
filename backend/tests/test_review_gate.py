"""MRK-97: static guards for the review gate workflow (no Actions run in CI). The Linux review script is exercised
for real in test_codex_review_script.py."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = (ROOT / '.github' / 'workflows' / 'review-gate.yml').read_text(encoding='utf-8')
GATE = yaml.safe_load(GATE_TEXT)
CI = yaml.safe_load((ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8'))
SCRIPT = (ROOT / 'scripts' / 'linux' / 'codex-review.sh').read_text(encoding='utf-8')
OPS = (ROOT / 'docs' / 'operations.md').read_text(encoding='utf-8')
AGENTS = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
TRIGGERS = GATE.get('on') or GATE.get(True)   # PyYAML reads the bare key `on` as True


def gate_script():
    return GATE['jobs']['gate']['steps'][0]['with']['script']


def verdict_regex():
    js = re.search(r'/(\^Codex-Verdict:[^/]+)/m\.exec', gate_script()).group(1)
    return re.compile(js, re.MULTILINE)


@pytest.mark.parametrize('body,verdict', [
    ('Bez nálezů.\n\nCodex-Verdict: MERGE', 'MERGE'),
    ('Codex-Verdict: BLOCK\n', 'BLOCK'),
    ('Codex-Verdict:   MERGE  ', 'MERGE'),
    ('Doporučení: MERGE', None),                         # prose is not a verdict
    ('text Codex-Verdict: MERGE', None),                 # must be its own line
    ('Codex-Verdict: MERGE please', None),
    ('Codex-Verdict: merge', None),
])
def test_only_a_standalone_verdict_line_counts(body, verdict):
    m = verdict_regex().search(body)
    assert (m.group(1) if m else None) == verdict
    # the poller uses the same rule before posting
    # the review script uses the same rule (POSIX ERE, case-sensitive) before posting
    ere = re.search(r"VERDICT_RE='([^']+)'", SCRIPT).group(1).replace('[[:space:]]', r'\s')
    assert bool(re.compile(ere, re.MULTILINE).search(body)) == bool(verdict)


def test_gate_trusts_only_the_owner_and_the_exact_head_commit():
    js = gate_script()
    assert 'r.commit_id === head' in js, 'a verdict on an older commit never counts'
    assert 'r.user.login === owner' in js and "r.state !== 'DISMISSED'" in js
    assert 'localeCompare' in js and 'verdicts[verdicts.length - 1]' in js, 'the newest verdict wins'
    assert js.index("core.setOutput('merge', 'true')") > js.index("if (last.m[1] !== 'MERGE')")


def test_gate_reruns_on_every_push_and_review():
    assert set(TRIGGERS['pull_request']['types']) >= {'opened', 'synchronize', 'reopened', 'labeled', 'unlabeled'}
    assert set(TRIGGERS['pull_request_review']['types']) >= {'submitted', 'edited', 'dismissed'}
    assert 'push' not in TRIGGERS


def test_least_privilege_and_no_untrusted_text_in_shell():
    assert GATE['permissions'] == {'contents': 'read', 'pull-requests': 'read'}
    merge = GATE['jobs']['auto-merge']
    assert merge['permissions'] == {'contents': 'write', 'pull-requests': 'write'}
    assert "contains(github.event.pull_request.labels.*.name, 'manual-merge')" in merge['if']
    assert '!github.event.pull_request.draft' in merge['if']
    run = merge['steps'][0]['run']
    assert '${{' not in run, 'event values reach the shell only through env'
    assert set(merge['steps'][0]['env']) == {'GH_TOKEN', 'PR', 'REPO', 'CRITICAL'}
    assert 'gh pr merge "$PR" --repo "$REPO" --auto --merge' in run
    # critical change: no auto-merge, label for Standa - before the auto-merge line
    assert run.index('--add-label manual-merge') < run.index('--auto --merge')
    assert '--disable-auto' in run
    # no PR title/body/branch name anywhere in the workflow
    for risky in ('pull_request.title', 'pull_request.body', 'review.body', 'head.ref', 'head_ref'):
        assert risky not in GATE_TEXT, risky


def test_docs_list_every_required_check_by_its_real_name():
    names = [job['name'] for job in CI['jobs'].values()] + [GATE['jobs']['gate']['name']]
    for name in names:
        assert f'`{name}`' in OPS, name
    assert 'Allow auto-merge' in OPS and 'required approvals **0**' in OPS
    assert 'Codex-Verdict: MERGE' in AGENTS and 'nikdy autor kódu' in AGENTS


def test_review_script_never_merges_and_codex_stays_read_only():
    code = [line for line in SCRIPT.splitlines() if not line.lstrip().startswith('#')]
    text = '\n'.join(code)
    assert '--sandbox read-only' in text
    assert 'gh pr merge' not in text and 'git push' not in text, 'review only; GitHub auto-merge does the merge'


def critical_rules():
    """The CRITICAL list from the gate script → [(label, compiled regex)] (JS regex syntax is Python-compatible here)."""
    block = re.search(r'const CRITICAL = \[(.*?)\];', gate_script(), re.S).group(1)
    rules = []
    for line in block.strip().splitlines():
        label, pattern, flags = re.match(r"\s*\['([^']+)', /(.*)/(i?)\],?\s*$", line).groups()
        rules.append((label, re.compile(pattern, re.I if flags else 0)))
    assert len(rules) == 4
    return rules


@pytest.mark.parametrize('path,label', [
    ('backend/alembic/versions/0028_school_progress.py', 'migrace'),
    ('backend/auth_service.py', 'přihlašování a bezpečnost'),
    ('frontend/proxy.ts', 'přihlašování a bezpečnost'),
    ('backend/backup_service.py', 'zálohy a obnova'),
    ('backend/offsite_restic.py', 'zálohy a obnova'),
    ('scripts/windows/offsite-secrets.ps1', 'zálohy a obnova'),
    ('.github/workflows/review-gate.yml', 'CI, review a deploy'),
    ('scripts/linux/claude-fix.sh', 'CI, review a deploy'),
    ('docker-compose.yml', 'CI, review a deploy'),
    ('backend/Dockerfile', 'CI, review a deploy'),
    ('backend/modules/school/progress.py', None),
    ('frontend/app/page.tsx', None),
    ('docs/backups.md', None),
    ('backend/tests/test_backup.py', None),
])
def test_critical_changes_need_a_manual_merge(path, label):
    hits = [name for name, rx in critical_rules() if rx.search(path)]
    assert (hits[0] if hits else None) == label, (path, hits)


def test_critical_areas_are_documented_for_people_and_agents():
    for label, _ in critical_rules():
        assert label in OPS, label
    assert 'needs-human' in AGENTS and 'manual-merge' in AGENTS
