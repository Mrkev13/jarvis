"""icalendar handles RFC decoding; validation/isolation policy lives here, never logs raw ICS."""
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from icalendar import Calendar

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 2000
UTC = timezone.utc


@dataclass(frozen=True)
class ParsedEvent:
    external_uid: str
    recurrence_id: str
    title: str | None
    description: str | None
    location: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    all_day: bool
    starts_on: date | None
    ends_on: date | None
    timezone: str
    status: str
    rrule: str | None
    recurrence_metadata: str | None
    sequence: int | None
    source_updated_at: datetime | None
    course_ref: str | None = None  # MRK-76: the single CATEGORIES value (Moodle: course short name)


@dataclass(frozen=True)
class ParseResult:
    events: tuple[ParsedEvent, ...]
    errors: int
    # MRK-40: a complete, authoritative snapshot lets the importer mark absent identities source-missing.
    # Incomplete = unreadable calendar, no VEVENT at all, or a component whose UID could not be read.
    complete: bool = False
    # UIDs present in the feed but not imported (malformed component, conflicting duplicates): never marked missing.
    uncertain_uids: frozenset[str] = frozenset()


def _text(component, name, maximum, *, required=False):
    value = component.get(name)
    if value is None:
        if required:
            raise ValueError('missing_field')
        return None
    if isinstance(value, list):
        raise ValueError('duplicate_property')
    text = str(value).strip()
    if len(text) > maximum or (required and not text):
        raise ValueError('invalid_field')
    return text or None


MAX_COURSE_REF = 100


def _course_ref(component):
    """MRK-76: Moodle exports the course short name as CATEGORIES. Exactly one distinct value → that value; none,
    several or an oversized one → None (no guessing). Never fails the event."""
    try:
        props = component.get('CATEGORIES')
        props = [] if props is None else props if isinstance(props, list) else [props]
        values = {str(cat).strip() for prop in props for cat in getattr(prop, 'cats', ())} - {''}
    except Exception:  # noqa: BLE001 - a malformed category never drops the event
        return None
    if len(values) != 1:
        return None
    value = values.pop()
    return value if len(value) <= MAX_COURSE_REF else None


def _value(component, name):
    prop = component.get(name)
    if prop is None:
        return None
    if isinstance(prop, list):
        raise ValueError('duplicate_property')
    return prop.dt


def _aware(value, zone, *, tzid=None):
    if not isinstance(value, datetime):
        raise ValueError('invalid_time')
    if value.tzinfo is None:
        if tzid:
            raise ValueError('unknown_timezone')
        value = value.replace(tzinfo=zone)
    # Nonexistent local wall times must not be silently shifted across a DST gap.
    if value.astimezone(UTC).astimezone(value.tzinfo).replace(tzinfo=None) != value.replace(tzinfo=None):
        raise ValueError('nonexistent_time')
    return value.astimezone(UTC)


def _zone_or(name, fallback):
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - 'UTC' labels etc. resolve; anything else falls back to the source zone
        return fallback


def _instant(value, zone):
    """RDATE/EXDATE value → ISO date (all-day) or aware UTC ISO instant. Floating values use the event zone; like
    generated instances, a nonexistent wall time takes the offset before the gap (RFC 5545 §3.3.5)."""
    if isinstance(value, tuple):  # RDATE PERIOD → its start
        value = value[0]
    if not isinstance(value, datetime):
        return value.isoformat()
    return (value if value.tzinfo else value.replace(tzinfo=zone)).astimezone(UTC).isoformat()


def _event(component, default_timezone):
    if component.errors:
        raise ValueError('invalid_component')
    zone = ZoneInfo(default_timezone)
    uid = _text(component, 'UID', 512, required=True)
    recurrence = _value(component, 'RECURRENCE-ID')
    recurrence_id = ''
    if recurrence is not None:
        prop = component.get('RECURRENCE-ID')
        if prop.params.get('RANGE'):
            raise ValueError('unsupported_recurrence_range')
        recurrence_id = (_aware(recurrence, zone, tzid=prop.params.get('TZID')).isoformat()
                         if isinstance(recurrence, datetime) else recurrence.isoformat())
    status = _text(component, 'STATUS', 20)
    if status is not None and status.upper() not in {'CANCELLED', 'CONFIRMED', 'TENTATIVE'}:
        raise ValueError('invalid_status')
    cancelled = status is not None and status.upper() == 'CANCELLED'
    start = _value(component, 'DTSTART')
    finish = _value(component, 'DTEND')
    starts_on = ends_on = starts_at = ends_at = None
    all_day = type(start) is date
    event_timezone = default_timezone
    if start is not None:
        duration = _value(component, 'DURATION')
        if duration is not None and (not isinstance(duration, timedelta) or finish is not None):
            raise ValueError('invalid_duration')
        if all_day:
            starts_on = start
            if duration is not None and duration.seconds:
                raise ValueError('invalid_all_day_duration')
            ends_on = finish if finish is not None else start + (duration if duration is not None else timedelta(days=1))
            if type(ends_on) is not date or ends_on <= starts_on:
                raise ValueError('invalid_interval')
            starts_at = datetime.combine(starts_on, time.min, zone).astimezone(UTC)
            ends_at = datetime.combine(ends_on, time.min, zone).astimezone(UTC)
        else:
            prop = component.get('DTSTART')
            starts_at = _aware(start, zone, tzid=prop.params.get('TZID'))
            event_timezone = str(prop.params.get('TZID') or getattr(start.tzinfo, 'key', None) or
                                 ('UTC' if start.tzinfo else default_timezone))
            ends_at = (_aware(finish, zone, tzid=component.get('DTEND').params.get('TZID')) if finish is not None else
                       starts_at + (duration if duration is not None else timedelta()))
            if ends_at < starts_at:
                raise ValueError('invalid_interval')
    elif not cancelled:
        raise ValueError('missing_start')
    updated = _value(component, 'LAST-MODIFIED') or _value(component, 'DTSTAMP')
    if updated is not None:
        updated = _aware(updated, zone)
    sequence = int(component['SEQUENCE']) if 'SEQUENCE' in component else None
    if sequence is not None and (sequence < 0 or sequence > 2147483647):
        raise ValueError('invalid_sequence')
    rrule = component.get('RRULE')
    if isinstance(rrule, list):
        raise ValueError('duplicate_rule')
    recurrence_metadata = {}
    instant_zone = _zone_or(event_timezone, zone)
    for name in ['RDATE', 'EXDATE']:
        props = component.get(name)
        if props is not None:
            props = props if isinstance(props, list) else [props]
            recurrence_metadata[name] = [_instant(item.dt, instant_zone) for p in props for item in p.dts]
    if len(event_timezone) > 80 or len(recurrence_id) > 100:
        raise ValueError('invalid_timezone_or_recurrence_id')
    return ParsedEvent(uid, recurrence_id, _text(component, 'SUMMARY', 300, required=not cancelled),
                       _text(component, 'DESCRIPTION', 20000), _text(component, 'LOCATION', 500),
                       starts_at, ends_at, all_day, starts_on, ends_on, event_timezone,
                       'cancelled' if cancelled else 'active', rrule.to_ical().decode('ascii') if rrule else None,
                       json.dumps(recurrence_metadata, sort_keys=True) if recurrence_metadata else None,
                       sequence, updated, _course_ref(component))


def parse_ics(data: bytes, default_timezone: str = 'Europe/Prague') -> ParseResult:
    """Choose highest source revision per identity; conflicting equal revisions are rejected."""
    try:
        if not data or len(data) > MAX_FEED_BYTES:
            raise ValueError('feed_size')
        calendar = Calendar.from_ical(data)
        if calendar.name != 'VCALENDAR':
            raise ValueError('not_calendar')
        components = calendar.walk('VEVENT')
        if len(components) > MAX_EVENTS:
            raise ValueError('too_many_events')
    except Exception:
        return ParseResult((), 1)
    errors = 0
    complete = bool(components)
    uncertain = set()
    groups = {}
    for component in components:
        try:
            event = _event(component, default_timezone)
            groups.setdefault((event.external_uid, event.recurrence_id), []).append(event)
        except Exception:
            errors += 1
            uid = component.get('UID')
            if uid is None or isinstance(uid, list) or not str(uid).strip():
                complete = False  # an unidentifiable component could be any stored event
            else:
                uncertain.add(str(uid).strip())
    chosen = []
    for (uid, _recurrence), events in groups.items():
        rank = lambda e: (e.sequence or 0, e.source_updated_at or datetime.min.replace(tzinfo=UTC))
        best = max(events, key=rank)
        if any(rank(e) == rank(best) and e != best for e in events):
            errors += 1
            uncertain.add(uid)
            continue
        chosen.append(best)
    return ParseResult(tuple(chosen), errors, complete, frozenset(uncertain))
