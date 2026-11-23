"""MRK-110: kontrolní sada pro deterministický výběr vzpomínek do kontextu (bez LLM, bez DB, bez sítě).

Data: backend/tests/data/memory_selection_cases.json - vymyšlené vzpomínky a dotazy ve dvou částech:
- `tune`: případy, na kterých se výběr (context_service.rank_memories / classify_areas / wants_broad_memory) ladí;
- `holdout`: stranou - při ladění se NEUPRAVUJÍ; ukazují, jestli změna pomohla obecně, ne jen na opraveném příkladu.
Každý případ: `must` (musí se vybrat), `must_not` (nesmí se vybrat). `known_gap` = správné očekávání, které dnešní
výběr nesplňuje (důvod v `note`) - počítá se do metrik, test kvůli němu nepadá.

Test hlídá dvě věci:
1. každý případ bez known_gap projde (regrese = konkrétní případ, který přestal fungovat);
2. metriky obou částí nejsou horší než `baseline` v datech (úplnost výběru `recall`, porušení `must_not`).
Zlepšení = posunout baseline v datech v tomtéž PR. Postup přidání případu: docs/memory-selection-cases.md.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

import context_service as cs
from models import Memory

DATA = json.loads((Path(__file__).parent / 'data' / 'memory_selection_cases.json').read_text(encoding='utf-8'))


def memories():
    out = []
    for m in DATA['memories']:
        mem = Memory(area=m['area'], category=m['category'], content=m['content'], importance=m['importance'],
                     active=m.get('active', True))
        mem.created_at = mem.updated_at = datetime.fromisoformat(m['updated'])
        mem.case_id = m['id']
        out.append(mem)
    return out


def select(message):
    """Stejný výběr jako build_current_context: oblasti dotazu (bez záměru jen výslovné), široký výběr, rank_memories."""
    broad = cs.wants_broad_memory(message)
    areas = cs.classify_areas(message, implied=broad)
    return [m.case_id for m in cs.rank_memories(memories(), message, areas, planner=broad)]


def outcome(case):
    chosen = select(case['message'])
    return {
        'chosen': chosen,
        'hits': sum(1 for i in case['must'] if i in chosen),
        'violations': sum(1 for i in case['must_not'] if i in chosen),
        'ok': all(i in chosen for i in case['must']) and not any(i in chosen for i in case['must_not']),
    }


def metrics(split):
    cases = [c for c in DATA['cases'] if c['split'] == split]
    results = [outcome(c) for c in cases]
    must = sum(len(c['must']) for c in cases)
    must_not = sum(len(c['must_not']) for c in cases)
    return {
        'cases': len(cases),
        'passed': sum(r['ok'] for r in results),
        'recall': round(sum(r['hits'] for r in results) / must, 3) if must else 1.0,
        'violation_rate': round(sum(r['violations'] for r in results) / must_not, 3) if must_not else 0.0,
    }


def test_data_is_well_formed():
    ids = [m['id'] for m in DATA['memories']]
    assert len(ids) == len(set(ids))
    splits = [c['split'] for c in DATA['cases']]
    assert splits.count('tune') >= 20 and splits.count('holdout') >= 10, 'MRK-110: aspoň 20 + 10 případů'
    for c in DATA['cases']:
        assert c['split'] in ('tune', 'holdout')
        assert set(c['must']) | set(c['must_not']) <= set(ids), c['id']
        assert not set(c['must']) & set(c['must_not']), c['id']
        assert not c.get('known_gap') or c.get('note'), f"{c['id']}: known_gap potřebuje důvod v note"
    text = json.dumps([DATA['memories'], DATA['cases']], ensure_ascii=False).lower()
    assert not any(w in text for w in ('financ', 'výdaj', 'příjem', ' kč', 'zůstatek', 'rozpočet')), 'MRK-60'


@pytest.mark.parametrize('case', [c for c in DATA['cases'] if not c.get('known_gap')], ids=lambda c: c['id'])
def test_case(case):
    r = outcome(case)
    assert r['ok'], f"{case['split']} {case['id']}: vybráno {r['chosen']}, musí {case['must']}, nesmí {case['must_not']}"


@pytest.mark.parametrize('split', ['tune', 'holdout'])
def test_metrics_do_not_regress(split):
    got, base = metrics(split), DATA['baseline'][split]
    print(f'MEMORY_SELECTION {split}: {got}')
    assert got['recall'] >= base['recall'], (split, got, base)
    assert got['violation_rate'] <= base['violation_rate'], (split, got, base)
    assert got['passed'] >= base['passed'], (split, got, base)


def test_known_gaps_are_still_gaps():
    """Opravený known_gap se má přeřadit mezi běžné případy (a posunout baseline), ne zůstat označený."""
    fixed = [c['id'] for c in DATA['cases'] if c.get('known_gap') and outcome(c)['ok']]
    assert not fixed, f'Tyto případy už projdou - odeber known_gap a posuň baseline: {fixed}'


def test_broad_memory_only_with_planning_intent():
    """MRK-118: zmínka dne nezapne široký výběr; plánovací / přehledový záměr ano."""
    assert not cs.wants_broad_memory('Hraju v pátek večer v četě?')
    for message in ('Naplánuj mi pátek', 'Co mám zítra?', 'Co mám dneska dělat?', 'Jak jsem na tom se školou?'):
        assert cs.wants_broad_memory(message), message
    # routing toolů dál bere časová slova
    assert cs.is_planner_like('Hraju v pátek večer v četě?')


def test_time_word_alone_does_not_select_a_memory():
    mems = [m for m in memories() if m.case_id == 'fyzika-zkouska']
    assert cs.rank_memories(mems, 'Hraju v pátek večer v četě?', frozenset(), planner=False) == []
