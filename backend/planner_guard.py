"""Deterministická kontrola groundingu LLM planner odpovědí.

LLM planner vrací ```json blok ({summary, actions[priority, area, title, reason]}), který frontend
renderuje jako kartu (app/ai/page.tsx → tryParseWeeklyPlan). Model občas doplní vymyšlené
projekty, částky nebo cíle. Tento modul:
  * najde planner blok podle stejných pravidel jako frontend,
  * z textu, který model v requestu skutečně měl (tool výsledky, zprávy uživatele, aktuální datum),
    sestaví „evidence",
  * odstraní akce, které uvádějí čísla s jednotkou / velká čísla, data nebo názvy (projekty, vlastní
    jména), jež v evidence nejsou a nejdou z ní jednoduše dopočítat.
Raději méně akcí než vymyšlené – odpovídá pravidlu PLANNER v SYSTEM_PROMPT.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import product

PLANNER_REQUIRED_TOOLS = ("get_goals", "get_memories")
PLANNER_AREAS = frozenset({"school", "work", "finance", "wot", "mff", "personal", "fitness", "hobby", "travel", "general"})
NO_GROUNDED_ACTIONS_NOTE = (
    "Z dostupných dat teď nedokážu sestavit konkrétní ověřené akce – doplň prosím cíle, úkoly nebo práci."
)
_GENERIC_SUMMARY = "Plán podle aktuálních dat."

_FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.S)
# Číslo: „150 000", „7,5", „7.5", „325"; volitelný násobič (tis., mil.) a jednotka.
_NUMBER_RE = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?"
    r"(?:\s*(tis\.?|tisíc\w*|mil\.?|milion\w*))?"
    r"(?:\s*(%|kč|czk|h\b|hod\w*|xp|kredit\w*|gold\w*|bond\w*))?",
    re.I,
)
# Metadata, ne hodnoty, na které se plán smí odkazovat (id, cizí klíče, důležitost paměti).
_ID_KEY_RE = re.compile(r"(^id$|_id$|^importance$)")
_ISO_DATETIME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
_CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_DATE_DM_RE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_PROJECT_RE = re.compile(r"\bproje[ck]t\w*\s+[„\"'“]?([^\s„\"'“”,.;:!?)]+)", re.I)
_CAPITALIZED_RE = re.compile(r"[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wÁ-ž.\-/]*")
_STOPWORDS = frozenset({
    "a", "i", "na", "pro", "do", "v", "ve", "z", "ze", "s", "se", "k", "ke", "o", "u", "za", "po", "od",
    "the", "for", "to", "of", "and",
})
# Obecné zkratky / názvy domén, které nejsou „vymyšlené vlastní jméno".
_KNOWN_TERMS = frozenset({
    "wot", "mff", "world", "of", "tanks", "marvel", "future", "fight", "kč", "czk", "xp", "free", "gold",
    "t1", "t2", "t3", "t4", "abx", "abl", "gbr", "pvp", "ects", "it",
})
_MULTIPLIERS = {"tis": 1_000, "mil": 1_000_000}


@dataclass(frozen=True)
class PlannerBlock:
    start: int
    end: int
    plan: dict


@dataclass(frozen=True)
class Evidence:
    text: str  # lowercase
    numbers: frozenset[float]
    day_months: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class GroundingResult:
    answer: str
    removed_actions: int
    summary_replaced: bool


def find_planner_block(answer: str) -> PlannerBlock | None:
    """Stejná pravidla jako frontend tryParseWeeklyPlan (```json nebo ``` bez jazyka)."""
    for m in _FENCE_RE.finditer(answer or ""):
        if m.group(1).strip() not in ("json", ""):
            continue
        try:
            plan = json.loads(m.group(2))
        except (ValueError, TypeError):
            continue
        if not isinstance(plan, dict) or not isinstance(plan.get("summary"), str):
            continue
        actions = plan.get("actions")
        if not isinstance(actions, list) or not 1 <= len(actions) <= 8:
            continue
        if all(
            isinstance(a, dict)
            and isinstance(a.get("priority"), (int, float))
            and all(isinstance(a.get(k), str) for k in ("area", "title", "reason"))
            for a in actions
        ):
            return PlannerBlock(m.start(), m.end(), plan)
    return None


def _parse_number(match: re.Match) -> tuple[float, bool]:
    integer = re.sub(r"[   ]", "", match.group(1))
    value = float(f"{integer}.{match.group(2)}" if match.group(2) else integer)
    multiplier = (match.group(3) or "").lower()[:3]
    value *= _MULTIPLIERS.get(multiplier, 1)
    has_unit = bool(match.group(4)) or bool(multiplier)
    return value, has_unit


def _collect_json(value, key: str | None, numbers: set[float], strings: list[str]) -> None:
    """Čísla jen z datových polí (ne id / *_id); řetězce se zpracují jako volný text."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not (key and _ID_KEY_RE.search(key)):
            numbers.add(float(value))
    elif isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            _collect_json(v, str(k), numbers, strings)
    elif isinstance(value, list):
        for item in value:
            _collect_json(item, key, numbers, strings)


def build_evidence(texts: list[str], name_only_texts: tuple[str, ...] = ()) -> Evidence:
    """texts = živá data (čísla, data, jména); name_only_texts = paměť – jen jména, nikdy čísla/data."""
    numbers: set[float] = set()
    free_text: list[str] = []
    for text in (t for t in texts if t):
        stripped = text.lstrip()
        if stripped[:1] in ("{", "["):
            try:
                _collect_json(json.loads(stripped), None, numbers, free_text)
                continue
            except ValueError:
                pass
        free_text.append(text)
    joined = "\n".join(free_text)
    day_months = {(int(d), int(mo)) for _y, mo, d in _ISO_DATE_RE.findall(joined)}
    day_months |= {(int(d), int(mo)) for d, mo in _DATE_DM_RE.findall(joined)}
    # Timestampy / data / časy nejsou „hodnoty" (jinak by rok 2026 ověřil vymyšlených 2 000 Kč).
    numeric_text = _CLOCK_RE.sub(" ", _ISO_DATETIME_RE.sub(" ", joined))
    numbers |= {_parse_number(m)[0] for m in _NUMBER_RE.finditer(numeric_text)}
    all_text = "\n".join(t for t in (*texts, *name_only_texts) if t).lower()
    return Evidence(text=all_text, numbers=frozenset(numbers), day_months=frozenset(day_months))


def _number_is_grounded(value: float, evidence: Evidence) -> bool:
    # Přímá shoda; relativní tolerance jen pro zaokrouhlení skutečných hodnot („3,1 mil." ≈ 3 082 152).
    if any(abs(value - n) <= 0.51 or (n and abs(value - n) / abs(n) <= 0.01) for n in evidence.numbers):
        return True
    # Jednoduché dopočty z ověřených hodnot (přesně): zbývá (a − b), součet, hodiny × sazba, procento a/b.
    # Jen pro „peněžní" velikosti – malé hodnoty (hodiny, %) by náhodně vycházely z ID, počtů apod.
    if value < 100:
        return False
    nums = sorted(n for n in evidence.numbers if n != 0)[:300]
    for a, b in product(nums, repeat=2):
        if any(abs(value - d) <= 0.51 for d in (a - b, a + b, a * b, a / b * 100)):
            return True
    return False


def ungrounded_items(text: str, evidence: Evidence) -> list[str]:
    """Vrátí kategorie problémů (bez obsahu – bezpečné pro log)."""
    problems: list[str] = []
    without_dates = _DATE_DM_RE.sub(" ", _ISO_DATE_RE.sub(" ", text))
    for m in _NUMBER_RE.finditer(without_dates):
        value, has_unit = _parse_number(m)
        if (has_unit or value >= 100) and not _number_is_grounded(value, evidence):
            problems.append("number")
    for d, mo in _DATE_DM_RE.findall(text):
        if (int(d), int(mo)) not in evidence.day_months:
            problems.append("date")
    for _y, mo, d in _ISO_DATE_RE.findall(text):
        if (int(d), int(mo)) not in evidence.day_months:
            problems.append("date")
    for name in _PROJECT_RE.findall(text):
        if name.lower() not in _STOPWORDS and name.lower() not in evidence.text:
            problems.append("project")
    words = text.split()
    for i, word in enumerate(words):
        if i == 0 or words[i - 1].endswith((".", "!", "?", ":")):
            continue  # začátek věty
        m = _CAPITALIZED_RE.match(word.strip("„\"'“”()"))
        if not m:
            continue
        token = m.group(0).split("/")[0].rstrip(".-").lower()  # „Kč/h" → „kč"
        if len(token) > 1 and token not in _KNOWN_TERMS and token not in evidence.text:
            problems.append("name")
    return problems


def ground_planner_answer(answer: str, evidence: Evidence) -> GroundingResult:
    block = find_planner_block(answer)
    if block is None:
        return GroundingResult(answer, 0, False)
    # title a reason jsou samostatné věty (velké písmeno na začátku reason není vlastní jméno).
    kept = [
        a for a in block.plan["actions"]
        if not ungrounded_items(a["title"], evidence) and not ungrounded_items(a["reason"], evidence)
    ]
    removed = len(block.plan["actions"]) - len(kept)
    summary = block.plan["summary"]
    summary_replaced = bool(ungrounded_items(summary, evidence))
    if summary_replaced:
        summary = _GENERIC_SUMMARY
    if not removed and not summary_replaced:
        return GroundingResult(answer, 0, False)

    if kept:
        actions = [{**a, "priority": i} for i, a in enumerate(kept, start=1)]
        plan = {**block.plan, "summary": summary, "actions": actions}
        replacement = "```json\n" + json.dumps(plan, ensure_ascii=False, indent=2) + "\n```"
    else:
        replacement = NO_GROUNDED_ACTIONS_NOTE
    new_answer = answer[:block.start] + replacement + answer[block.end:]
    return GroundingResult(new_answer, removed, summary_replaced)


def missing_planner_tools(called_tools: set[str]) -> list[str]:
    return [t for t in PLANNER_REQUIRED_TOOLS if t not in called_tools]


def planner_tools_nudge(missing: list[str]) -> str:
    return (
        "PLANNER rule check: before the final plan you must call "
        + " and ".join(missing)
        + ". Call them now, then answer again using only grounded data."
    )
