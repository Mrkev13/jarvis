"""Server-side context prefetch (Roadmap 3.0 A3).

Před LLM voláním sestaví kompaktní CURRENT STATE (živá data modulů) + RELEVANT MEMORY, aby častý dotaz
(„co mám zítra", „co mám dělat tento týden", „jak jsem na tom") nepotřeboval 4–6 sekvenčních read-tool
kol. Výběr oblastí je deterministický (klíčová slova), bez LLM volání. Velikost hlídá rozpočet tokenů.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from goal_history_service import compute_goal_progress_and_value
from llm_budget import estimate_tokens
from llm_config import DEFAULT_CONTEXT_TARGET_TOKENS, DEFAULT_MAX_CONTEXT_TOKENS
from models import Assignment, Exam, FinanceTransaction, Goal, Memory, Notification, WorkSession, WotGrind, WotResource
from time_utils import local_month_bounds_utc, now_local

CONTEXT_TARGET_TOKENS = DEFAULT_CONTEXT_TARGET_TOKENS
CONTEXT_MAX_TOKENS = DEFAULT_MAX_CONTEXT_TOKENS
WINDOW_DAYS = 7
MAX_ITEMS = 3
MAX_MEMORIES = 3
MEMORY_CHARS = 140

AREA_SCHOOL, AREA_GOALS, AREA_NOTIFICATIONS = "school", "goals", "notifications"
AREA_FINANCE, AREA_WORK, AREA_WOT, AREA_MEMORY = "finance", "work", "wot", "memory"
# MFF nemá CURRENT STATE sekci; oblast slouží routingu toolů (A5) a řazení paměti.
AREA_MFF = "mff"
# Phase D: připomínky (časové dotazy je zahrnují stejně jako školu a cíle).
AREA_REMINDERS = "reminders"

_DONE_STATUSES = {"completed", "hotovo", "done", "closed", "finished"}
_EXAM_OPEN_STATUSES = {"upcoming", "scheduled", ""}
_INACTIVE_GOAL_STATUSES = {"completed", "paused", "cancelled"}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_WEEKDAYS = ("po", "út", "st", "čt", "pá", "so", "ne")

# Klíčová slova (bez diakritiky, podřetězce) → oblasti.
_TIME_PLAN_WORDS = ("zitra", "dnes", "dneska", "tyden", "tydnu", "vikend", "pondeli", "utery", "streda", "ctvrtek",
                    "patek", "sobota", "nedele", "datum", "co mam", "plan", "priorit", "myslet", "program", "agenda")
# Plánovací záměr („co mám dělat", plán, priority): planner řadí i finance a práci → bez nich v kontextu
# by si je model vždy dočítal extra tool kolem.
_PLAN_INTENT_WORDS = ("delat", "plan", "priorit", "agenda", "program", "zamer", "soustred")
_OVERVIEW_WORDS = ("jak jsem na tom", "jak na tom", "prehled", "shrnuti", " stav", "jak se mi dari", "co je noveho")
_AREA_WORDS = {
    AREA_SCHOOL: ("skol", "ukol", "zkous", "pisemk", "zapoct", "predmet", "semestr", "deadline", "termin", "test"),
    AREA_FINANCE: ("penez", "penize", "financ", "vydaj", "prijem", "prijm", "utrat", "bilanc", "uspor", "setr",
                   "rozpoc", " kc", "korun", "money", "zustatek"),
    AREA_WORK: ("prac", "odprac", "hodin", "smen", "vydelek", "vydelal", "sazb"),
    AREA_WOT: ("wot", "tank", "kredit", "gold", "grind", "free xp", "bond"),
    AREA_MFF: ("mff", "marvel", "future fight", "uniform", " ctp", " uru", "iso-8", "iso8"),
    AREA_REMINDERS: ("pripom", "upomin", "reminder"),
    AREA_GOALS: ("cil", "cile", "goal", "progres"),
    AREA_NOTIFICATIONS: ("upozorn", "notifikac", "notifik"),
}
_AREA_SECTIONS_ORDER = (AREA_SCHOOL, AREA_REMINDERS, AREA_NOTIFICATIONS, AREA_GOALS, AREA_WORK, AREA_FINANCE,
                        AREA_WOT)
# Read tooly, jejichž informaci daná sekce pokrývá (planner pravidla, metriky).
_COVERED_TOOLS = {
    AREA_SCHOOL: ("get_school_assignments", "get_school_exams"),
    AREA_GOALS: ("get_goals", "get_goals_summary"),
    AREA_NOTIFICATIONS: ("get_notification_summary",),
    AREA_WORK: ("get_work_summary",),
    AREA_FINANCE: ("get_finance_summary",),
    AREA_WOT: ("get_wot_resources", "get_wot_grinds"),
    AREA_MEMORY: ("get_memories",),
    AREA_REMINDERS: ("get_reminders",),
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


def _split_memory(text: str) -> str:
    marker = "\nRELEVANT MEMORY"
    return text[text.index(marker) + 1:] if marker in text else ""


def _fold(text: str) -> str:
    """Lowercase bez diakritiky – deterministické porovnávání českých slov."""
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def fold_text(text: str) -> str:
    """Veřejný alias _fold pro sdílené deterministické klasifikátory (tool_router)."""
    return _fold(text)


def is_planner_like(message: str) -> bool:
    """Časový / plánovací / přehledový dotaz – stejné pravidlo, jakým prefetch rozhoduje o paměti."""
    # Mezery kolem: slova jako " stav" se hledají od začátku slova („postav" není přehled).
    folded = f" {_fold(message)} "
    return _has(folded, _TIME_PLAN_WORDS) or _has(folded, _OVERVIEW_WORDS)


def classify_areas(message: str, project_names=(), tank_names=(), *, implied: bool = True) -> frozenset[str]:
    """Oblasti dotazu. implied=False vrátí jen explicitně zmíněné oblasti (pro pořadí při ořezu)."""
    t = f" {_fold(message)} "
    areas: set[str] = set()
    for area, words in _AREA_WORDS.items():
        if _has(t, words):
            areas.add(area)
    if _has(t, [_fold(p) for p in project_names if p and len(p) >= 3]):
        areas.add(AREA_WORK)
    if _has(t, [_fold(n) for n in tank_names if n and len(n) >= 3]):
        areas.add(AREA_WOT)
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


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")


def _short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _list_or_none(items: list[str], total: int) -> str:
    if not items:
        return "žádné"
    more = f" (+{total - len(items)} další)" if total > len(items) else ""
    return "; ".join(items) + more


def _school_lines(db: Session, today: date) -> list[str]:
    window_end = today + timedelta(days=WINDOW_DAYS)
    open_assignments = [
        a for a in db.query(Assignment).filter(Assignment.due_date.is_not(None)).all()
        if (a.status or "").strip().lower() not in _DONE_STATUSES
    ]
    overdue = sorted((a for a in open_assignments if a.due_date < today), key=lambda a: a.due_date)
    upcoming = sorted((a for a in open_assignments if today <= a.due_date <= window_end), key=lambda a: a.due_date)
    exams = sorted(
        (e for e in db.query(Exam).filter(Exam.exam_date.is_not(None)).all()
         if today <= e.exam_date <= window_end and (e.status or "").strip().lower() in _EXAM_OPEN_STATUSES),
        key=lambda e: e.exam_date,
    )

    def fmt(title: str, subject, d: date) -> str:
        subj = f", {_short(subject.name, 25)}" if subject is not None else ""
        return f"{_short(title, 50)}{subj}, {d.isoformat()}"

    return [
        f"Škola po termínu: {_list_or_none([fmt(a.title, a.subject, a.due_date) for a in overdue[:MAX_ITEMS]], len(overdue))}",
        f"Úkoly do {window_end.isoformat()}: {_list_or_none([fmt(a.title, a.subject, a.due_date) for a in upcoming[:MAX_ITEMS]], len(upcoming))}",
        f"Zkoušky do {window_end.isoformat()}: {_list_or_none([fmt(e.title, e.subject, e.exam_date) for e in exams[:MAX_ITEMS]], len(exams))}",
    ]


def _notification_lines(db: Session) -> list[str]:
    rows = (
        db.query(Notification)
        .filter(Notification.read.is_(False), Notification.resolved.is_(False), Notification.severity == "important")
        .order_by(Notification.created_at.desc())
        .all()
    )
    return [f"Důležitá nepřečtená upozornění: {_list_or_none([_short(n.title, 60) for n in rows[:MAX_ITEMS]], len(rows))}"]


def _goal_lines(db: Session, today: date) -> list[str]:
    goals = [g for g in db.query(Goal).all() if (g.status or "").strip().lower() not in _INACTIVE_GOAL_STATUSES]
    goals.sort(key=lambda g: (_PRIORITY_RANK.get((g.priority or "").lower(), 3), g.target_date or date.max))
    items = []
    for g in goals[:MAX_ITEMS]:
        progress, current = compute_goal_progress_and_value(db, g, today=today)
        value = ""
        if current is not None and g.target_value:
            value = f" ({_fmt_num(current)} / {_fmt_num(float(g.target_value))})"
        deadline = f", do {g.target_date.isoformat()}" if g.target_date else ""
        items.append(f"\"{_short(g.title, 50)}\" {progress} %{value}{deadline}")
    return [f"Aktivní cíle: {_list_or_none(items, len(goals))}"]


def _work_lines(db: Session, today: date) -> list[str]:
    month_start = today.replace(day=1)
    sessions = db.query(WorkSession).filter(WorkSession.date >= month_start, WorkSession.date <= today).all()
    hours = sum(float(s.hours or 0) for s in sessions)
    earnings = sum(float(s.hours or 0) * float(s.hourly_rate or 0) for s in sessions)
    last = db.query(WorkSession).order_by(WorkSession.date.desc(), WorkSession.id.desc()).first()
    last_txt = (
        f"; poslední záznam {last.date.isoformat()} {_short(last.project or '-', 30)} {_fmt_num(float(last.hours or 0))} h"
        if last else "; žádné záznamy"
    )
    return [f"Práce tento měsíc: {_fmt_num(hours)} h, {_fmt_num(earnings)} Kč{last_txt}"]


def _finance_lines(db: Session, today: date) -> list[str]:
    start_utc, end_utc = local_month_bounds_utc(today)
    income = expenses = total_income = total_expenses = 0.0
    for t in db.query(FinanceTransaction).all():
        amount = float(t.amount or 0)
        is_income = (t.transaction_type or "").lower() == "income"
        in_month = t.created_at is not None and start_utc <= t.created_at < end_utc
        if is_income:
            total_income += amount
            income += amount if in_month else 0
        else:
            total_expenses += amount
            expenses += amount if in_month else 0
    return [
        f"Finance tento měsíc: příjmy {_fmt_num(income)} Kč, výdaje {_fmt_num(expenses)} Kč; "
        f"celková bilance {_fmt_num(total_income - total_expenses)} Kč"
    ]


def _reminder_lines(db: Session, local_now: datetime) -> list[str]:
    """Aktivní připomínky: zazněné + nejbližší do 48 h (pražský čas)."""
    from models import Reminder
    from time_utils import to_local

    now_utc = local_now.astimezone(timezone.utc).replace(tzinfo=None)
    horizon = now_utc + timedelta(hours=48)
    rows = db.query(Reminder).filter(Reminder.status.in_(("scheduled", "fired"))).all()

    def due(r):
        return r.snoozed_until if r.snoozed_until is not None and r.snoozed_until < r.due_at else r.due_at

    fired = [r for r in rows if r.status == "fired" or due(r) <= now_utc]
    upcoming = sorted((r for r in rows if r not in fired and due(r) <= horizon), key=due)

    def fmt(r):
        t = to_local(due(r))
        return f"{_short(r.title, 40)} {_WEEKDAYS[t.weekday()]} {t:%d.%m. %H:%M}"

    return [f"Připomínky: zazněné {_list_or_none([_short(r.title, 40) for r in fired[:MAX_ITEMS]], len(fired))}; "
            f"do 48 h {_list_or_none([fmt(r) for r in upcoming[:MAX_ITEMS]], len(upcoming))}"]


def _wot_lines(db: Session) -> list[str]:
    resources = ", ".join(f"{r.resource} {_fmt_num(float(r.amount or 0))}" for r in db.query(WotResource).all())
    grinds = [g for g in db.query(WotGrind).all() if (g.status or "").lower() == "active"]
    grinds.sort(key=lambda g: _PRIORITY_RANK.get((g.priority or "").lower(), 3))
    grind_items = [f"{_short(g.tank, 25)} {_fmt_num(float(g.xp_remaining or 0))} XP ({g.priority})" for g in grinds[:MAX_ITEMS]]
    return [f"WoT zdroje: {resources or 'žádné'}", f"WoT aktivní grindy: {_list_or_none(grind_items, len(grinds))}"]


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


def build_current_context(
    db: Session,
    message: str,
    *,
    now_utc: datetime | None = None,
    target_tokens: int = CONTEXT_TARGET_TOKENS,
    max_tokens: int = CONTEXT_MAX_TOKENS,
) -> CurrentContext:
    local = now_local(now_utc)
    today = local.date()
    projects = [p for (p,) in db.query(WorkSession.project).distinct().all() if p]
    tanks = [t for (t,) in db.query(WotGrind.tank).all() if t]
    areas = classify_areas(message, projects, tanks)
    planner_like = is_planner_like(message)

    tomorrow = today + timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    header = [
        f"Dnes {today.isoformat()} ({_WEEKDAYS[today.weekday()]}) {local:%H:%M}; zítra {tomorrow.isoformat()} "
        f"({_WEEKDAYS[tomorrow.weekday()]}); tento týden {monday.isoformat()} až {(monday + timedelta(days=6)).isoformat()}"
    ]
    builders = {
        AREA_SCHOOL: lambda: _school_lines(db, today),
        AREA_NOTIFICATIONS: lambda: _notification_lines(db),
        AREA_GOALS: lambda: _goal_lines(db, today),
        AREA_WORK: lambda: _work_lines(db, today),
        AREA_FINANCE: lambda: _finance_lines(db, today),
        AREA_WOT: lambda: _wot_lines(db),
        AREA_REMINDERS: lambda: _reminder_lines(db, local),
    }
    # Explicitně zmíněné oblasti první → při ořezu rozpočtu se odebírají až nakonec.
    explicit = classify_areas(message, projects, tanks, implied=False)
    ordered = sorted((k for k in _AREA_SECTIONS_ORDER if k in areas), key=lambda k: k not in explicit)
    sections = [(key, builders[key]()) for key in ordered]

    memories = rank_memories(db.query(Memory).filter(Memory.active.is_(True)).all(), message, areas, planner=planner_like)
    memory_lines = [f"- [{m.area}/{m.category}] {_short(m.content, MEMORY_CHARS)}" for m in memories]
    memory_checked = planner_like or bool(memory_lines)

    if not sections and not memory_lines:
        # Neznámý / obecný dotaz: jen datum (malý obecný souhrn), žádná data modulů.
        text = _render(header, [], [])
        return CurrentContext(text, ("date",), frozenset(), estimate_tokens(text), areas)

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
    covered = {tool for key in included for tool in _COVERED_TOOLS[key]}
    if memory_checked and (memory_lines or planner_like):
        covered |= set(_COVERED_TOOLS[AREA_MEMORY])
    section_names = ("date", *included, *(("memory",) if memory_lines else ()))
    return CurrentContext(text, section_names, frozenset(covered), estimate_tokens(text), areas, _split_memory(text))
