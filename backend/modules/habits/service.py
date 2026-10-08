"""Doménová logika Návyků (MRK-21) – jediná cesta zápisu (REST i Dnes), čtení pro poskytovatele.

Stavy dne:
- `done` / `skipped` – uložený záznam (`HabitEntry`), zapisuje uživatel;
- `missed` – ODVOZENÝ: minulý den od založení návyku, pro který žádný záznam není (bez scheduleru,
  deterministicky při každém čtení). Hodnota `missed` je v DB povolená jen pro budoucí ruční / importovaný zápis;
- `open` – dnešek bez záznamu.

Historie: záznam se nikdy nemaže; změna stavu dne přepíše řádek, ale Aktivita uloží deltu (původní stav, hodnotu).
Archivace jen skryje návyk z Dnes a z nových zápisů – záznamy zůstávají a po obnovení jsou zpět. Od dne archivace
se nic neodvozuje jako `missed`; po obnovení jiný den začíná odvozování od dne obnovení (`Habit.tracked_since`).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from activity_service import log_activity
from domain_events import ActivityProjection, append_domain_event
from modules.habits.models import ENTRY_STATES, HABIT_KINDS, Habit, HabitEntry
from text_utils import format_date_cz, format_num_cz
from time_utils import to_local, today_local, utc_now

AREA = "habits"
WRITABLE_STATES = ("done", "skipped")
HISTORY_DAYS = 7
MAX_NAME = 120
MAX_NOTE = 500
MAX_VALUE = 100_000
MAX_DURATION = 24 * 60
KIND_LABELS = {"check": "Splnit", "count": "Počet", "duration": "Doba"}
STATE_LABELS = {"done": "splněno", "skipped": "přeskočeno", "missed": "vynecháno", "open": "čeká"}


class HabitError(Exception):
    """Neplatný požadavek (`status` = HTTP kód, `message` česky)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- čtení ----------


def created_day(h: Habit) -> date:
    return to_local(h.created_at).date() if h.created_at else today_local()


def target_label(h: Habit) -> str:
    if h.target_value is None:
        return ""
    return f"{format_num_cz(h.target_value)} {h.unit or ''}".strip()


def tracked_since(h: Habit) -> date:
    """První den, od kterého chybějící záznam znamená „missed" (založení, po obnovení z archivu den obnovení)."""
    return max(created_day(h), h.tracked_since) if h.tracked_since else created_day(h)


def day_state(h: Habit, day: date, entry: HabitEntry | None, today: date) -> str | None:
    """Stav návyku v daný den; None = nic se neočekává (před sledováním, v budoucnu, nebo od archivace)."""
    if entry is not None:
        return entry.state
    if day > today or day < tracked_since(h):
        return None
    if not h.active and h.archived_at and day >= to_local(h.archived_at).date():
        return None
    return "open" if day == today else "missed"


def _entries_by_day(db: Session, habit_ids: list[int], first: date, last: date) -> dict[tuple[int, date], HabitEntry]:
    if not habit_ids:
        return {}
    rows = (db.query(HabitEntry)
            .filter(HabitEntry.habit_id.in_(habit_ids), HabitEntry.date >= first, HabitEntry.date <= last).all())
    return {(e.habit_id, e.date): e for e in rows}


def entry_dict(e: HabitEntry | None) -> dict | None:
    if e is None:
        return None
    return {"id": e.id, "date": e.date.isoformat(), "state": e.state, "value": e.value,
            "duration_minutes": e.duration_minutes, "note": e.note}


def habit_dict(h: Habit, entries: dict[tuple[int, date], HabitEntry], today: date) -> dict:
    days = [today - timedelta(days=i) for i in range(HISTORY_DAYS - 1, -1, -1)]
    history = []
    for d in days:
        st = day_state(h, d, entries.get((h.id, d)), today)
        history.append({"date": d.isoformat(), "state": st})
    return {
        "id": h.id,
        "name": h.name,
        "kind": h.kind,
        "target_value": h.target_value,
        "unit": h.unit,
        "target_label": target_label(h),
        "active": bool(h.active),
        "archived_at": h.archived_at.isoformat() if h.archived_at else None,
        "created_on": created_day(h).isoformat(),
        "today": {"state": day_state(h, today, entries.get((h.id, today)), today) if h.active else None,
                  "entry": entry_dict(entries.get((h.id, today)))},
        "history": history,
    }


def active_habits(db: Session) -> list[Habit]:
    return db.query(Habit).filter(Habit.active.is_(True)).order_by(Habit.name, Habit.id).all()


def list_habits(db: Session, today: date | None = None, *, include_archived: bool = True) -> dict:
    today = today or today_local()
    q = db.query(Habit)
    if not include_archived:
        q = q.filter(Habit.active.is_(True))
    habits = q.order_by(Habit.name, Habit.id).all()
    entries = _entries_by_day(db, [h.id for h in habits], today - timedelta(days=HISTORY_DAYS - 1), today)
    items = [habit_dict(h, entries, today) for h in habits]
    return {
        "date": today.isoformat(),
        "active": [i for i in items if i["active"]],
        "archived": [i for i in items if not i["active"]],
        "summary": summary(db, today),
    }


def summary(db: Session, today: date | None = None) -> dict:
    """Dnešek (hotovo / přeskočeno / celkem) a posledních 7 dní (splněno z očekávaných dní)."""
    today = today or today_local()
    habits = active_habits(db)
    first = today - timedelta(days=HISTORY_DAYS - 1)
    entries = _entries_by_day(db, [h.id for h in habits], first, today)
    states_today = [day_state(h, today, entries.get((h.id, today)), today) for h in habits]
    week_expected = week_done = 0
    for h in habits:
        for i in range(HISTORY_DAYS):
            st = day_state(h, first + timedelta(days=i), entries.get((h.id, first + timedelta(days=i))), today)
            if st is None or st == "open" or st == "skipped":
                continue  # dnešek se teprve počítá; přeskočení není neúspěch
            week_expected += 1
            week_done += st == "done"
    return {
        "total": len(habits),
        "done": states_today.count("done"),
        "skipped": states_today.count("skipped"),
        "open": states_today.count("open"),
        "week_done": week_done,
        "week_expected": week_expected,
    }


def get_habit(db: Session, habit_id: int) -> Habit:
    h = db.get(Habit, habit_id)
    if h is None:
        raise HabitError(404, "Návyk neexistuje.")
    return h


# ---------- zápis ----------


def _clean_name(name) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise HabitError(422, "Doplň název návyku.")
    if len(text) > MAX_NAME:
        raise HabitError(422, "Název je moc dlouhý.")
    return text


def create_habit(db: Session, name, kind: str = "check", target_value=None, unit=None, *,
                 user_context: str | None = None) -> Habit:
    kind = kind or "check"
    if kind not in HABIT_KINDS:
        raise HabitError(422, "Neznámý druh návyku.")
    if target_value is not None:
        try:
            target_value = float(target_value)
        except (TypeError, ValueError):
            raise HabitError(422, "Cíl musí být číslo.")
        if not 0 < target_value <= MAX_VALUE:
            raise HabitError(422, "Cíl je mimo rozsah.")
    unit = (" ".join(str(unit).split())[:20] or None) if unit else None
    h = Habit(name=_clean_name(name), kind=kind, target_value=target_value, unit=unit, active=True)
    db.add(h)
    db.flush()
    log_activity(db, AREA, "create", f"Nový návyk: {h.name}", entity_type="habit", entity_id=h.id,
                 delta={"name": {"old": None, "new": h.name}, "kind": {"old": None, "new": kind}}, user_context=user_context)
    return h


def set_active(db: Session, habit_id: int, active: bool, *, user_context: str | None = None) -> Habit:
    """Archivace / obnovení. Záznamy dnů se nemění (žádné mazání historie)."""
    h = get_habit(db, habit_id)
    if bool(h.active) == active:
        return h
    if active and h.archived_at and to_local(h.archived_at).date() < today_local():
        # dny archivace (a neznámé dny před ní) se po obnovení nepočítají jako vynechané
        h.tracked_since = today_local()
    h.active = active
    h.archived_at = None if active else utc_now()
    log_activity(db, AREA, "restore" if active else "archive",
                 f"{'Obnoven' if active else 'Archivován'} návyk: {h.name}", entity_type="habit", entity_id=h.id,
                 delta={"active": {"old": not active, "new": active}}, user_context=user_context)
    return h


def _number(v, fld: str, maximum: float, *, integer: bool = False):
    if v in (None, ""):
        return None
    try:
        num = int(v) if integer else float(v)
    except (TypeError, ValueError):
        raise HabitError(422, f"{fld} musí být číslo.")
    if not 0 <= num <= maximum:
        raise HabitError(422, f"{fld} je mimo rozsah.")
    return num


def set_entry(db: Session, habit_id: int, state: str, *, day: date | None = None, value=None, duration_minutes=None,
              note=None, user_context: str | None = None, today: date | None = None) -> HabitEntry:
    """Zapíše stav dne (`done` / `skipped`). Existující záznam se aktualizuje a změna jde do Aktivity s deltou."""
    today = today or today_local()
    day = day or today
    if state not in WRITABLE_STATES:
        raise HabitError(422, "Stav musí být splněno nebo přeskočeno.")
    if state not in ENTRY_STATES:  # pragma: no cover - pojistka shody konstant
        raise HabitError(422, "Neznámý stav.")
    h = get_habit(db, habit_id)
    if not h.active:
        raise HabitError(409, "Návyk je archivovaný.")
    if day > today:
        raise HabitError(422, "Do budoucnosti se zapsat nedá.")
    if day < created_day(h):
        raise HabitError(422, "Návyk tehdy ještě neexistoval.")
    value = _number(value, "Hodnota", MAX_VALUE)
    duration_minutes = _number(duration_minutes, "Doba", MAX_DURATION, integer=True)
    note = (str(note).strip()[:MAX_NOTE] or None) if note else None
    entry = db.query(HabitEntry).filter(HabitEntry.habit_id == h.id, HabitEntry.date == day).one_or_none()
    old = entry_dict(entry)
    if entry is None:
        entry = HabitEntry(habit_id=h.id, date=day, state=state)
        db.add(entry)
    entry.state = state
    entry.value = value
    entry.duration_minutes = duration_minutes
    entry.note = note
    db.flush()
    new = entry_dict(entry)
    delta = {k: {"old": (old or {}).get(k), "new": new[k]} for k in ("state", "value", "duration_minutes", "note")
             if (old or {}).get(k) != new[k]}
    if delta:
        when = "dnes" if day == today else format_date_cz(day)
        # MRK-19: fakt habits.entry.done / .skipped; Aktivita je projekce (právě jeden řádek na změnu)
        append_domain_event(
            db, event_type=f"habits.entry.{state}", aggregate_type="entry", aggregate_id=entry.id,
            payload={"habit_id": h.id, "entry_id": entry.id, "date": day.isoformat(), "state": state,
                     "previous_state": (old or {}).get("state")},
            activity=ActivityProjection(
                AREA, "update" if old else "check", f"{h.name}: {STATE_LABELS[state]} ({when})",
                entity_type="habit_entry", entity_id=entry.id, delta=delta, user_context=user_context),
        )
    return entry
