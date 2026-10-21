"""Příspěvky JÁDRA do globálních agregátorů (MRK-20): připomínky, paměť, upozornění.

Jádro není `ModuleDef` a nejde vypnout (docs/module-framework.md §5.1) – registr tyto příspěvky
(`CORE_INTEGRATIONS`) předává agregátorům vždy. Bloky jsou přesunuté beze změny chování ze
search_service / today_service / context_service / quick_add_service.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import quick_add_text as qt
import reminder_service as rs
from context_format import MAX_ITEMS, WEEKDAYS, list_or_none, short
from finance_ai_policy import is_finance_notification
from models import Memory, Notification, Reminder
from module_contracts import (
    TimelineItem, TimelineSource,
    ChangeSource, activity_changes,
    ContextRequest, ContextSection, EntityRef, ModuleIntegrations, QuickAddKind, QuickAddRule, SearchSource,
    TodaySource,
)
from statuses import REMINDER_ACTIVE_STATUSES
from text_utils import format_date_cz, join_parts
from time_utils import APP_TZ, local_day_bounds_utc, local_to_utc, now_local, to_local
from today_types import UPCOMING_DAYS, TodayItem

ROW_LIMIT = 500  # na tabulku (search_service.ROW_LIMIT)

# ---------- připomínky: vyhledávání ----------


def search_reminders(db, q):
    rows = db.query(Reminder).filter(Reminder.status.in_(REMINDER_ACTIVE_STATUSES)).order_by(Reminder.due_at).limit(ROW_LIMIT).all()
    for r in rows:
        when = rs.describe_recurrence(r) if r.recurrence != "none" else rs.format_local(r.due_at)
        yield "reminder", r.id, r.title, join_parts("Připomínka", when), f"{r.note or ''} pripominka", "reminders", f"/reminders?reminder={r.id}"


# ---------- paměť: vyhledávání ----------

_AREA = {"school": "Škola", "work": "Práce", "finance": "Finance", "wot": "World of Tanks", "mff": "Marvel FF",
         "personal": "Osobní", "fitness": "Fitness", "hobby": "Hobby", "travel": "Cestování", "general": "Obecné",
         "goals": "Cíle", "reminders": "Připomínky"}
_MEMORY_CATEGORY = {"context": "Kontext", "preference": "Preference", "plan": "Plán", "decision": "Rozhodnutí",
                    "routine": "Rutina", "constraint": "Omezení", "goal": "Cíl", "fact": "Fakt"}


def search_memories(db, q):
    for m in db.query(Memory).filter(Memory.active == True).limit(ROW_LIMIT).all():  # noqa: E712
        content = " ".join((m.content or "").split())
        title = content if len(content) <= 80 else content[:79].rstrip() + "…"
        cat = _MEMORY_CATEGORY.get((m.category or "").lower(), m.category or "")
        area = _AREA.get((m.area or "").lower(), m.area or "")
        yield "memory", m.id, title, join_parts("Paměť", cat, area), f"{cat} {area} pamet", "memory", f"/memory?memory={m.id}"


# ---------- připomínky: Dnes ----------


def _reminder_actions(r: Reminder, rung: bool) -> list[str]:
    """Hotovo / odložit jen u aktivní JEDNORÁZOVÉ připomínky: u opakované „hotovo" výskyt neposune
    (reminder_service.complete) a odložení mění jen jeden výskyt – to patří na stránku Připomínky.

    Odložit jen u připomínky, která už zazněla (`rung`): snooze_target počítá „+N min" od TEĎ, takže
    u budoucí připomínky (21:00, klik v 10:39, +1 h → 11:39) by „odložení" termín naopak přiblížilo."""
    if r.status not in ("scheduled", "fired") or r.recurrence != "none":
        return []
    return ["complete", "snooze"] if rung else ["complete"]


def today_reminders_timeline(c):
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


def today_reminders_overdue(c):
    start, _ = local_day_bounds_utc(c.today)
    items = []
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


def today_reminders_upcoming(c):
    last = c.today + timedelta(days=UPCOMING_DAYS)
    _, end_today = local_day_bounds_utc(c.today)
    _, end_last = local_day_bounds_utc(last)
    items = []
    for r in c.db.query(Reminder).filter(Reminder.status == "scheduled").all():
        when = rs.effective_due(r)
        if end_today <= when < end_last:
            local = to_local(when)
            items.append(TodayItem(
                id=f"reminder:{r.id}", type="reminder", title=r.title, subtitle="Připomínka", area="reminders",
                date=local.date().isoformat(), time=f"{local:%H:%M}", status="upcoming",
                href=f"/reminders?reminder={r.id}", source_id=r.id,
            ))
    return items


def today_reminders_closed(c) -> set[str]:
    return {f"reminder:{r.id}" for r in c.db.query(Reminder.id).filter(Reminder.status.in_(("done", "cancelled"))).all()}


# ---------- AI kontext ----------


def context_reminders(req: ContextRequest) -> list[str]:
    """Aktivní připomínky: zazněné + nejbližší do 48 h (pražský čas)."""
    now_utc = req.local_now.astimezone(timezone.utc).replace(tzinfo=None)
    horizon = now_utc + timedelta(hours=48)
    rows = req.db.query(Reminder).filter(Reminder.status.in_(REMINDER_ACTIVE_STATUSES)).all()

    def due(r):
        return r.snoozed_until if r.snoozed_until is not None and r.snoozed_until < r.due_at else r.due_at

    fired = [r for r in rows if r.status == "fired" or due(r) <= now_utc]
    upcoming = sorted((r for r in rows if r not in fired and due(r) <= horizon), key=due)

    def fmt(r):
        t = to_local(due(r))
        return f"{short(r.title, 40)} {WEEKDAYS[t.weekday()]} {t:%d.%m. %H:%M}"

    return [f"Připomínky: zazněné {list_or_none([short(r.title, 40) for r in fired[:MAX_ITEMS]], len(fired))}; "
            f"do 48 h {list_or_none([fmt(r) for r in upcoming[:MAX_ITEMS]], len(upcoming))}"]


def context_notifications(req: ContextRequest) -> list[str]:
    rows = (
        req.db.query(Notification)
        .filter(Notification.read.is_(False), Notification.resolved.is_(False), Notification.severity == "important")
        .order_by(Notification.created_at.desc())
        .all()
    )
    rows = [n for n in rows if not is_finance_notification(n.area, n.notification_type)]  # MRK-60
    return [f"Důležitá nepřečtená upozornění: {list_or_none([short(n.title, 60) for n in rows[:MAX_ITEMS]], len(rows))}"]


# ---------- Rychlé přidání: připomínka ----------

KW_REMINDER = re.compile(r"\b(pripomen\w*|pripominka|upozorni\w*|reminder|nezapomen\w*)\b")
DEFAULT_REMINDER_TIME = "09:00"


def detect_reminder_keyword(t) -> str | None:
    return "high" if KW_REMINDER.search(t.f) else None


def detect_reminder_time(t) -> str | None:
    """Relativní čas („za 2 hodiny") nebo čas bez částky („v 17:00") – s datem jisté, jinak střední jistota."""
    f = t.f
    relative = qt.RE_RELATIVE.search(f)
    if relative or (qt.RE_TIME.search(f) and not qt.RE_MONEY.search(f)):
        dated = qt.RE_DAYWORD.search(f) or qt.RE_WEEKDAY.search(f) or qt.RE_DATE.search(f) or qt.RE_ISO.search(f)
        return "high" if relative or dated else "medium"
    return None


def parse_reminder(t, d, now_utc: datetime, ctx: dict):
    local_now = now_local(now_utc)
    today = local_now.date()
    km = KW_REMINDER.search(t.f)
    if km:
        t.take(km)
    rel = qt.RE_RELATIVE.search(t.f)
    due: datetime | None = None
    if rel:
        t.take(rel)
        qty_raw, unit = rel.group(1), (rel.group(2) or "")
        qty = 0.5 if qty_raw == "pul" else 1.0 if qty_raw in ("hodinu", "minutu") else qt.num(qty_raw)
        minutes = qty if unit.startswith("min") or qty_raw == "minutu" else qty * 60
        if qty_raw == "hodinu" or (qty_raw == "pul" and not unit.startswith("min")):
            minutes = qty * 60
        due = (local_now + timedelta(minutes=minutes)).replace(second=0, microsecond=0, tzinfo=None)
    else:
        day = qt.find_date(t, today, d)
        starts = qt.RE_TIME.search(t.f)
        tm = qt.find_time(t, d)
        if tm and not km and starts and starts.group("prep") == "od":
            # událost s časem začátku – samostatný kalendář zatím není, uloží se jako připomínka v čas začátku
            d.warnings.append(f"Začátek v {tm} – uloží se jako připomínka na tento čas.")
        if d.errors:
            pass
        elif day is None and tm is None:
            d.need("due_local", "Kdy ti to mám připomenout?")
        else:
            if tm is None:
                tm = DEFAULT_REMINDER_TIME
                d.warnings.append(f"Čas nezadán – nastaveno {DEFAULT_REMINDER_TIME}.")
            if day is None:
                day = today
                if tm <= f"{local_now:%H:%M}":
                    day = today + timedelta(days=1)
                    d.warnings.append("Ten čas už dnes proběhl – nastaveno na zítra.")
            due = datetime.fromisoformat(f"{day.isoformat()}T{tm}")
    title = t.rest(KW_REMINDER)
    d.fields = {"title": title, "due_local": due.strftime("%Y-%m-%dT%H:%M") if due else ""}
    if not title:
        d.need("title", "Co ti mám připomenout?")
    if due and due <= local_now.replace(tzinfo=None):
        d.error("due_local", "Ten čas už proběhl.")


def reminder_tool_call(f: dict, d, today, now_utc, db) -> tuple[str, dict]:
    title = qt.required(f, d, "title", "Doplň, co připomenout.")
    due = qt.required(f, d, "due_local", "Doplň čas.")
    if due:
        try:
            local_due = datetime.fromisoformat(due[:16])
            if local_to_utc(local_due) <= now_utc:
                d.error("due_local", "Ten čas už proběhl.")
            elif (local_due.date() - today).days > 366:
                d.error("due_local", "Víc než rok dopředu.")
        except ValueError:
            d.error("due_local", "Neplatný čas.")
    return "add_reminder", {"title": title or "", "due_local": (due or "")[:16]}


def reminder_display(f: dict, ctx: dict, today) -> dict:
    sub = "Kdy? (doplň)"
    if f.get("due_local"):
        sub = qt.when_label(datetime.fromisoformat(f["due_local"]), today)
    return {"title": f.get("title") or "Připomínka", "subtitle": sub, "area": "reminders"}


# ---------- denní osa (MRK-13) ----------

def timeline_reminders(req) -> list[TimelineItem]:
    """Připomínky dne jako časové body (bez konce – neobsazují čas, volné bloky neovlivní)."""
    start, end = (req.start.astimezone(timezone.utc).replace(tzinfo=None), req.end.astimezone(timezone.utc).replace(tzinfo=None))
    now = req.now.astimezone(timezone.utc).replace(tzinfo=None)
    items = []
    for r in req.db.query(Reminder).filter(Reminder.status.in_(("scheduled", "fired", "done"))).all():
        # stejná pravidla jako režim Dnes (today_reminders_timeline)
        when = rs.effective_due(r) if r.status in ("scheduled", "fired") else r.due_at
        if start <= when < end:
            status = "done" if r.status == "done" else ("due" if r.status == "fired" or when <= now else "upcoming")
        elif r.recurrence != "none" and r.last_fired_at is not None and start <= r.last_fired_at < end:
            when, status = r.last_fired_at, "past"  # opakovaná připomínka v tento den už zazněla
        else:
            continue
        items.append(TimelineItem(
            id=f"reminder:{r.id}", kind="reminder", title=r.title, date=req.day.isoformat(), status=status,
            subtitle="Připomínka" + (f" · {rs.describe_recurrence(r)}" if r.recurrence != "none" else ""),
            starts_at=when.replace(tzinfo=timezone.utc), href=f"/reminders?reminder={r.id}"))
    return items


def context_timeline(req: ContextRequest) -> list[str]:
    """MRK-13: krátký deterministický souhrn dne z denní osy – další časová položka, další volno, termíny dne."""
    if req.day_timeline is None:
        return []
    data = req.day_timeline()
    now = req.local_now if req.local_now.tzinfo else req.local_now.replace(tzinfo=APP_TZ)
    now_iso = now.astimezone(timezone.utc).isoformat()
    upcoming = [i for i in data["timed_items"] if (i["ends_at"] or i["starts_at"]) > now_iso and i["status"] not in ("done", "past")]
    nxt = f"{upcoming[0]['local_start']} {short(upcoming[0]['title'], 50)}" if upcoming else "nic dalšího s časem"
    free = [b for b in data["free_blocks"] if b["ends_at"] > now_iso]
    # volno, které už běží, se ukáže od teď (ne od svého začátku)
    gap_start = (now.strftime("%H:%M") if free and free[0]["starts_at"] < now_iso else free[0]["local_start"]) if free else ""
    gap = f"{gap_start}–{free[0]['local_end']}" if free else "žádné (07–22, min. 30 min)"
    deadlines = [short(i["title"], 40) for i in data["all_day_items"] if i["status"] not in ("done", "past")][:3]
    caveat = " (neúplné)" if data.get("truncated") else ""
    return [f"Den dnes{caveat}: další {nxt}; nejbližší volno {gap}; celodenní/termíny: {list_or_none(deadlines, len(deadlines))}"]


CORE_INTEGRATIONS = ModuleIntegrations(
    timeline=(TimelineSource("reminders", 10, timeline_reminders),),
    # MRK-28: změny jádra (system.* je provoz, ne změna pro člověka – ten change_feed vyřadí jako šum)
    changes=(
        ChangeSource("reminders", areas=frozenset({"reminders"}),
                     from_activity=activity_changes({"reminder": "/reminders?reminder={id}"}, "/reminders")),
        ChangeSource("memory", areas=frozenset({"memory"}),
                     from_activity=activity_changes({"memory": "/memory?memory={id}"}, "/memory")),
    ),
    search=(
        SearchSource("reminders", 40, search_reminders),
        SearchSource("memory", 80, search_memories),
    ),
    today=(
        TodaySource("reminders", 10, timeline=today_reminders_timeline, overdue=today_reminders_overdue,
                    upcoming=today_reminders_upcoming, closed_refs=today_reminders_closed),
    ),
    entity_refs=(EntityRef("reminder", "/reminders?reminder={id}", notification_source=True),),
    context=(
        ContextSection("reminders", ("pripom", "upomin", "reminder"), order=20, build=context_reminders,
                       covered_tools=("get_reminders",)),
        ContextSection("timeline", ("program", "muj den", "harmonogram", "timeline", "voln"),
                       order=5, build=context_timeline),
        ContextSection("notifications", ("upozorn", "notifikac", "notifik"), order=30, build=context_notifications,
                       covered_tools=("get_notification_summary",)),
    ),
    quick_add_rules=(
        QuickAddRule(10, "reminder", detect_reminder_keyword),
        QuickAddRule(60, "reminder", detect_reminder_time),
    ),
    quick_add_kinds=(QuickAddKind("reminder", parse_reminder, reminder_tool_call, reminder_display),),
)
