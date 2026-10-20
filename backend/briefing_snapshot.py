"""Deterministický zdrojový snímek pro Denní přehled (Roadmap 3.0 Phase F).

Sestaví se z reálných dat PŘED voláním LLM, bez historie konverzace a bez toolů. Každá položka má odkaz
`ref` („assignment:12", „reminder:5"…), takže LLM smí jen vybírat a řadit – ne vymýšlet úkoly.
Sekce: today (dnes), overdue (po termínu), soon (brzy), goals, attention (upozornění), changes (co se změnilo
od minulého přehledu). Velikost hlídají stropy položek a tokenů.
Finance tu není ani nepřímo (MRK-60: do LLM nejde – finance_ai_policy.py).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from goal_history_service import compute_goal_progress_and_value
from llm_budget import estimate_tokens
from finance_ai_policy import is_finance_activity, is_finance_goal, is_finance_notification
from models import ActivityLog, Assignment, Exam, Goal, Notification, Reminder
from statuses import ASSIGNMENT_DONE_STATUSES, EXAM_OPEN_STATUSES, GOAL_INACTIVE_STATUSES, REMINDER_ACTIVE_STATUSES
from time_utils import local_day_bounds_utc, to_local
from text_utils import WEEKDAYS_CZ_SHORT, clip

SECTION_ORDER = ("today", "overdue", "soon", "attention", "goals", "changes")
SECTION_TITLES = {
    "today": "DNES",
    "overdue": "PO TERMÍNU / NEVYŘÍZENÉ",
    "soon": "BRZY",
    "attention": "UPOZORNĚNÍ",
    "goals": "CÍLE",
    "changes": "ZMĚNY OD MINULÉHO PŘEHLEDU",
}
SECTION_CAPS = {"today": 6, "overdue": 6, "soon": 6, "attention": 3, "goals": 3, "changes": 4}
# Při ořezu na rozpočet se bere od konce: nejdřív změny, cíle…
TRIM_ORDER = ("changes", "goals", "attention", "soon", "overdue", "today")
MAX_SNAPSHOT_TOKENS = 1200
SOON_DAYS = 7
EXAM_SOON_DAYS = 14
GOAL_SOON_DAYS = 14
LABEL_CHARS = 70

_DONE = ASSIGNMENT_DONE_STATUSES  # kanonické stavy: statuses.py
_EXAM_OPEN = EXAM_OPEN_STATUSES
_GOAL_INACTIVE = GOAL_INACTIVE_STATUSES
_ATTENTION_TYPES = ("goal_stagnation", "work_behind")
_WEEKDAYS = WEEKDAYS_CZ_SHORT
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Technický audit bez hodnoty pro člověka (sekce „změny"): automatické vedlejší zápisy a provoz.
_NOISE_AREAS = {"ai", "system", "auth", "backup", "scheduler", "maintenance", "migration"}
_NOISE_ACTIONS = {"snapshot", "sync", "sync_to_finance", "error", "cleanup", "maintenance", "migration",
                  "migrate", "backup", "restore", "seed", "purge"}
_NOISE_CONTEXTS = {"test", "unit_test", "tests", "cleanup", "maintenance", "migration", "system", "scheduler",
                   "verify", "verification", "seed"}
_NOISE_SUMMARY = re.compile(r"\[(?:test|verify|verification|e2e|qa)\]|__test|\btest[ _-]?cleanup\b", re.I)


def _is_noise(log: ActivityLog) -> bool:
    ctx = (log.user_context or "").strip().lower()
    return ((log.area or "").lower() in _NOISE_AREAS
            or (log.action_type or "").lower() in _NOISE_ACTIONS
            or ctx in _NOISE_CONTEXTS or ctx.startswith("test")
            or bool(_NOISE_SUMMARY.search(log.summary or "")))


def meaningful_activity(logs: list[ActivityLog]) -> list[ActivityLog]:
    """Jen změny, které člověka zajímají. Záznam vytvořený i smazaný v rámci okna (typicky úklid po testu
    / ověřování) nemá čistý dopad → vypadnou oba. Smazání ani úprava existujících dat se neskrývá."""
    kept = [lg for lg in logs if not _is_noise(lg)]
    created = {(lg.entity_type, lg.entity_id) for lg in kept if lg.action_type == "create" and lg.entity_id is not None}
    deleted = {(lg.entity_type, lg.entity_id) for lg in kept if lg.action_type == "delete" and lg.entity_id is not None}
    transient = created & deleted
    return [lg for lg in kept if (lg.entity_type, lg.entity_id) not in transient]


def _short(text, limit: int = LABEL_CHARS) -> str:
    return clip(text, limit)


def _day_label(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "dnes"
    if delta == 1:
        return "zítra"
    if delta == -1:
        return "včera"
    return f"{_WEEKDAYS[d.weekday()]} {d.day}. {d.month}."


@dataclass
class Item:
    ref: str
    kind: str
    label: str
    when: str = ""
    date: str | None = None
    url: str = "/"
    detail: str = ""
    new: bool = False

    def line(self) -> str:
        parts = [f"[{self.ref}] {self.label}"]
        if self.when:
            parts.append(self.when)
        if self.detail:
            parts.append(self.detail)
        if self.new:
            parts.append("NOVÉ")
        return " · ".join(parts)

    def as_dict(self) -> dict:
        return {"ref": self.ref, "kind": self.kind, "label": self.label, "when": self.when, "date": self.date,
                "url": self.url, "detail": self.detail, "new": self.new}


@dataclass
class Snapshot:
    date: date
    weekday: str
    sections: dict[str, list[Item]] = field(default_factory=dict)
    changes_summary: str = ""

    def items(self) -> list[Item]:
        return [i for s in SECTION_ORDER for i in self.sections.get(s, [])]

    def by_ref(self) -> dict[str, Item]:
        return {i.ref: i for i in self.items()}

    @property
    def refs(self) -> list[str]:
        return sorted({i.ref for i in self.items() if not i.ref.startswith("activity:")})

    @property
    def is_quiet(self) -> bool:
        return not any(self.sections.get(s) for s in ("today", "overdue", "soon", "attention"))

    def render(self) -> str:
        lines = [f"DATUM: {self.date.isoformat()} ({self.weekday}), Europe/Prague"]
        for key in SECTION_ORDER:
            items = self.sections.get(key) or []
            if key == "changes" and self.changes_summary:
                lines.append(f"{SECTION_TITLES[key]}: {self.changes_summary}")
            elif items:
                lines.append(SECTION_TITLES[key])
            if not items:
                continue
            lines.extend(f"- {i.line()}" for i in items)
        if self.is_quiet:
            lines.append("(Žádné termíny, nevyřízené ani blížící se položky.)")
        return "\n".join(lines)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.render())

    def source_hash(self) -> str:
        canonical = json.dumps([[k, [i.as_dict() for i in self.sections.get(k, [])]] for k in SECTION_ORDER],
                               ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {"date": self.date.isoformat(), "quiet": self.is_quiet,
                "sections": {k: [i.as_dict() for i in self.sections.get(k, [])] for k in SECTION_ORDER},
                "changes_summary": self.changes_summary}


def _subject(obj) -> str:
    s = getattr(obj, "subject", None)
    return f" ({_short(s.name, 25)})" if s is not None else ""


def _reminder_due(r: Reminder) -> datetime:
    return r.snoozed_until if r.snoozed_until is not None and r.snoozed_until < r.due_at else r.due_at


def build_snapshot(
    db: Session,
    now_utc: datetime,
    *,
    previous_refs: set[str] | None = None,
    changes_since: datetime | None = None,
    max_tokens: int = MAX_SNAPSHOT_TOKENS,
) -> Snapshot:
    local = to_local(now_utc)
    today = local.date()
    sections: dict[str, list[Item]] = {k: [] for k in SECTION_ORDER}
    day_start, day_end = local_day_bounds_utc(today)

    # --- škola: úkoly ---
    for a in db.query(Assignment).filter(Assignment.due_date.isnot(None)).all():
        if (a.status or "").strip().lower() in _DONE:
            continue
        delta = (a.due_date - today).days
        prio = (a.priority or "medium").lower()
        item = Item(f"assignment:{a.id}", "assignment", _short(f"{a.title}{_subject(a)}"),
                    f"termín {_day_label(a.due_date, today)}", a.due_date.isoformat(), "/school",
                    f"priorita {prio}" if prio == "high" else "")
        if delta < 0:
            sections["overdue"].append(item)
        elif delta == 0:
            sections["today"].append(item)
        elif delta <= SOON_DAYS:
            sections["soon"].append(item)

    # --- škola: zkoušky ---
    for e in db.query(Exam).filter(Exam.exam_date.isnot(None)).all():
        if (e.status or "").strip().lower() not in _EXAM_OPEN:
            continue
        delta = (e.exam_date - today).days
        if delta < 0 or delta > EXAM_SOON_DAYS:
            continue
        item = Item(f"exam:{e.id}", "exam", _short(f"{e.title}{_subject(e)}"),
                    f"zkouška {_day_label(e.exam_date, today)}", e.exam_date.isoformat(), "/school")
        sections["today" if delta == 0 else "soon"].append(item)

    # --- připomínky ---
    for r in db.query(Reminder).filter(Reminder.status.in_(REMINDER_ACTIVE_STATUSES)).all():
        due = _reminder_due(r)
        t = to_local(due)
        when = f"{_day_label(t.date(), today)} {t:%H:%M}"
        item = Item(f"reminder:{r.id}", "reminder", _short(r.title), f"připomínka {when}", t.date().isoformat(),
                    "/reminders")
        if r.status == "fired" or due <= now_utc:
            item.when = f"připomínka zazněla {when}, nevyřízená"
            sections["overdue"].append(item)
        elif due < day_end:
            sections["today"].append(item)
        elif due < now_utc + timedelta(hours=48):
            sections["soon"].append(item)

    # --- cíle ---
    active_goals = [g for g in db.query(Goal).all() if (g.status or "").strip().lower() not in _GOAL_INACTIVE
                    and not is_finance_goal(g.source)]
    for g in active_goals:
        if g.target_date is None:
            continue
        delta = (g.target_date - today).days
        progress, _ = compute_goal_progress_and_value(db, g, today=today)
        item = Item(f"goal:{g.id}", "goal", _short(g.title), f"cíl do {_day_label(g.target_date, today)}",
                    g.target_date.isoformat(), "/goals", f"{progress} %")
        if delta < 0:
            sections["overdue"].append(item)
        elif delta <= GOAL_SOON_DAYS:
            sections["soon"].append(item)
    listed = {i.ref for s in ("overdue", "soon") for i in sections[s]}
    for g in sorted(active_goals, key=lambda g: (_PRIORITY_RANK.get((g.priority or "").lower(), 3),
                                                 g.target_date or date.max, g.id)):
        ref = f"goal:{g.id}"
        if ref in listed or (g.priority or "").lower() != "high":
            continue
        progress, current = compute_goal_progress_and_value(db, g, today=today)
        sections["goals"].append(Item(ref, "goal", _short(g.title), "", None, "/goals", f"{progress} %"))

    # --- upozornění (jen typy, které nejsou duplicitou termínů výše) ---
    for n in (db.query(Notification)
              .filter(Notification.resolved == False, Notification.notification_type.in_(_ATTENTION_TYPES))  # noqa: E712
              .order_by(Notification.created_at.desc()).all()):
        if is_finance_notification(n.area, n.notification_type):
            continue
        sections["attention"].append(Item(f"notification:{n.id}", "notification", _short(n.title), "",
                                          None, n.action_url or "/", n.severity or ""))

    # --- změny od minulého přehledu ---
    since = changes_since or (now_utc - timedelta(hours=24))
    logs = meaningful_activity(db.query(ActivityLog)
                               .filter(ActivityLog.timestamp >= since)
                               .order_by(ActivityLog.timestamp.desc()).all())
    logs = [lg for lg in logs if not is_finance_activity(lg.area, lg.entity_type)]
    counts: dict[str, int] = {}
    for lg in logs:
        counts[lg.area] = counts.get(lg.area, 0) + 1
    changes_summary = ", ".join(f"{n}× {area}" for area, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    for lg in logs:
        sections["changes"].append(Item(f"activity:{lg.id}", "activity", _short(lg.summary, 60), "", None,
                                        "/activity"))

    # --- řazení, „nové", stropy ---
    def sort_key(i: Item):
        return (i.date or "9999", i.ref)

    for key in ("today", "overdue", "soon"):
        sections[key].sort(key=sort_key)
    if previous_refs is not None:
        for key in ("today", "overdue", "soon", "attention"):
            for i in sections[key]:
                i.new = i.ref not in previous_refs
    for key, cap in SECTION_CAPS.items():
        sections[key] = sections[key][:cap]

    snap = Snapshot(today, _WEEKDAYS[today.weekday()], sections, changes_summary)
    # Rozpočet tokenů: ubírat od nejméně důležitých sekcí.
    for key in TRIM_ORDER:
        while snap.tokens > max_tokens and snap.sections[key]:
            snap.sections[key].pop()
        if key == "changes" and snap.tokens > max_tokens:
            snap.changes_summary = ""
        if snap.tokens <= max_tokens:
            break
    return snap
