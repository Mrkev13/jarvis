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


def gate_step():
    return GATE['jobs']['gate']['steps'][0]


def gate_script():
    return gate_step()['with']['script']


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
    # the review script uses the same rule (POSIX ERE, case-sensitive) before posting
    ere = re.search(r"VERDICT_RE='([^']+)'", SCRIPT).group(1).replace('[[:space:]]', r'\s')
    assert bool(re.compile(ere, re.MULTILINE).search(body)) == bool(verdict)


def test_gate_runs_only_the_trusted_copy_from_the_default_branch():
    """Review MRK-97 P1: a PR must not run its own copy of the gate (pull_request would)."""
    assert set(TRIGGERS) == {'pull_request_target', 'workflow_dispatch', 'schedule'}
    assert TRIGGERS['schedule'] == [{'cron': '*/10 * * * *'}], 'periodic trusted pass catches edited / dismissed reviews'
    assert set(TRIGGERS['pull_request_target']['types']) >= {'opened', 'synchronize', 'reopened', 'labeled', 'unlabeled'}
    assert 'pull_request' not in TRIGGERS and 'pull_request_review' not in TRIGGERS
    assert 'actions/checkout' not in GATE_TEXT, 'never check out PR code with a write token'
    assert "context.eventName === 'workflow_dispatch' && context.ref !== trusted" in gate_script()


def test_least_privilege_and_no_untrusted_text_in_expressions():
    assert GATE['permissions'] == {'contents': 'read'}
    assert GATE['jobs']['gate']['permissions'] == {'contents': 'read', 'pull-requests': 'write', 'statuses': 'write'}
    assert 'enablePullRequestAutoMerge' not in GATE_TEXT, 'the gate never merges and never enables auto-merge'
    assert set(gate_step()['env']) == {'PR_INPUT'}, 'the dispatch input reaches the script only through env'
    assert 'run:' not in GATE_TEXT, 'no shell step at all'
    for risky in ('pull_request.title', 'pull_request.body', 'review.body', 'head.ref', 'head_ref'):
        assert risky not in GATE_TEXT, risky


# ---------- behaviour: the gate script run in Node against a fake GitHub API ----------

NODE_HARNESS = r"""
const fs = require('fs');
const [scriptFile, scenarioFile] = process.argv.slice(2);
const sc = JSON.parse(fs.readFileSync(scenarioFile, 'utf8'));
const out = { statuses: [], labels: [], automerge: 0, automergeOff: 0, failed: null, notices: [], evaluated: [] };
const list = (name) => async () => sc[name];
const github = {
  paginate: async (fn, args) => fn(args),
  rest: {
    pulls: { get: async (a) => { out.evaluated.push(a.pull_number); return { data: { ...sc.pr, number: a.pull_number } }; },
             list: async () => sc.open || [], listFiles: list('files'),
             listReviews: async () => { if (sc.reviewsFail) throw new Error('API down'); return sc.reviews; } },
    repos: { createCommitStatus: async (a) => { out.statuses.push([a.sha, a.state, a.context]); } },
    issues: { addLabels: async (a) => { out.labels.push(...a.labels); } },
  },
  graphql: async (q) => {
    if (q.includes('disablePullRequestAutoMerge')) { out.automergeOff += 1; return; }
    out.automerge += 1;
  },
};
const core = { setFailed: (m) => { out.failed = m; }, notice: (m) => out.notices.push(m), warning: (m) => out.notices.push(m) };
const context = { repo: { owner: 'Mrkev13', repo: 'jarvis' }, eventName: sc.event, ref: sc.ref,
  payload: { repository: { default_branch: 'main' }, ...(sc.event === 'pull_request_target' ? { pull_request: { number: 7 } } : {}) } };
process.env.PR_INPUT = sc.input || '';
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
new AsyncFunction('github', 'context', 'core', 'process', fs.readFileSync(scriptFile, 'utf8'))(github, context, core, process)
  .then(() => console.log(JSON.stringify(out)));
"""

HEAD = 'a' * 40


def run_gate(tmp_path, *, reviews=(), files=('backend/x.py',), labels=(), event='pull_request_target', ref='refs/heads/main',
             inp='', draft=False, auto_merge=None, open_prs=(), reviews_fail=False):
    import json
    import subprocess
    pr = {'number': 7, 'state': 'open', 'draft': draft, 'node_id': 'PR_x', 'head': {'sha': HEAD},
          'labels': [{'name': n} for n in labels], 'auto_merge': auto_merge}
    scenario = {'pr': pr, 'files': [{'filename': f} for f in files], 'reviews': list(reviews), 'event': event,
                'ref': ref, 'input': inp, 'reviewsFail': reviews_fail,
                'open': [{'number': n} for n in open_prs]}
    (tmp_path / 'gate.js').write_text(gate_script())
    (tmp_path / 'scenario.json').write_text(json.dumps(scenario))
    (tmp_path / 'harness.js').write_text(NODE_HARNESS)
    r = subprocess.run(['node', str(tmp_path / 'harness.js'), str(tmp_path / 'gate.js'), str(tmp_path / 'scenario.json')],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def review(body, login='Mrkev13', commit=HEAD, state='COMMENTED', at='2026-11-09T10:00:00Z'):
    return {'body': body, 'user': {'login': login}, 'commit_id': commit, 'state': state, 'submitted_at': at}


MERGE, BLOCK = 'ok\nCodex-Verdict: MERGE', 'no\nCodex-Verdict: BLOCK'
needs_node = pytest.mark.skipif(__import__('shutil').which('node') is None, reason='needs node')


def final(out):
    """The status a PR ends with (every pass first sets pending)."""
    return out['statuses'][-1][1]


@needs_node
def test_merge_on_the_head_sets_success_and_never_enables_auto_merge(tmp_path):
    out = run_gate(tmp_path, reviews=[review(MERGE)])
    assert out['statuses'][0] == [HEAD, 'pending', 'Review gate (Codex verdict)'], 'pending first (fail closed)'
    assert final(out) == 'success' and out['automerge'] == 0 and out['labels'] == [] and out['failed'] is None


@needs_node
@pytest.mark.parametrize('reviews,state', [
    ([], 'pending'),
    ([review(BLOCK)], 'failure'),
    ([review(MERGE, commit='b' * 40)], 'pending'),                     # verdict on an older commit
    ([review(MERGE, login='someone-else')], 'pending'),                # not the owner
    ([review(MERGE, state='DISMISSED')], 'pending'),                   # dismissed
    ([review(MERGE, at='2026-11-09T10:00:00Z'), review(BLOCK, at='2026-11-09T11:00:00Z')], 'failure'),  # newest wins
    ([review(BLOCK, at='2026-11-09T10:00:00Z'), review(MERGE, at='2026-11-09T11:00:00Z')], 'success'),
])
def test_only_the_owners_newest_live_verdict_on_the_head_counts(tmp_path, reviews, state):
    out = run_gate(tmp_path, reviews=reviews)
    assert final(out) == state and out['automerge'] == 0


@needs_node
@pytest.mark.parametrize('path', ['backend/alembic/versions/0028_x.py', '.github/workflows/ci.yml', 'frontend/proxy.ts'])
def test_critical_change_gets_the_manual_merge_label(tmp_path, path):
    out = run_gate(tmp_path, reviews=[review(MERGE)], files=['frontend/app/page.tsx', path])
    assert final(out) == 'success' and out['labels'] == ['manual-merge']


@needs_node
def test_a_leftover_auto_merge_is_always_switched_off(tmp_path):
    """Review MRK-97 P1: no persistent status may authorise a merge - GitHub auto-merge is never left on."""
    for reviews in ([review(MERGE)], [review(BLOCK)], []):
        out = run_gate(tmp_path, reviews=reviews, auto_merge={'merge_method': 'merge'})
        assert out['automergeOff'] == 1 and out['automerge'] == 0


@needs_node
def test_edited_or_dismissed_review_turns_the_status_back(tmp_path):
    assert final(run_gate(tmp_path, reviews=[review(MERGE)])) == 'success'
    edited = run_gate(tmp_path, reviews=[review(BLOCK)], event='schedule', open_prs=[7])
    assert edited['evaluated'] == [7] and final(edited) == 'failure'
    dismissed = run_gate(tmp_path, reviews=[review(MERGE, state='DISMISSED')], event='schedule', open_prs=[7])
    assert final(dismissed) == 'pending'


@needs_node
def test_an_api_error_never_keeps_a_green_status(tmp_path):
    out = run_gate(tmp_path, reviews=[review(MERGE)], reviews_fail=True, event='schedule', open_prs=[7])
    assert [s[1] for s in out['statuses']] == ['pending', 'error'] and out['failed'], 'fail closed'


@needs_node
def test_schedule_evaluates_every_open_pr(tmp_path):
    out = run_gate(tmp_path, reviews=[review(MERGE)], event='schedule', open_prs=[7, 8, 9])
    assert out['evaluated'] == [7, 8, 9] and len(out['statuses']) == 6


@needs_node
def test_dispatch_runs_only_from_main_with_a_numeric_pr(tmp_path):
    ok = run_gate(tmp_path, reviews=[review(MERGE)], event='workflow_dispatch', inp='7')
    assert final(ok) == 'success'
    other = run_gate(tmp_path, reviews=[review(MERGE)], event='workflow_dispatch', inp='7', ref='refs/heads/feature')
    assert other['failed'] and other['statuses'] == []
    bad = run_gate(tmp_path, reviews=[review(MERGE)], event='workflow_dispatch', inp='7; rm -rf /')
    assert bad['failed'] == 'No valid PR number.' and bad['statuses'] == []


def test_docs_list_every_required_check_by_its_real_name():
    names = [job['name'] for job in CI['jobs'].values()] + ['Review gate (Codex verdict)']
    for name in names:
        assert f'`{name}`' in OPS, name
    assert 'required approvals **0**' in OPS and '--match-head-commit' in OPS
    assert 'Codex-Verdict: MERGE' in AGENTS and 'nikdy autor kódu' in AGENTS


def test_review_script_never_merges_and_codex_stays_read_only():
    code = [line for line in SCRIPT.splitlines() if not line.lstrip().startswith('#')]
    text = '\n'.join(code)
    assert '--sandbox read-only' in text
    assert 'git push' not in text and '--auto' not in text, 'never GitHub auto-merge'
    merges = [line for line in code if 'gh pr merge' in line]
    assert merges and all('--match-head-commit "$head"' in m for m in merges), 'merge only pinned to the checked head'
    assert 'gh workflow run review-gate.yml --repo "$REPO" --ref main' in text, 'the trusted gate re-evaluates after a review'


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
