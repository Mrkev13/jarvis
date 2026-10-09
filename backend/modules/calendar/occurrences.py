"""Bounded occurrence projection (MRK-40): what actually happens in a time window.

`CalendarEvent` stays the durable imported fact (a single event, a recurring master or a RECURRENCE-ID override).
Occurrences are computed at query time, never stored:

- active = status `active` and still present in its source (`source_missing_at IS NULL`);
- a recurring master (RRULE and/or RDATE) expands with `dateutil.rrule` in the event's own timezone, so a weekly
  10:00 Europe/Prague lecture stays 10:00 local across CET/CEST (never "+7 days in UTC");
- RFC 5545 §3.3.5 for generated wall times: a nonexistent local time (spring gap) uses the offset before the gap
  (02:30 → 03:30 CEST), an ambiguous one (autumn) is the first occurrence (fold=0) – exactly what zoneinfo does;
- EXDATE removes an instance; a present RECURRENCE-ID override replaces it (moved), or removes it when cancelled;
- every query needs a window (max `MAX_WINDOW`); infinite rules are only iterated up to the window end.

Sub-daily rules (HOURLY/MINUTELY/SECONDLY) are not expanded: only the stored first instance is shown.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from sqlalchemy import or_

from modules.calendar.models import CalendarEvent
from time_utils import APP_TZ

UTC = timezone.utc
MAX_WINDOW = timedelta(days=366)
MAX_OCCURRENCES = 5000
EXPANDABLE_FREQ = frozenset({"DAILY", "WEEKLY", "MONTHLY", "YEARLY"})


class CalendarWindowError(ValueError):
    """Invalid or too large query window (→ 422)."""


@dataclass(frozen=True)
class CalendarOccurrence:
    key: str                 # "<event id>" for a single event, "<event id>@<recurrence key>" for a generated instance
    event_id: int
    source_id: int
    recurrence_key: str      # UTC ISO instant (timed) or ISO date (all-day); "" for a stored single/override row
    title: str
    location: str | None
    starts_at: datetime      # aware UTC
    ends_at: datetime
    all_day: bool
    starts_on: date | None   # all-day: local date, exclusive `ends_on`
    ends_on: date | None
    timezone: str
    recurring: bool          # generated from a recurring master

    def as_dict(self) -> dict:
        out = asdict(self)
        for name in ("starts_at", "ends_at", "starts_on", "ends_on"):
            out[name] = out[name].isoformat() if out[name] is not None else None
        return out


def local_window(start: date, end: date, zone: ZoneInfo = APP_TZ) -> tuple[datetime, datetime]:
    """Local calendar days [start, end) → aware UTC bounds."""
    return (datetime.combine(start, time.min, zone).astimezone(UTC),
            datetime.combine(end, time.min, zone).astimezone(UTC))


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or APP_TZ.key)
    except Exception:  # noqa: BLE001 - unknown label stored by an older import → app zone
        return APP_TZ


def _active(query):
    return query.filter(CalendarEvent.status == "active", CalendarEvent.source_missing_at.is_(None))


def _meta(row) -> dict:
    try:
        meta = json.loads(row.recurrence_metadata or "{}")
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        return {}


def _is_recurring_master(row) -> bool:
    return row.recurrence_id == "" and (bool(row.rrule) or bool(_meta(row).get("RDATE")))


def _parse_instant(value: str, zone: ZoneInfo, all_day: bool):
    """Stored RDATE/EXDATE value → aware local datetime (timed) or date (all-day). Accepts normalized ISO values
    and legacy raw iCal values (floating values use the event zone, as the parser does)."""
    text = value.strip()
    if "-" in text or ":" in text:  # ISO written by the parser
        parsed = date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)
    elif len(text) == 8:
        parsed = datetime.strptime(text, "%Y%m%d").date()
    else:
        parsed = datetime.strptime(text.rstrip("Z"), "%Y%m%dT%H%M%S")
        parsed = parsed.replace(tzinfo=UTC) if text.endswith("Z") else parsed.replace(tzinfo=zone)
    if all_day:
        return parsed.astimezone(zone).date() if isinstance(parsed, datetime) else parsed
    if not isinstance(parsed, datetime):
        parsed = datetime.combine(parsed, time.min)
    return (parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed).astimezone(zone)


def _values(meta: dict, name: str) -> list[str]:
    out = []
    for item in meta.get(name) or []:
        out.extend(part for part in str(item).split(",") if part.strip())
    return out


def _rule_text(rrule: str, zone: ZoneInfo, all_day: bool) -> str:
    """dateutil needs UNTIL in UTC for an aware DTSTART and naive for a naive (all-day) one."""
    parts = []
    for part in rrule.split(";"):
        key, sep, value = part.partition("=")
        if key.upper() == "UNTIL" and value:
            if len(value) == 8:  # DATE: inclusive local day
                until = datetime.combine(datetime.strptime(value, "%Y%m%d").date(), time(23, 59, 59), zone)
            elif value.endswith("Z"):
                until = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            else:
                until = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone)
            value = (until.astimezone(zone).strftime("%Y%m%dT%H%M%S") if all_day
                     else until.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"))
        parts.append(f"{key}{sep}{value}")
    return ";".join(parts)


def _freq(rrule: str) -> str | None:
    for part in rrule.split(";"):
        key, _, value = part.partition("=")
        if key.upper() == "FREQ":
            return value.upper()
    return None


def _window_days(start: datetime, end: datetime) -> tuple[date, date]:
    """All-day events are date facts: they overlap the window by app-local (Prague) days, never by instants of
    their source zone, so a date never shifts between days."""
    last = end.astimezone(APP_TZ)
    end_day = last.date() if last.time() == time.min else last.date() + timedelta(days=1)
    return start.astimezone(APP_TZ).date(), end_day


def _instances(row, lo, hi, limit: int):
    """Local instance starts of a recurring master overlapping [lo, hi) (aware datetimes or dates)."""
    zone = _zone(row.timezone)
    meta = _meta(row)
    if row.all_day:
        anchor = datetime.combine(row.starts_on, time.min)
        span = row.ends_on - row.starts_on
        first_day, end_day = _window_days(lo, hi)
        lo_key, hi_key = first_day - span, end_day
    else:
        anchor = row.starts_at.astimezone(zone)
        span = row.ends_at - row.starts_at
        lo_key, hi_key = lo - span, hi
    found = {}

    def add(value):
        key_value = value.date() if row.all_day and isinstance(value, datetime) else value
        if row.all_day:
            if lo_key < key_value < hi_key or (span == timedelta(0) and key_value == lo_key):
                found[key_value.isoformat()] = key_value
        else:
            utc = key_value.astimezone(UTC)
            if lo_key < utc < hi_key or (span == timedelta(0) and utc == lo):
                found[utc.isoformat()] = key_value

    add(anchor)  # RFC 5545: DTSTART is always the first instance
    if row.rrule and _freq(row.rrule) in EXPANDABLE_FREQ:
        try:
            rule = rrulestr(_rule_text(row.rrule, zone, row.all_day), dtstart=anchor)
        except (ValueError, TypeError):
            rule = None
        if rule is not None:
            start_from = datetime.combine(lo_key, time.min) if row.all_day else lo_key.astimezone(zone)
            for count, value in enumerate(rule.xafter(start_from, inc=True)):
                if count >= limit or (value.date() if row.all_day else value.astimezone(UTC)) >= hi_key:
                    break
                add(value)
    for raw in _values(meta, "RDATE"):
        try:
            add(_parse_instant(raw, zone, row.all_day))
        except ValueError:
            continue
    for raw in _values(meta, "EXDATE"):
        try:
            value = _parse_instant(raw, zone, row.all_day)
        except ValueError:
            continue
        found.pop(value.isoformat() if row.all_day else value.astimezone(UTC).isoformat(), None)
    return found


def _occurrence(row, *, key="", start=None) -> CalendarOccurrence:
    zone = _zone(row.timezone)
    if not key:
        return CalendarOccurrence(str(row.id), row.id, row.source_id, "", row.title, row.location, row.starts_at,
                                  row.ends_at, row.all_day, row.starts_on, row.ends_on, row.timezone, False)
    if row.all_day:
        span = row.ends_on - row.starts_on
        starts_on, ends_on = start, start + span
        starts_at, ends_at = local_window(starts_on, ends_on, zone)
    else:
        starts_on = ends_on = None
        starts_at = start.astimezone(UTC)
        ends_at = starts_at + (row.ends_at - row.starts_at)
    return CalendarOccurrence(f"{row.id}@{key}", row.id, row.source_id, key, row.title, row.location, starts_at,
                              ends_at, row.all_day, starts_on, ends_on, row.timezone, True)


def get_calendar_occurrences(db, start: datetime, end: datetime, *, limit: int = MAX_OCCURRENCES) -> list[CalendarOccurrence]:
    """Active occurrences overlapping [start, end) (aware datetimes), ordered by start. Bounded window."""
    if start.tzinfo is None or end.tzinfo is None:
        raise CalendarWindowError("window must be timezone-aware")
    if end <= start:
        raise CalendarWindowError("window end must be after its start")
    if end - start > MAX_WINDOW:
        raise CalendarWindowError("window is too large")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    first_day, end_day = _window_days(start, end)
    overlap = (((CalendarEvent.all_day.is_(False)) & (CalendarEvent.starts_at < end) &
                ((CalendarEvent.ends_at > start) | ((CalendarEvent.ends_at == CalendarEvent.starts_at) &
                                                    (CalendarEvent.starts_at >= start)))) |
               ((CalendarEvent.all_day.is_(True)) & (CalendarEvent.starts_on < end_day) &
                (CalendarEvent.ends_on > first_day)))
    singles = _active(db.query(CalendarEvent)).filter(overlap).order_by(CalendarEvent.starts_at, CalendarEvent.id) \
        .limit(limit).all()
    masters = [row for row in _active(db.query(CalendarEvent)).filter(
        CalendarEvent.recurrence_id == "",
        or_(CalendarEvent.starts_at < end, CalendarEvent.starts_on < end_day),
        or_(CalendarEvent.rrule.isnot(None), CalendarEvent.recurrence_metadata.isnot(None))).all()
        if _is_recurring_master(row)]
    # Present overrides (any status) replace their generated instance; a cancelled one only removes it.
    overrides = set()
    if masters:
        for source_id, uid, rid in (db.query(CalendarEvent.source_id, CalendarEvent.external_uid, CalendarEvent.recurrence_id)
                                    .filter(CalendarEvent.recurrence_id != "", CalendarEvent.source_missing_at.is_(None),
                                            CalendarEvent.external_uid.in_({m.external_uid for m in masters})).all()):
            overrides.add((source_id, uid, rid))
    master_ids = {m.id for m in masters}
    out = [_occurrence(row) for row in singles if row.id not in master_ids]
    for master in masters:
        for key, value in _instances(master, start, end, limit).items():
            if (master.source_id, master.external_uid, key) not in overrides:
                out.append(_occurrence(master, key=key, start=value))
    out.sort(key=lambda o: (o.starts_at, o.event_id, o.key))
    return out[:limit]
