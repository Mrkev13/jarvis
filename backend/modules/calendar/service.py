"""Explicit, caller-owned import transaction; no scheduler, secret logging or hard deletion."""
from dataclasses import fields
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from domain_events import ActivityProjection, append_domain_event
from env_config import env_str
from modules.calendar.models import CalendarEvent, CalendarSource, now_utc
from modules.calendar.parser import MAX_FEED_BYTES, ParsedEvent, parse_ics
from time_utils import APP_TZ, today_local

BUSINESS_FIELDS = ('title', 'description', 'location', 'starts_at', 'ends_at', 'all_day', 'starts_on', 'ends_on',
                   'timezone', 'status', 'rrule', 'recurrence_metadata')
AUDIT_FIELDS = ('title', 'location', 'starts_at', 'ends_at', 'all_day', 'starts_on', 'ends_on', 'status')


class CalendarSyncError(ValueError):
    def __init__(self, category='feed_unavailable'):
        allowed = {'feed_unavailable', 'feed_redirect_rejected', 'invalid_feed_configuration', 'feed_size_limit',
                   'source_disabled', 'feed_not_configured'}
        self.category = category if category in allowed else 'feed_unavailable'
        super().__init__(self.category)


def feed_url():
    # Preserve the locally established name; optional alias for installations without it.
    return env_str('MOODLE_ICS_URL') or env_str('CALENDAR_MOODLE_ICS_URL')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CalendarSyncError('feed_redirect_rejected')


def fetch_feed(url: str) -> bytes:
    """Only server-configured HTTPS, TLS verified, no redirects or URL-bearing logging."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise CalendarSyncError('invalid_feed_configuration')
        opener = build_opener(_NoRedirect(), HTTPSHandler(debuglevel=0))
        with opener.open(Request(url, headers={'Accept': 'text/calendar'}), timeout=15) as response:
            data = response.read(MAX_FEED_BYTES + 1)
        if not data or len(data) > MAX_FEED_BYTES:
            raise CalendarSyncError('feed_size_limit')
        return data
    except CalendarSyncError:
        raise
    except Exception:
        # urllib exceptions may contain the entire bearer URL; discard them.
        raise CalendarSyncError() from None


def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _rank(sequence, updated):
    return sequence, updated or datetime.min.replace(tzinfo=timezone.utc)


def import_ics(db, source: CalendarSource, data: bytes, *, now=None) -> dict:
    """Idempotent source/UID/recurrence upsert. Missing identities remain untouched."""
    stats = dict(created=0, updated=0, unchanged=0, cancelled=0, errors=0)
    # PostgreSQL row lock serializes every import for this source until caller commit.
    # Refresh identity-map values too: a cached ORM row is not current source truth.
    db.flush()
    source = (db.query(CalendarSource).filter_by(id=source.id).populate_existing().with_for_update().one())
    if not source.enabled:
        raise CalendarSyncError('source_disabled')
    now = now or now_utc()
    if now.tzinfo is None:
        raise ValueError('Calendar import time must be aware')
    parsed = parse_ics(data, source.timezone)
    stats['errors'] = parsed.errors
    for incoming in parsed.events:
        row = db.query(CalendarEvent).filter_by(source_id=source.id, external_uid=incoming.external_uid,
                                               recurrence_id=incoming.recurrence_id).populate_existing().one_or_none()
        created = row is None
        sequence = incoming.sequence if incoming.sequence is not None else (row.sequence if row else 0)
        source_updated = incoming.source_updated_at or (row.source_updated_at if row else None)
        if row is not None and _rank(sequence, source_updated) < _rank(row.sequence, row.source_updated_at):
            stats['unchanged'] += 1
            continue
        if created and incoming.starts_at is None:
            stats['errors'] += 1  # identity-only cancellation needs an existing historical record
            continue
        values = {f.name: getattr(incoming, f.name) for f in fields(ParsedEvent) if f.name in BUSINESS_FIELDS}
        if incoming.starts_at is None:
            for name in BUSINESS_FIELDS:
                if name != 'status' and (name != 'title' or incoming.title is None):
                    values[name] = getattr(row, name)
        if values['title'] is None:
            values['title'] = 'Zrušená událost'
        before = {name: _iso(getattr(row, name)) for name in AUDIT_FIELDS} if row is not None else {}
        changed = [name for name in BUSINESS_FIELDS if row is None or getattr(row, name) != values[name]]
        if not changed:
            # A newer revision watermark prevents later stale source data rolling back facts.
            # It is not a business change and emits no activity/domain event.
            if _rank(sequence, source_updated) > _rank(row.sequence, row.source_updated_at):
                row.sequence, row.source_updated_at = sequence, source_updated
            stats['unchanged'] += 1
            continue
        if created:
            row = CalendarEvent(source_id=source.id, external_uid=incoming.external_uid,
                                recurrence_id=incoming.recurrence_id, created_at=now)
            db.add(row)
        for name, value in values.items():
            setattr(row, name, value)
        row.sequence = sequence
        row.source_updated_at = source_updated
        row.imported_at = row.updated_at = now
        row.cancelled_at = (row.cancelled_at or now) if row.status == 'cancelled' else None
        db.flush()
        action = 'cancelled' if row.status == 'cancelled' and (created or before['status'] != 'cancelled') else ('created' if created else 'updated')
        stats[action] += 1
        after = {name: _iso(getattr(row, name)) for name in AUDIT_FIELDS}
        delta = {name: {'old': before.get(name), 'new': after[name]} for name in AUDIT_FIELDS if before.get(name) != after[name]}
        label = {'created': 'Přidána událost', 'cancelled': 'Zrušena událost', 'updated': 'Změněna událost'}[action]
        if action == 'updated' and any(name in changed for name in ('starts_at', 'ends_at', 'starts_on', 'ends_on')):
            label = 'Změněn čas události'
        append_domain_event(db, event_type=f'calendar.event.{action}', aggregate_type='calendar_event', aggregate_id=row.id,
                            payload={'event_id': row.id, 'source_id': source.id, 'status': row.status,
                                     'starts_at': row.starts_at.isoformat(), 'ends_at': row.ends_at.isoformat(),
                                     'all_day': row.all_day}, now=now,
                            activity=ActivityProjection('calendar', 'cancel' if action == 'cancelled' else ('create' if created else 'update'),
                                                        f"{label}: {row.title}", 'calendar_event', row.id, delta, 'ics_import'))
    return stats


def sync_moodle(db, *, fetch=None, now=None):
    url = feed_url()
    if not url:
        raise CalendarSyncError('feed_not_configured')
    source = db.query(CalendarSource).filter_by(config_key='moodle').one_or_none()
    if source is not None and not source.enabled:
        raise CalendarSyncError('source_disabled')
    try:
        data = (fetch or fetch_feed)(url)
    except CalendarSyncError:
        raise
    except Exception:
        raise CalendarSyncError() from None
    if source is None:
        # Conflict-safe bootstrap: concurrent first syncs converge on one source.
        insert = postgres_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
        db.execute(insert(CalendarSource).values(kind='ics', name='Moodle', config_key='moodle', enabled=True,
                   timezone=APP_TZ.key).on_conflict_do_nothing(index_elements=['config_key']))
        source = db.query(CalendarSource).filter_by(config_key='moodle').one()
    return import_ics(db, source, data, now=now)


def event_dict(row):
    # No configuration, raw UID/ICS, description or private feed URL in page/list payloads.
    return {name: _iso(getattr(row, name)) for name in
            ('id', 'source_id', 'title', 'location', 'starts_at', 'ends_at', 'all_day', 'starts_on', 'ends_on',
             'timezone', 'status', 'cancelled_at', 'rrule')}


def list_calendar(db, *, today=None, event_id=None):
    today = today or today_local()
    # Include recent cancelled records without allowing an unbounded history response.
    lower = datetime.combine(today - timedelta(days=7), time.min, APP_TZ).astimezone(timezone.utc)
    upper = datetime.combine(today + timedelta(days=60), time.min, APP_TZ).astimezone(timezone.utc)
    rows = (db.query(CalendarEvent).filter(CalendarEvent.ends_at >= lower, CalendarEvent.starts_at < upper)
            .order_by(CalendarEvent.starts_at, CalendarEvent.id).limit(500).all())
    if event_id is not None and not any(e.id == event_id for e in rows):
        selected = db.get(CalendarEvent, event_id)
        if selected is not None:
            rows.append(selected)
            rows.sort(key=lambda e: (e.starts_at, e.id))
    sources = [{'id': s.id, 'kind': s.kind, 'name': s.name, 'enabled': s.enabled,
                'configured': bool(feed_url()) if s.config_key == 'moodle' else False}
               for s in db.query(CalendarSource).order_by(CalendarSource.id).all()]
    return {'today': today.isoformat(), 'events': [event_dict(e) for e in rows], 'sources': sources,
            'moodle_configured': bool(feed_url())}
