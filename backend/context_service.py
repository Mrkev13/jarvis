"""Server-side context prefetch (Roadmap 3.0 A3).

Před LLM voláním sestaví kompaktní CURRENT STATE (živá data modulů) + RELEVANT MEMORY, aby častý dotaz
(„co mám zítra", „co mám dělat tento týden", „jak jsem na tom") nepotřeboval 4–6 sekvenčních read-tool
kol. Výběr oblastí je deterministický (klíčová slova), bez LLM volání. Velikost hlídá rozpočet tokenů.

MRK-20: klíčová slova oblastí, sekce CURRENT STATE, pokryté tooly a názvy záznamů dodávají moduly
(`ModuleIntegrations.context`); tady zůstává globální politika – implikované oblasti (plán, přehled),
pořadí a ořez podle rozpočtu, paměť, gating dostupností modulů a izolace chyb.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from context_format import short
from llm_budget import estimate_tokens
from llm_config import DEFAULT_CONTEXT_TARGET_TOKENS, DEFAULT_MAX_CONTEXT_TOKENS
from models import Memory
from module_contracts import ContextRequest
from module_registry import MODULES, ModuleAccess, all_contributions, current_access
from statuses import REMINDER_ACTIVE_STATUSES
from time_utils import now_local
from text_utils import WEEKDAYS_CZ_SHORT, fold_text

log = logging.getLogger(__name__)

CONTEXT_TARGET_TOKENS = DEFAULT_CONTEXT_TARGET_TOKENS
CONTEXT_MAX_TOKENS = DEFAULT_MAX_CONTEXT_TOKENS
MAX_MEMORIES = 3
MEMORY_CHARS = 140

# Oblasti, na které se odkazují globální pravidla níže (implikované oblasti, ořez). Data a klíčová slova oblastí
# dodávají moduly (MRK-20: `ModuleIntegrations.context` v <modul>_integrations.py, jádro v core_integrations.py).
AREA_SCHOOL, AREA_GOALS, AREA_NOTIFICATIONS = "school", "goals", "notifications"
AREA_FINANCE, AREA_WORK, AREA_WOT, AREA_MEMORY = "finance", "work", "wot", "memory"
AREA_MFF = "mff"
AREA_REMINDERS = "reminders"

_WEEKDAYS = WEEKDAYS_CZ_SHORT

# Klíčová slova (bez diakritiky, podřetězce) → oblasti.
_TIME_PLAN_WORDS = ("zitra", "dnes", "dneska", "tyden", "tydnu", "vikend", "pondeli", "utery", "streda", "ctvrtek",
                    "patek", "sobota", "nedele", "datum", "co mam", "plan", "priorit", "myslet", "program", "agenda")
# Plánovací záměr („co mám dělat", plán, priority): planner řadí i finance a práci → bez nich v kontextu
# by si je model vždy dočítal extra tool kolem.
_PLAN_INTENT_WORDS = ("delat", "plan", "priorit", "agenda", "program", "zamer", "soustred")
_OVERVIEW_WORDS = ("jak jsem na tom", "jak na tom", "prehled", "shrnuti", " stav", "jak se mi dari", "co je noveho")
# Statické tabulky ze VŠECH registrovaných oblastí (routing toolů běží i bez DB a stavu modulů; vypnutý modul
# zablokuje sekci i tooly později – `access.contributions` a tool_router).
_AREA_WORDS: dict[str, tuple[str, ...]] = {sec.area: sec.keywords for _owner, sec in all_contributions("context")}
# Read tooly, jejichž informaci daná sekce pokrývá (planner pravidla, metriky).
_COVERED_TOOLS: dict[str, tuple[str, ...]] = {
    **{sec.area: sec.covered_tools for _owner, sec in all_contributions("context") if sec.covered_tools},
    AREA_MEMORY: ("get_memories",),
}
_STOPWORDS = {"jsem", "mam", "mas", "jak", "kdy", "kde", "jaky", "jaka", "jake", "pro", "ktery", "ktera", "ten", "tento",
              "tohle", "neco", "nebo", "ale", "aby", "byl", "bude", "chci", "muj", "moje", "tom", "the", "and"}


@dataclass(frozen=True)
class CurrentContext:
    text: str  # celý injektovaný text (CURRENT STATE + RELEVANT MEMORY)
    sections: tuple[str, ...]
    covered_tools: frozenset[str]
    estimated_tokens: int
    areas: frozenset[str] = field(default_factory=frozenset)
    memory_text: str = ""  # jen RELEVANT MEMORY – pro grounding NENÍ zdrojem čísel
    # Oblasti výslovně zmíněné jménem záznamu z DB, které router sám nezná (název aktivní připomínky).
    named_areas: frozenset[str] = field(default_factory=frozenset)


def _split_memory(text: str) -> str:
    marker = "\nRELEVANT MEMORY"
    return text[text.index(marker) + 1:] if marker in text else ""


def _fold(text: str) -> str:
    """Lowercase bez diakritiky – deterministické porovnávání českých slov (text_utils.fold_text)."""
    return fold_text(text)


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def is_planner_like(message: str) -> bool:
    """Časový / plánovací / přehledový dotaz – stejné pravidlo, jakým prefetch rozhoduje o paměti."""
    # Mezery kolem: slova jako " stav" se hledají od začátku slova („postav" není přehled).
    folded = f" {_fold(message)} "
    return _has(folded, _TIME_PLAN_WORDS) or _has(folded, _OVERVIEW_WORDS)


def classify_areas(message: str, project_names=(), tank_names=(), *, implied: bool = True,
                   hints: dict[str, list[str]] | None = None,
                   words: dict[str, tuple[str, ...]] | None = None) -> frozenset[str]:
    """Oblasti dotazu. implied=False vrátí jen explicitně zmíněné oblasti (pro pořadí při ořezu).

    `hints` = názvy záznamů podle oblasti (`ContextSection.name_hints`); `project_names` / `tank_names` jsou
    starší zkratky pro hints["work"] / hints["wot"].
    """
    t = f" {_fold(message)} "
    areas: set[str] = set()
    for area, area_words in (_AREA_WORDS if words is None else words).items():
        if _has(t, area_words):
            areas.add(area)
    named = {area: list(names) for area, names in (hints or {}).items()}
    named.setdefault(AREA_WORK, []).extend(project_names)
    named.setdefault(AREA_WOT, []).extend(tank_names)
    for area, names in named.items():
        if _has(t, [_fold(n) for n in names if n and len(n) >= 3]):
            areas.add(area)
    if not implied:
        return frozenset(areas)
    if _has(t, _TIME_PLAN_WORDS):
        areas |= {AREA_SCHOOL, AREA_GOALS, AREA_NOTIFICATIONS, AREA_REMINDERS}
    if _has(t, _PLAN_INTENT_WORDS):
        areas |= {AREA_SCHOOL, AREA_GOALS, AREA_NOTIFICATIONS, AREA_WORK, AREA_FINANCE}
    if _has(t, _OVERVIEW_WORDS):
        areas |= {AREA_GOALS, AREA_NOTIFICATIONS, AREA_SCHOOL, AREA_WORK, AREA_FINANCE}
    if AREA_WORK in areas:
        areas |= {AREA_FINANCE, AREA_GOALS}
    if AREA_FINANCE in areas:
        areas.add(AREA_GOALS)
    return frozenset(areas)


def _tokens(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9.]{3,}", _fold(text)) if w not in _STOPWORDS}


def rank_memories(memories: list[Memory], message: str, areas: frozenset[str], *, planner: bool) -> list[Memory]:
    """Deterministické řazení: aktivní, překryv slov, oblast, důležitost, recency jako tiebreak."""
    msg_tokens = _tokens(message)
    scored = []
    for m in memories:
        if not m.active:
            continue
        overlap = len(msg_tokens & _tokens(m.content or ""))
        area_match = (m.area or "") in areas
        if not (overlap or area_match or planner):
            continue
        score = overlap * 3 + (3 if area_match else 0) + int(m.importance or 0)
        recency = (m.updated_at or m.created_at or datetime.min).timestamp() if (m.updated_at or m.created_at) else 0
        scored.append((score, recency, m))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [m for _s, _r, m in scored[:MAX_MEMORIES]]


def _render(header_lines: list[str], sections: list[tuple[str, list[str]]], memory_lines: list[str]) -> str:
    out = ["CURRENT STATE (live module data – authoritative; do not re-fetch with tools)", *header_lines]
    for _key, lines in sections:
        out.extend(lines)
    if memory_lines:
        out.append("RELEVANT MEMORY (long-term context only – never a source of current numbers)")
        out.extend(memory_lines)
    return "\n".join(out)


def _named_reminder_areas(db: Session, message: str) -> frozenset[str]:
    """Zmínka názvu aktivní připomínky („posuň fyzio o hodinu") = výslovně oblast připomínek."""
    from models import Reminder

    titles = [_fold(t).strip() for (t,) in db.query(Reminder.title).filter(Reminder.status.in_(REMINDER_ACTIVE_STATUSES)).all() if t]
    folded = _fold(message)
    # Celá slova („fyzio" ano, „fyzioterapeut" ne) – název připomínky bývá obyčejné slovo.
    hit = any(len(t) >= 3 and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", folded) for t in titles)
    return frozenset({AREA_REMINDERS}) if hit else frozenset()


def build_current_context(
    db: Session,
    message: str,
    *,
    now_utc: datetime | None = None,
    target_tokens: int = CONTEXT_TARGET_TOKENS,
    max_tokens: int = CONTEXT_MAX_TOKENS,
    access: ModuleAccess | None = None,
) -> CurrentContext:
    local = now_local(now_utc)
    today = local.date()
    # Roadmap 6C / MRK-20: jen oblasti modulů, které smí do AI kontextu (vypnutý modul nedodá nic).
    access = access or current_access()
    sections_by_area = {sec.area: sec for _owner, sec in access.contributions("context")}
    hints = {area: list(sec.name_hints(db)) for area, sec in sections_by_area.items() if sec.name_hints}
    words = None if access.modules is MODULES else {s.area: s.keywords for _o, s in all_contributions("context", access.modules)}
    named = _named_reminder_areas(db, message)
    areas = classify_areas(message, hints=hints, words=words) | named
    planner_like = is_planner_like(message)

    tomorrow = today + timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    header = [
        f"Dnes {today.isoformat()} ({_WEEKDAYS[today.weekday()]}) {local:%H:%M}; zítra {tomorrow.isoformat()} "
        f"({_WEEKDAYS[tomorrow.weekday()]}); tento týden {monday.isoformat()} až {(monday + timedelta(days=6)).isoformat()}"
    ]
    req = ContextRequest(db=db, today=today, local_now=local)
    # Explicitně zmíněné oblasti první → při ořezu rozpočtu se odebírají až nakonec.
    explicit = classify_areas(message, implied=False, hints=hints, words=words) | named
    with_section = sorted((sec for sec in sections_by_area.values() if sec.build and sec.order is not None and sec.area in areas),
                          key=lambda sec: sec.order)
    ordered = sorted(with_section, key=lambda sec: sec.area not in explicit)
    sections = []
    for sec in ordered:
        try:
            sections.append((sec.area, sec.build(req)))
        except Exception:  # noqa: BLE001 – chyba jednoho modulu = jen chybějící sekce (tooly ji dočtou)
            log.exception("context: section %s failed", sec.area)
            db.rollback()

    memories = rank_memories(db.query(Memory).filter(Memory.active.is_(True)).all(), message, areas, planner=planner_like)
    memory_lines = [f"- [{m.area}/{m.category}] {short(m.content, MEMORY_CHARS)}" for m in memories]
    memory_checked = planner_like or bool(memory_lines)

    if not sections and not memory_lines:
        # Neznámý / obecný dotaz: jen datum (malý obecný souhrn), žádná data modulů.
        text = _render(header, [], [])
        return CurrentContext(text, ("date",), frozenset(), estimate_tokens(text), areas, named_areas=named)

    # Rozpočet: nejdřív zkrátit paměť, pak odebírat sekce od nejméně důležité (konec pořadí).
    text = _render(header, sections, memory_lines)
    while estimate_tokens(text) > target_tokens and len(memory_lines) > 1:
        memory_lines = memory_lines[:-1]
        text = _render(header, sections, memory_lines)
    while estimate_tokens(text) > max_tokens and sections:
        sections = sections[:-1]
        text = _render(header, sections, memory_lines)
    if estimate_tokens(text) > max_tokens:
        memory_lines = []
        text = _render(header, sections, memory_lines)

    included = [key for key, _ in sections]
    covered = {tool for key in included for tool in (sections_by_area[key].covered_tools if key in sections_by_area else ())}
    if memory_checked and (memory_lines or planner_like):
        covered |= set(_COVERED_TOOLS[AREA_MEMORY])
    section_names = ("date", *included, *(("memory",) if memory_lines else ()))
    return CurrentContext(text, section_names, frozenset(covered), estimate_tokens(text), areas, _split_memory(text),
                          named_areas=named)
