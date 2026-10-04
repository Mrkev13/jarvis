"""Režim Dnes (Roadmap 4G) – „Co dnes potřebuje moji pozornost?" Deterministicky, bez LLM, jen čtení.

GET /today skládá EXISTUJÍCÍ zdroje (žádná nová business pravidla):
- časová osa: připomínky, zkoušky a úkoly s termínem v pražském dni D (00:00–24:00 Europe/Prague, DST přes time_utils);
- pozornost: po termínu (úkoly, zkoušky, nevyřízené připomínky z dřívějška) + neřešená nepřečtená upozornění
  (stejná sémantika jako karta „Vyžaduje pozornost" na Řídicím centru);
- dnešní plán: akce denního plánovače (planner_service.generate_plan – stejný výpočet jako /planner a /dashboard);
- potom: nejbližší termíny v dalších 7 dnech (max. 3).

Deduplikace podle záznamu (`ref` = „assignment:12"): každý záznam je jen v JEDNÉ sekci s pořadím
časová osa > pozornost > plán > potom. Informace z vyšších sekcí se nezahodí – položka dostane značku
(priorita z plánu, závažnost z upozornění). Každá sekce se počítá zvlášť: chyba jednoho zdroje = `errors[sekce]`,
ostatní sekce se vrátí normálně.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

import reminder_service as rs
from models import Assignment, Exam, Reminder, Subject
from notifications_service import list_notifications
from planner_service import generate_plan
from statuses import is_assignment_done, is_exam_open, norm
from text_utils import format_date_cz
from time_utils import local_day_bounds_utc, now_local, to_local, utc_now

log = logging.getLogger(__name__)

WEEKDAYS_CZ = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
MAX_ATTENTION = 8
MAX_UPCOMING = 3
UPCOMING_DAYS = 7
SEVERITY_RANK = {"important": 0, "warning": 1, "info": 2}

SECTION_ERRORS = {
    "timeline": "Dnešní termíny se nepodařilo načíst.",
    "attention": "Položky k vyřízení se nepodařilo načíst.",
    "priorities": "Dnešní plán se nepodařilo sestavit.",
    "upcoming": "Další termíny se nepodařilo načíst.",
}


@dataclass
class TodayItem:
    """Normalizovaná položka (jen pro režim Dnes – žádný univerzální model entit)."""
    id: str                      # ref záznamu „reminder:5" / u upozornění bez záznamu „notification:9"
    type: str                    # reminder | exam | assignment | planner | notification
    title: str
    subtitle: str = ""
    area: str | None = None
    date: str | None = None      # pražské datum (ISO)
    time: str | None = None      # pražský čas „HH:MM" nebo None (celý den)
    status: str = "open"         # upcoming | due | past | done | overdue | open
    priority: int | None = None  # pořadí z denního plánu
    severity: str | None = None  # important | warning | info (upozornění)
    href: str | None = None
    source_id: int | None = None
    # Roadmap 4H: co jde udělat přímo z řádku (jen id akcí, žádné URL ani příkazy):
    # complete (připomínka / úkol), snooze (připomínka), record_result (zkouška → otevřít záznam).
    actions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Ctx:
    db: Session
    now_utc: datetime
    today: date
    now_local_naive: datetime
    subjects: dict[int, str] = field(default_factory=dict)


def _subject_names(db: Session) -> dict[int, str]:
    return {s.id: s.name for s in db.query(Subject).all()}


def _school_subtitle(kind: str, subject: str | None, extra: str | None = None) -> str:
    return " · ".join(x for x in (kind, subject, extra) if x)


def _exam_kind(exam_type: str | None) -> str:
    return {"test": "Test", "quiz": "Kvíz", "colloquium": "Kolokvium", "midterm": "Průběžný test", "oral": "Ústní zkouška"}.get(
        norm(exam_type), "Zkouška")


# ---------- akce (Roadmap 4H) ----------

def _reminder_actions(r: Reminder, rung: bool) -> list[str]:
    """Hotovo / odložit jen u aktivní JEDNORÁZOVÉ připomínky: u opakované „hotovo" výskyt neposune
    (reminder_service.complete) a odložení mění jen jeden výskyt – to patří na stránku Připomínky.

    Odložit jen u připomínky, která už zazněla (`rung`): snooze_target počítá „+N min" od TEĎ, takže
    u budoucí připomínky (21:00, klik v 10:39, +1 h → 11:39) by „odložení" termín naopak přiblížilo."""
    if r.status not in ("scheduled", "fired") or r.recurrence != "none":
        return []
    return ["complete", "snooze"] if rung else ["complete"]


def snooze_options(today: date) -> list[dict]:
    """Pevné volby odložení; „zítra" = další pražský kalendářní den v 08:00 (i těsně po půlnoci)."""
    return [
        {"id": "15m", "label": "+15 min", "minutes": 15},
        {"id": "1h", "label": "+1 h", "minutes": 60},
        {"id": "3h", "label": "+3 h", "minutes": 180},
        {"id": "tomorrow", "label": "Zítra 8:00", "until_local": f"{(today + timedelta(days=1)).isoformat()}T08:00"},
    ]


# ---------- časová osa ----------

def _reminder_items_today(c: _Ctx) -> list[TodayItem]:
    start, end = local_day_bounds_utc(c.today)
    items: list[TodayItem] = []
    rows = c.db.query(Reminder).filter(Reminder.status.in_(("scheduled", "fired", "done"))).all()
    for r in rows:
        when = rs.effective_due(r) if r.status in ("scheduled", "fired") else r.due_at
        if start <= when < end:
            local = to_local(when)
            if r.status == "done":
                status = "done"
            elif r.status == "fired" or when <= c.now_utc:
                status = "due"  # zaznělo, čeká na vyřízení
            else:
                status = "upcoming"
            items.append(TodayItem(
                id=f"reminder:{r.id}", type="reminder", title=r.title,
                subtitle="Připomínka" + (f" · {rs.describe_recurrence(r)}" if r.recurrence != "none" else ""),
                area="reminders", date=local.date().isoformat(), time=f"{local:%H:%M}", status=status,
                href=f"/reminders?reminder={r.id}", source_id=r.id, actions=_reminder_actions(r, rung=status == "due"),
            ))
        elif r.recurrence != "none" and r.last_fired_at is not None and start <= r.last_fired_at < end:
            # opakovaná připomínka dnes už zazněla (due_at se posunul na další výskyt) – proběhlo
            local = to_local(r.last_fired_at)
            items.append(TodayItem(
                id=f"reminder:{r.id}", type="reminder", title=r.title,
                subtitle=f"Připomínka · {rs.describe_recurrence(r)}", area="reminders",
                date=local.date().isoformat(), time=f"{local:%H:%M}", status="past",
                href=f"/reminders?reminder={r.id}", source_id=r.id,
            ))
    return items


def _school_items_today(c: _Ctx) -> list[TodayItem]:
    items: list[TodayItem] = []
    for e in c.db.query(Exam).filter(Exam.exam_date == c.today).all():
        items.append(TodayItem(
            id=f"exam:{e.id}", type="exam", title=e.title,
            subtitle=_school_subtitle(_exam_kind(e.exam_type), c.subjects.get(e.subject_id)),
            area="school", date=c.today.isoformat(), status="open" if is_exam_open(e.status) else "done",
            href=f"/school?exam={e.id}", source_id=e.id,
        ))
    for a in c.db.query(Assignment).filter(Assignment.due_date == c.today).all():
        items.append(TodayItem(
            id=f"assignment:{a.id}", type="assignment", title=a.title,
            subtitle=_school_subtitle("Úkol · termín dnes", c.subjects.get(a.subject_id)),
            area="school", date=c.today.isoformat(), status="done" if is_assignment_done(a.status) else "open",
            href=f"/school?assignment={a.id}", source_id=a.id, actions=[] if is_assignment_done(a.status) else ["complete"],
        ))
    return items


def timeline_sort_key(item: TodayItem) -> tuple:
    """Hotové dospod; s časem chronologicky; bez času („Během dne") za nimi; pak název."""
    return (item.status == "done", item.time is None, item.time or "", item.title.lower())


def build_timeline(c: _Ctx) -> list[TodayItem]:
    items = _reminder_items_today(c) + _school_items_today(c)
    return sorted(items, key=timeline_sort_key)


# ---------- pozornost ----------

def _overdue_items(c: _Ctx) -> list[TodayItem]:
    start, _ = local_day_bounds_utc(c.today)
    items: list[TodayItem] = []
    for a in c.db.query(Assignment).filter(Assignment.due_date.is_not(None), Assignment.due_date < c.today).all():
        if is_assignment_done(a.status):
            continue
        items.append(TodayItem(
            id=f"assignment:{a.id}", type="assignment", title=a.title,
            subtitle=_school_subtitle("Úkol po termínu", c.subjects.get(a.subject_id), f"termín {format_date_cz(a.due_date)}"),
            area="school", date=a.due_date.isoformat(), status="overdue", severity="important",
            href=f"/school?assignment={a.id}", source_id=a.id, actions=["complete"],
        ))
    for e in c.db.query(Exam).filter(Exam.exam_date.is_not(None), Exam.exam_date < c.today).all():
        if not is_exam_open(e.status):
            continue
        items.append(TodayItem(
            id=f"exam:{e.id}", type="exam", title=e.title,
            subtitle=_school_subtitle(f"{_exam_kind(e.exam_type)} proběhla – zapiš výsledek", c.subjects.get(e.subject_id),
                                      format_date_cz(e.exam_date)),
            area="school", date=e.exam_date.isoformat(), status="overdue", severity="warning",
            href=f"/school?exam={e.id}", source_id=e.id, actions=["record_result"],
        ))
    for r in c.db.query(Reminder).filter(Reminder.status == "fired").all():
        if r.due_at >= start:
            continue  # dnešní je na časové ose
        local = to_local(r.due_at)
        items.append(TodayItem(
            id=f"reminder:{r.id}", type="reminder", title=r.title,
            subtitle=f"Nevyřízená připomínka · {format_date_cz(local.date())} {local:%H:%M}", area="reminders",
            date=local.date().isoformat(), time=f"{local:%H:%M}", status="overdue", severity="warning",
            href=f"/reminders?reminder={r.id}", source_id=r.id, actions=_reminder_actions(r, rung=True),
        ))
    return items


def _closed_refs(c: _Ctx) -> set[str]:
    """Ref záznamů, které už nic nepotřebují: hotové úkoly, uzavřené zkoušky, neaktivní připomínky."""
    refs = {f"assignment:{a.id}" for a in c.db.query(Assignment.id, Assignment.status).all() if is_assignment_done(a.status)}
    refs |= {f"exam:{e.id}" for e in c.db.query(Exam.id, Exam.status).all() if not is_exam_open(e.status)}
    refs |= {f"reminder:{r.id}" for r in c.db.query(Reminder.id).filter(Reminder.status.in_(("done", "cancelled"))).all()}
    return refs


def _notification_ref(n: dict) -> str | None:
    st, sid = n.get("source_type"), n.get("source_id")
    return f"{st}:{sid}" if st in ("assignment", "exam", "reminder", "goal") and sid is not None else None


def _safe_href(url) -> str | None:
    return url if isinstance(url, str) and url.startswith("/") and not url.startswith("//") else None


def build_attention(c: _Ctx) -> tuple[list[TodayItem], dict[str, str]]:
    """(položky, závažnost podle ref z upozornění) – upozornění k záznamu se spojí s jeho položkou."""
    items = {it.id: it for it in _overdue_items(c)}
    severity_by_ref: dict[str, str] = {}
    closed = _closed_refs(c)
    for n in list_notifications(c.db, unread_only=True, include_resolved=False, now=c.now_utc):
        sev = norm(n.get("severity")) or "info"
        ref = _notification_ref(n)
        if ref in closed:
            # Roadmap 4H: záznam je už vyřízený (např. právě dokončený z Dnes) – upozornění by do dalšího běhu
            # generate_notifications jen strašilo. Stejné pravidlo jako _resolve_if_no_longer_relevant, jen čtením.
            continue
        if ref:
            prev = severity_by_ref.get(ref)
            if prev is None or SEVERITY_RANK.get(sev, 3) < SEVERITY_RANK.get(prev, 3):
                severity_by_ref[ref] = sev
            if ref in items:
                continue
        key = ref or f"notification:{n['id']}"
        if key in items:
            continue
        items[key] = TodayItem(
            id=key, type="notification", title=n.get("title") or "", subtitle=n.get("message") or "",
            area=n.get("area"), status="open", severity=sev, href=_safe_href(n.get("action_url")), source_id=n.get("id"),
        )
    for ref, sev in severity_by_ref.items():
        if ref in items and SEVERITY_RANK.get(sev, 3) < SEVERITY_RANK.get(items[ref].severity or "", 3):
            items[ref].severity = sev
    ordered = sorted(items.values(), key=lambda it: (SEVERITY_RANK.get(it.severity or "", 3), it.date or "9999", it.title.lower()))
    return ordered, severity_by_ref


# ---------- plán, potom ----------

def _ref_href(ref: str | None) -> str | None:
    if not ref:
        return None
    kind, _, rid = ref.partition(":")
    return {"assignment": f"/school?assignment={rid}", "exam": f"/school?exam={rid}", "goal": f"/goals?goal={rid}"}.get(kind)


def build_priorities(c: _Ctx) -> list[TodayItem]:
    plan = generate_plan(c.db, mode="daily", today=c.today)
    items = []
    for a in plan.get("actions") or []:
        ref = a.get("ref")
        items.append(TodayItem(
            id=ref or f"planner:{a.get('priority')}", type="planner", title=a.get("title") or "",
            subtitle=a.get("reason") or "", area=a.get("area"), status="open", priority=int(a.get("priority") or 0) or None,
            href=_ref_href(ref) or "/planner", source_id=int(ref.split(":")[1]) if ref else None,
            actions=["complete"] if ref and ref.startswith("assignment:") else [],
        ))
    return items


def build_upcoming(c: _Ctx) -> list[TodayItem]:
    first, last = c.today + timedelta(days=1), c.today + timedelta(days=UPCOMING_DAYS)
    items: list[TodayItem] = []
    for e in c.db.query(Exam).filter(Exam.exam_date >= first, Exam.exam_date <= last).all():
        if is_exam_open(e.status):
            items.append(TodayItem(
                id=f"exam:{e.id}", type="exam", title=e.title,
                subtitle=_school_subtitle(_exam_kind(e.exam_type), c.subjects.get(e.subject_id)), area="school",
                date=e.exam_date.isoformat(), status="upcoming", href=f"/school?exam={e.id}", source_id=e.id,
            ))
    for a in c.db.query(Assignment).filter(Assignment.due_date >= first, Assignment.due_date <= last).all():
        if not is_assignment_done(a.status):
            items.append(TodayItem(
                id=f"assignment:{a.id}", type="assignment", title=a.title,
                subtitle=_school_subtitle("Úkol", c.subjects.get(a.subject_id)), area="school",
                date=a.due_date.isoformat(), status="upcoming", href=f"/school?assignment={a.id}", source_id=a.id,
            ))
    _, end_today = local_day_bounds_utc(c.today)
    _, end_last = local_day_bounds_utc(last)
    for r in c.db.query(Reminder).filter(Reminder.status == "scheduled").all():
        when = rs.effective_due(r)
        if end_today <= when < end_last:
            local = to_local(when)
            items.append(TodayItem(
                id=f"reminder:{r.id}", type="reminder", title=r.title, subtitle="Připomínka", area="reminders",
                date=local.date().isoformat(), time=f"{local:%H:%M}", status="upcoming",
                href=f"/reminders?reminder={r.id}", source_id=r.id,
            ))
    return sorted(items, key=lambda it: (it.date or "", it.time or "99:99", it.title.lower()))


# ---------- skladba ----------

def dedupe(timeline: list[TodayItem], attention: list[TodayItem], priorities: list[TodayItem],
           upcoming: list[TodayItem], severity_by_ref: dict[str, str] | None = None) -> dict[str, list[TodayItem]]:
    """Každý záznam v jedné sekci: časová osa > pozornost > plán > potom. Značky se přenesou na ponechanou položku."""
    severity_by_ref = severity_by_ref or {}
    shown: dict[str, TodayItem] = {}
    out: dict[str, list[TodayItem]] = {}
    for name, items in (("timeline", timeline), ("attention", attention), ("priorities", priorities), ("upcoming", upcoming)):
        kept = []
        for it in items:
            if it.id in shown:
                keeper = shown[it.id]
                if it.priority and not keeper.priority:
                    keeper.priority = it.priority
                continue
            if name == "timeline" and it.id in severity_by_ref and it.status != "done":
                it.severity = severity_by_ref[it.id]
            shown[it.id] = it
            kept.append(it)
        out[name] = kept
    out["upcoming"] = out["upcoming"][:MAX_UPCOMING]
    out["attention"] = out["attention"][:MAX_ATTENTION]
    return out


def next_item(timeline: list[TodayItem], now_local_naive: datetime) -> tuple[TodayItem | None, int | None]:
    """Nejbližší položka s časem, která ještě nenastala (minuty od teď), jinak (None, None)."""
    hhmm = f"{now_local_naive:%H:%M}"
    for it in timeline:
        if it.time and it.status == "upcoming" and it.time > hhmm:
            h, m = map(int, it.time.split(":"))
            at = now_local_naive.replace(hour=h, minute=m, second=0, microsecond=0)
            return it, max(0, int((at - now_local_naive).total_seconds() // 60))
    return None, None


def date_label(d: date) -> str:
    return f"{WEEKDAYS_CZ[d.weekday()]} {format_date_cz(d)}"


def build_today(db: Session, now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or utc_now()
    local_now = now_local(now_utc)
    c = _Ctx(db=db, now_utc=now_utc, today=local_now.date(), now_local_naive=local_now.replace(tzinfo=None))
    errors: dict[str, str] = {}
    try:
        c.subjects = _subject_names(db)
    except Exception:  # noqa: BLE001 – bez názvů předmětů se dá pokračovat
        log.exception("today: subjects")

    def section(name, fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001 – jeden zdroj nesmí shodit celou stránku
            log.exception("today: section %s failed", name)
            db.rollback()
            errors[name] = SECTION_ERRORS[name]
            return default

    timeline = section("timeline", lambda: build_timeline(c), [])
    attention, severity_by_ref = section("attention", lambda: build_attention(c), ([], {}))
    priorities = section("priorities", lambda: build_priorities(c), [])
    upcoming = section("upcoming", lambda: build_upcoming(c), [])
    sections = dedupe(timeline, attention, priorities, upcoming, severity_by_ref)

    nxt, minutes = next_item(sections["timeline"], c.now_local_naive)
    remaining = sum(1 for it in sections["timeline"] if it.status in ("upcoming", "due", "open"))
    return {
        "date": c.today.isoformat(),
        "date_label": date_label(c.today),
        "now_local": f"{c.now_local_naive:%H:%M}",
        "summary": {
            "remaining": remaining,
            "done": sum(1 for it in sections["timeline"] if it.status in ("done", "past")),
            "attention": len(sections["attention"]),
            "next": {**nxt.as_dict(), "minutes_until": minutes} if nxt else None,
        },
        "timeline": [it.as_dict() for it in sections["timeline"]],
        "attention": [it.as_dict() for it in sections["attention"]],
        "priorities": [it.as_dict() for it in sections["priorities"]],
        "upcoming": [it.as_dict() for it in sections["upcoming"]],
        "snooze_options": snooze_options(c.today),
        "errors": errors,
    }
