"""MRK-41: ruční týdenní rozvrh školy – hodiny zadané jednou za semestr, uložené jako opakované události Kalendáře.

Bez vlastního modelu a bez migrace: rozvrh je kalendářní zdroj `timetable` (kind `ics`, jen bez feedu – synchronizace
ICS zná jen klíče ze `service.SOURCES`, takže ruční hodiny nikdy neoznačí jako chybějící). Každá hodina je master
událost s `RRULE:FREQ=WEEKLY;UNTIL=…`. Výskyty, letní/zimní čas, volné bloky, denní osa i Dnes tak fungují beze změny
(`occurrences.get_calendar_occurrences`).

- Předmět: `course_ref = "subject:<id>"` (párování Moodle MRK-76 bere jen zdroj `moodle`, nekoliduje).
- Druh hodiny: `description` = český popisek (Přednáška / Seminář / Cvičení / Laboratoř).
- Rytmus (MRK-142): každý týden, nebo ob týden (`INTERVAL=2`). U ob týden určuje týdny s výukou kotva = libovolný den
  týdne s výukou (UI posílá pondělí tohoto nebo příštího týdne) – žádné „liché / sudé“ podle čísla týdne, to se mezi
  školami liší. První výskyt = první daný den od „Platí od“ v týdnu se stejnou paritou jako kotva.
- Den, čas a platnost od–do se čtou zpět z události (první výskyt, `UNTIL`) – nic se neukládá dvakrát.
- Výjimka jednoho výskytu = přepis (override) se stejným `external_uid` a `recurrence_id` = klíč výskytu:
  zrušení = status `cancelled`, přesun = aktivní přepis s novým časem. Obnovení výskytu přepis odstraní.
- Každá změna = doménová událost `calendar.event.*` s projekcí do Aktivity ve stejné transakci.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from domain_events import ActivityProjection, append_domain_event
from models import Subject
from modules.calendar.models import CalendarEvent, CalendarSource, now_utc
from modules.calendar.occurrences import _instances
from time_utils import APP_TZ, today_local

SOURCE_KEY = "timetable"
SOURCE_NAME = "Rozvrh"
KINDS = {"lecture": "Přednáška", "seminar": "Seminář", "exercise": "Cvičení", "lab": "Laboratoř"}
WEEKDAYS = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
MAX_ENTRIES = 80
MAX_SPAN_DAYS = 366
CLOCK_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
UID_PREFIX = "timetable-"


class TimetableError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- pomocné ----------


def _clock(raw, field: str) -> time:
    if not isinstance(raw, str) or not CLOCK_RE.match(raw):
        raise TimetableError(400, f"{field}: čas ve tvaru HH:MM.")
    return time(int(raw[:2]), int(raw[3:]))


def _day(raw, field: str) -> date:
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) and len(raw) == 10 else _bad(field)
    except ValueError:
        return _bad(field)


def _bad(field: str):
    raise TimetableError(400, f"{field}: datum ve tvaru RRRR-MM-DD.")


def _local(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=APP_TZ)


def _source(db: Session) -> CalendarSource:
    """Zdroj „Rozvrh“ – založí se při první hodině (bezpečně i při souběhu)."""
    source = db.query(CalendarSource).filter_by(config_key=SOURCE_KEY).one_or_none()
    if source is None:
        insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        db.execute(insert(CalendarSource).values(kind="ics", name=SOURCE_NAME, config_key=SOURCE_KEY, enabled=True,
                                                 timezone=APP_TZ.key).on_conflict_do_nothing(index_elements=["config_key"]))
        source = db.query(CalendarSource).filter_by(config_key=SOURCE_KEY).one()
    return source


def _subject_id(row: CalendarEvent) -> int | None:
    ref = row.course_ref or ""
    return int(ref[8:]) if ref.startswith("subject:") and ref[8:].isdigit() else None


def _until(row: CalendarEvent) -> date | None:
    m = re.search(r"UNTIL=(\d{8})T(\d{6})Z", row.rrule or "")
    if not m:
        return None
    utc = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return utc.astimezone(APP_TZ).date()


def _every(row: CalendarEvent) -> int:
    return 2 if "INTERVAL=2" in (row.rrule or "") else 1


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _next_dates(row: CalendarEvent, overrides: list[CalendarEvent], today: date) -> tuple[str | None, str | None]:
    """→ (next_date, next_regular_date), oba od dneška včetně. Pravidelné výskyty až do konce platnosti série
    (několik zrušených hodin za sebou nesmí „příště“ schovat); přesunuté hodiny kdykoli od dneška.

    `next_date` = skutečná příští hodina (MRK-147): zrušené výskyty přeskočí, přesunutý výskyt se počítá v novém
    termínu. `next_regular_date` = příští výskyt podle série BEZ výjimky – výchozí den pro formulář výjimky
    (ten pracuje s původními dny série)."""
    lo = datetime.combine(today, time.min, tzinfo=APP_TZ)
    until = _until(row) or row.starts_at.astimezone(APP_TZ).date()
    hi = datetime.combine(until + timedelta(days=1), time.min, tzinfo=APP_TZ)
    excepted = {o.recurrence_id for o in overrides}
    regular = []
    if hi > lo:  # konec platnosti omezuje jen pravidelné opakování …
        found = _instances(row, lo.astimezone(timezone.utc), hi.astimezone(timezone.utc), 120)  # rok týdně = 53
        regular = sorted(v for k, v in found.items() if isinstance(v, datetime) and k not in excepted)
    # … přesunutá hodina platí v novém termínu, i když leží za koncem série (review #128)
    moved = [o.starts_at for o in overrides if o.status == "active" and o.starts_at >= lo]
    actual = sorted([*regular, *moved])
    day = lambda v: v.astimezone(APP_TZ).date().isoformat()  # noqa: E731
    return (day(actual[0]) if actual else None), (day(regular[0]) if regular else None)


def _key(start_local: datetime) -> str:
    """Klíč výskytu přesně jako `occurrences._instances` (UTC isoformat)."""
    return start_local.astimezone(timezone.utc).isoformat()


def _masters(db: Session) -> list[CalendarEvent]:
    source = db.query(CalendarSource).filter_by(config_key=SOURCE_KEY).one_or_none()
    if source is None:
        return []
    return (db.query(CalendarEvent).filter(CalendarEvent.source_id == source.id, CalendarEvent.recurrence_id == "",
                                           CalendarEvent.status == "active")
            .order_by(CalendarEvent.starts_at, CalendarEvent.id).all())


def _get(db: Session, entry_id: int) -> CalendarEvent:
    source = db.query(CalendarSource).filter_by(config_key=SOURCE_KEY).one_or_none()
    row = db.get(CalendarEvent, entry_id)
    if (row is None or source is None or row.source_id != source.id or row.recurrence_id != ""
            or row.status != "active"):
        raise TimetableError(404, "Hodina v rozvrhu neexistuje.")
    return row


def _overrides(db: Session, row: CalendarEvent) -> list[CalendarEvent]:
    return (db.query(CalendarEvent).filter(CalendarEvent.source_id == row.source_id,
                                           CalendarEvent.external_uid == row.external_uid,
                                           CalendarEvent.recurrence_id != "")
            .order_by(CalendarEvent.recurrence_id).all())


def _payload(row: CalendarEvent) -> dict:
    return {"event_id": row.id, "source_id": row.source_id, "status": row.status,
            "starts_at": row.starts_at.isoformat(), "ends_at": row.ends_at.isoformat(), "all_day": False}


def _fact(db: Session, row: CalendarEvent, action: str, activity_action: str, summary: str, delta: dict | None = None):
    append_domain_event(db, event_type=f"calendar.event.{action}", aggregate_type="calendar_event",
                        aggregate_id=row.id, payload=_payload(row), now=now_utc(),
                        activity=ActivityProjection("calendar", activity_action, summary[:480], "calendar_event", row.id,
                                                    delta, "manual"))


# ---------- čtení ----------


def entry_dict(db: Session, row: CalendarEvent, subjects: dict[int, str] | None = None) -> dict:
    start = row.starts_at.astimezone(APP_TZ)
    end = row.ends_at.astimezone(APP_TZ)
    sid = _subject_id(row)
    kind = next((k for k, v in KINDS.items() if v == row.description), None)
    exceptions = []
    overrides = _overrides(db, row)
    next_date, next_regular = _next_dates(row, overrides, today_local())
    for o in overrides:
        original = datetime.fromisoformat(o.recurrence_id).astimezone(APP_TZ)
        moved = o.status == "active"
        exceptions.append({
            "date": original.date().isoformat(), "action": "move" if moved else "cancel",
            "starts_at": o.starts_at.astimezone(APP_TZ).isoformat() if moved else None,
            "ends_at": o.ends_at.astimezone(APP_TZ).isoformat() if moved else None,
        })
    return {
        "id": row.id, "subject_id": sid, "subject_name": (subjects or {}).get(sid) if sid else None,
        "title": row.title, "kind": kind, "kind_label": row.description, "room": row.location,
        "weekday": start.weekday(), "weekday_label": WEEKDAYS[start.weekday()],
        "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
        "valid_from": start.date().isoformat(), "valid_until": (_until(row) or start.date()).isoformat(),
        "every": _every(row), "week_anchor": _monday(start.date()).isoformat(),
        "next_date": next_date, "next_regular_date": next_regular,
        "exceptions": exceptions,
    }


def list_entries(db: Session) -> dict:
    subjects = {s.id: s.name for s in db.query(Subject).all()}
    rows = sorted(_masters(db), key=lambda r: (r.starts_at.astimezone(APP_TZ).weekday(),
                                               r.starts_at.astimezone(APP_TZ).time(), r.id))
    return {"entries": [entry_dict(db, r, subjects) for r in rows], "kinds": KINDS}


# ---------- zápisy ----------


def _validated(db: Session, data: dict) -> dict:
    sid = data.get("subject_id")
    subject = db.get(Subject, sid) if isinstance(sid, int) and not isinstance(sid, bool) else None
    if subject is None:
        raise TimetableError(400, "Vyber předmět.")
    kind = data.get("kind")
    if kind not in KINDS:
        raise TimetableError(400, "Druh hodiny: přednáška, seminář, cvičení nebo laboratoř.")
    weekday = data.get("weekday")
    if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday <= 6:
        raise TimetableError(400, "Den v týdnu: 0 (pondělí) až 6 (neděle).")
    start, end = _clock(data.get("start"), "Začátek"), _clock(data.get("end"), "Konec")
    if end <= start:
        raise TimetableError(400, "Konec musí být po začátku.")
    valid_from, valid_until = _day(data.get("valid_from"), "Platí od"), _day(data.get("valid_until"), "Platí do")
    if valid_until < valid_from:
        raise TimetableError(400, "„Platí do“ musí být po „Platí od“.")
    if (valid_until - valid_from).days > MAX_SPAN_DAYS:
        raise TimetableError(400, "Rozvrh zadávej nejvýš na rok (jeden semestr).")
    every = data.get("every", 1)
    if every not in (1, 2) or isinstance(every, bool):
        raise TimetableError(400, "Rytmus: každý týden (1) nebo ob týden (2).")
    first = valid_from + timedelta(days=(weekday - valid_from.weekday()) % 7)
    if every == 2:
        if not data.get("week_anchor"):
            raise TimetableError(400, "U hodiny ob týden vyber, jestli je výuka tento, nebo příští týden.")
        anchor = _monday(_day(data.get("week_anchor"), "Týden s výukou"))
        if (_monday(first) - anchor).days // 7 % 2:
            first += timedelta(days=7)
    if first > valid_until:
        raise TimetableError(400, "V zadaném období není žádný takový den.")
    room = data.get("room")
    room = room.strip()[:200] or None if isinstance(room, str) else None
    return {"subject": subject, "kind": kind, "start": start, "end": end, "first": first, "until": valid_until,
            "room": room, "every": every}


def _apply(row: CalendarEvent, v: dict) -> None:
    starts = _local(v["first"], v["start"])
    until_utc = _local(v["until"], v["end"]).astimezone(timezone.utc)
    row.title = v["subject"].name[:300]
    row.description = KINDS[v["kind"]]
    row.location = v["room"]
    row.starts_at = starts.astimezone(timezone.utc)
    row.ends_at = _local(v["first"], v["end"]).astimezone(timezone.utc)
    row.timezone = APP_TZ.key
    interval = ";INTERVAL=2" if v["every"] == 2 else ""
    row.rrule = f"FREQ=WEEKLY{interval};UNTIL={until_utc:%Y%m%dT%H%M%SZ}"
    row.course_ref = f"subject:{v['subject'].id}"


def _label(row: CalendarEvent) -> str:
    start = row.starts_at.astimezone(APP_TZ)
    every = ", ob týden" if _every(row) == 2 else ""
    return f"{row.title} ({row.description}, {WEEKDAYS[start.weekday()]} {start:%H:%M}{every})"


def create_entry(db: Session, data: dict) -> dict:
    v = _validated(db, data)
    source = _source(db)
    if len(_masters(db)) >= MAX_ENTRIES:
        raise TimetableError(400, f"Rozvrh má nejvýš {MAX_ENTRIES} hodin.")
    now = now_utc()
    row = CalendarEvent(source_id=source.id, external_uid=f"{UID_PREFIX}{uuid.uuid4().hex}", recurrence_id="",
                        all_day=False, status="active", sequence=0, imported_at=now, created_at=now, updated_at=now)
    _apply(row, v)
    db.add(row)
    db.flush()
    _fact(db, row, "created", "create", f"Rozvrh: {_label(row)}")
    return entry_dict(db, row, {v["subject"].id: v["subject"].name})


def update_entry(db: Session, entry_id: int, data: dict) -> dict:
    """Změna hodiny. Změna dne / času posune všechny výskyty; výjimky výskytů, které už do série nepatří (jiný den /
    čas, zkrácená platnost), se zahodí."""
    row = _get(db, entry_id)
    v = _validated(db, data)
    before = (row.starts_at, row.ends_at, row.rrule, row.title, row.description, row.location)
    _apply(row, v)
    after = (row.starts_at, row.ends_at, row.rrule, row.title, row.description, row.location)
    if after == before:
        return entry_dict(db, row, {v["subject"].id: v["subject"].name})
    dropped = _drop_orphan_overrides(db, row)
    row.sequence = (row.sequence or 0) + 1
    row.updated_at = now_utc()
    db.flush()
    _fact(db, row, "updated", "update", f"Rozvrh upraven: {_label(row)}",
          {"exceptions_removed": dropped} if dropped else None)
    return entry_dict(db, row, {v["subject"].id: v["subject"].name})


def _drop_orphan_overrides(db: Session, row: CalendarEvent) -> int:
    """Smaže výjimky, jejichž původní výskyt už do série nepatří (jiný den / čas, zkrácená platnost) – jinak by
    přesunutá hodina zůstala v Kalendáři a v rozvrhu by nešla spravovat. Výjimky platných výskytů zůstanou."""
    overrides = _overrides(db, row)
    if not overrides:
        return 0
    until = _until(row) or row.starts_at.astimezone(APP_TZ).date()
    hi = datetime.combine(until + timedelta(days=1), time.min, tzinfo=APP_TZ).astimezone(timezone.utc)
    keys = set(_instances(row, row.starts_at, hi, 1000))
    dropped = [o for o in overrides if o.recurrence_id not in keys]
    for o in dropped:
        db.delete(o)
    return len(dropped)


def delete_entry(db: Session, entry_id: int) -> None:
    """Odebrání hodiny = zrušení opakované události (žádné tvrdé mazání; výskyty zmizí z kalendáře)."""
    row = _get(db, entry_id)
    now = now_utc()
    row.status = "cancelled"
    row.cancelled_at = row.updated_at = now
    # přesunuté výskyty jsou samostatné aktivní řádky – bez zrušení by zůstaly v Kalendáři / denní ose / Dnes
    moved = [o for o in _overrides(db, row) if o.status == "active"]
    for o in moved:
        o.status = "cancelled"
        o.cancelled_at = o.updated_at = now
    db.flush()
    _fact(db, row, "cancelled", "cancel", f"Rozvrh: odebrána hodina {_label(row)}",
          {"moved_occurrences_cancelled": len(moved)} if moved else None)


def _instance(row: CalendarEvent, day: date) -> datetime:
    """Začátek výskytu dané hodiny v den `day`, nebo chyba (ten den hodina není)."""
    lo = datetime.combine(day, time.min, tzinfo=APP_TZ)
    found = _instances(row, lo.astimezone(timezone.utc), (lo + timedelta(days=1)).astimezone(timezone.utc), 5)
    if not found:
        raise TimetableError(404, "Ten den tahle hodina není.")
    value = next(iter(found.values()))
    return value if isinstance(value, datetime) else lo


def set_exception(db: Session, entry_id: int, data: dict) -> dict:
    """Zrušení (`cancel`) nebo přesun (`move`, nový den a čas) JEDNOHO výskytu."""
    row = _get(db, entry_id)
    day = _day(data.get("date"), "Datum hodiny")
    action = data.get("action")
    if action not in ("cancel", "move"):
        raise TimetableError(400, "Akce: zrušit nebo přesunout.")
    start = _instance(row, day)
    key = _key(start)
    duration = row.ends_at - row.starts_at
    if action == "move":
        new_day = _day(data.get("new_date") or data.get("date"), "Nové datum")
        new_start, new_end = _clock(data.get("start"), "Nový začátek"), _clock(data.get("end"), "Nový konec")
        if new_end <= new_start:
            raise TimetableError(400, "Konec musí být po začátku.")
        starts, ends = _local(new_day, new_start), _local(new_day, new_end)
    else:
        starts, ends = start, start + duration
    override = next((o for o in _overrides(db, row) if o.recurrence_id == key), None)
    now = now_utc()
    if override is None:
        override = CalendarEvent(source_id=row.source_id, external_uid=row.external_uid, recurrence_id=key,
                                 title=row.title, description=row.description, location=row.location,
                                 all_day=False, timezone=row.timezone, course_ref=row.course_ref, sequence=0,
                                 imported_at=now, created_at=now)
        db.add(override)
    override.starts_at = starts.astimezone(timezone.utc)
    override.ends_at = ends.astimezone(timezone.utc)
    override.status = "active" if action == "move" else "cancelled"
    override.cancelled_at = now if action == "cancel" else None
    override.updated_at = now
    db.flush()
    if action == "cancel":
        _fact(db, override, "cancelled", "cancel", f"Rozvrh: zrušena hodina {row.title} {day.day}. {day.month}.")
    else:
        _fact(db, override, "updated", "update",
              f"Rozvrh: hodina {row.title} {day.day}. {day.month}. přesunuta na {starts:%d. %m. %H:%M}",
              {"starts_at": {"old": start.isoformat(), "new": starts.isoformat()}})
    return entry_dict(db, row, {})


def clear_exception(db: Session, entry_id: int, day_raw: str) -> dict:
    """Obnovení výskytu podle rozvrhu (zrušení výjimky)."""
    row = _get(db, entry_id)
    day = _day(day_raw, "Datum hodiny")
    key = _key(_instance(row, day))
    override = next((o for o in _overrides(db, row) if o.recurrence_id == key), None)
    if override is None:
        raise TimetableError(404, "Ten den žádná výjimka není.")
    _fact(db, row, "updated", "update", f"Rozvrh: hodina {row.title} {day.day}. {day.month}. zase podle rozvrhu")
    db.delete(override)
    db.flush()
    return entry_dict(db, row, {})
