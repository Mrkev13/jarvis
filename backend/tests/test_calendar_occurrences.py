"""MRK-40: recurrence occurrences (DST-correct, bounded) and source presence reconciliation. Synthetic feeds only."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from module_contracts import ContextRequest
from module_registry import ModuleAccess
from modules.calendar import integrations, service
from modules.calendar.models import CalendarEvent, CalendarSource
from modules.calendar.occurrences import (MAX_WINDOW, CalendarWindowError, get_calendar_occurrences,
                                          local_window)
from today_types import TodayContext

FIXTURES = Path(__file__).parent / 'fixtures/calendar'
NOW = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
PRAGUE = ZoneInfo('Europe/Prague')
UTC = timezone.utc


def feed(name):
    return (FIXTURES / name).read_bytes()


def ics(*events):
    body = ''.join('BEGIN:VEVENT\n' + e.strip() + '\nEND:VEVENT\n' for e in events)
    return ('BEGIN:VCALENDAR\nVERSION:2.0\n' + body + 'END:VCALENDAR\n').encode()


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def source(db):
    item = CalendarSource(kind='ics', name='Synthetic', config_key='moodle', enabled=True, timezone='Europe/Prague')
    db.add(item)
    db.flush()
    return item


def imported(db, source, data):
    stats = service.import_ics(db, source, data, now=NOW)
    db.commit()
    return stats


def between(db, start, end):
    return get_calendar_occurrences(db, *local_window(start, end))


def local(o):
    return o.starts_at.astimezone(PRAGUE)


# ---------- recurrence ----------

def test_weekly_prague_lecture_keeps_wall_clock_across_autumn_dst_with_exdate_rdate_and_overrides(db, source):
    assert imported(db, source, feed('recurring.ics'))['errors'] == 0
    lecture = [o for o in between(db, date(2026, 10, 12), date(2026, 11, 12))
               if o.title.startswith('Synthetic') and 'lecture' in o.title]
    got = [(local(o).date().isoformat(), local(o).strftime('%H:%M'), o.title) for o in lecture]
    assert got == [
        ('2026-10-13', '10:00', 'Synthetic weekly lecture'),   # CEST, 08:00 UTC
        ('2026-10-21', '14:00', 'Synthetic moved lecture'),    # RECURRENCE-ID 20.10. moved
        # 27.10. cancelled override: removed
        ('2026-10-31', '09:00', 'Synthetic weekly lecture'),   # RDATE extra occurrence
        # 3.11. EXDATE: removed
        ('2026-11-10', '10:00', 'Synthetic weekly lecture'),   # CET, 09:00 UTC; UNTIL inclusive
    ]
    first, last = lecture[0], lecture[-1]
    assert first.starts_at.hour == 8 and last.starts_at.hour == 9, 'UTC shifts, Prague wall clock does not'
    assert last.ends_at - last.starts_at == timedelta(minutes=90)
    assert first.recurring and first.key == f'{first.event_id}@{first.recurrence_key}'
    assert not lecture[1].recurring  # the override is its own stored record


def test_spring_dst_count_nonexistent_and_ambiguous_times(db, source):
    imported(db, source, ics(
        'UID:spring@test.invalid\nDTSTART;TZID=Europe/Prague:20260317T100000\nDTEND;TZID=Europe/Prague:20260317T110000\n'
        'RRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:Spring',
        'UID:gap@test.invalid\nDTSTART;TZID=Europe/Prague:20260322T023000\nRRULE:FREQ=WEEKLY;COUNT=2\nSUMMARY:Gap',
        'UID:fold@test.invalid\nDTSTART;TZID=Europe/Prague:20261018T023000\nRRULE:FREQ=WEEKLY;COUNT=2\nSUMMARY:Fold'))
    spring = [o for o in between(db, date(2026, 3, 1), date(2026, 5, 1)) if o.title == 'Spring']
    assert [o.starts_at.astimezone(UTC).strftime('%m-%d %H:%M') for o in spring] == ['03-17 09:00', '03-24 09:00', '03-31 08:00']
    assert {local(o).strftime('%H:%M') for o in spring} == {'10:00'}
    assert len(spring) == 3, 'COUNT bounds the series'
    gap = [o for o in between(db, date(2026, 3, 1), date(2026, 5, 1)) if o.title == 'Gap']
    # 29.3. 02:30 does not exist → offset before the gap (RFC 5545): 01:30 UTC = 03:30 CEST
    assert [o.starts_at.astimezone(UTC).isoformat() for o in gap] == ['2026-03-22T01:30:00+00:00', '2026-03-29T01:30:00+00:00']
    assert local(gap[1]).strftime('%H:%M') == '03:30'
    fold = [o for o in between(db, date(2026, 10, 1), date(2026, 11, 1)) if o.title == 'Fold']
    # 25.10. 02:30 happens twice → the first one (CEST, 00:30 UTC)
    assert fold[1].starts_at.astimezone(UTC).isoformat() == '2026-10-25T00:30:00+00:00'


def test_until_forms_byday_interval_and_all_day_recurrence(db, source):
    imported(db, source, feed('recurring.ics'))
    window = between(db, date(2026, 10, 1), date(2026, 12, 1))
    seminar = [o for o in window if o.title == 'Synthetic seminar']
    assert [o.starts_at.date().isoformat() for o in seminar] == ['2026-10-12', '2026-10-14', '2026-10-26', '2026-10-28']
    block = [o for o in window if o.title == 'Synthetic all-day block']
    assert [(o.starts_on.isoformat(), o.ends_on.isoformat()) for o in block] == [
        ('2026-10-19', '2026-10-20'), ('2026-10-26', '2026-10-27'), ('2026-11-02', '2026-11-03')], 'dates never shift at DST'
    assert all(o.all_day and o.recurring for o in block)
    # a second source, so this snapshot does not mark the first source's records missing
    other = CalendarSource(kind='ics', name='Other', enabled=True, timezone='Europe/Prague')
    db.add(other)
    db.flush()
    service.import_ics(db, other, ics(
        'UID:until-date@test.invalid\nDTSTART;TZID=Europe/Prague:20261013T100000\nRRULE:FREQ=DAILY;UNTIL=20261015\nSUMMARY:Until date',
        'UID:until-local@test.invalid\nDTSTART;TZID=Europe/Prague:20261013T100000\nRRULE:FREQ=DAILY;UNTIL=20261014T100000\nSUMMARY:Until local'), now=NOW)
    db.commit()
    window = between(db, date(2026, 10, 1), date(2026, 11, 1))
    assert len([o for o in window if o.title == 'Until date']) == 3
    assert len([o for o in window if o.title == 'Until local']) == 2


def test_infinite_rule_is_bounded_by_the_window_and_windows_are_capped(db, source):
    imported(db, source, ics('UID:forever@test.invalid\nDTSTART;TZID=Europe/Prague:20200106T100000\n'
                             'DTEND;TZID=Europe/Prague:20200106T110000\nRRULE:FREQ=WEEKLY\nSUMMARY:Forever'))
    week = between(db, date(2026, 10, 12), date(2026, 10, 19))
    assert [(local(o).date().isoformat(), local(o).strftime('%H:%M')) for o in week] == [('2026-10-12', '10:00')]
    assert len(between(db, date(2026, 1, 1), date(2027, 1, 1))) == 52
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(CalendarWindowError):
        get_calendar_occurrences(db, start, start + MAX_WINDOW + timedelta(days=1))
    with pytest.raises(CalendarWindowError):
        get_calendar_occurrences(db, start, start)
    with pytest.raises(CalendarWindowError):
        get_calendar_occurrences(db, start.replace(tzinfo=None), start.replace(tzinfo=None) + timedelta(days=1))
    assert len(get_calendar_occurrences(db, *local_window(date(2026, 1, 1), date(2027, 1, 1)), limit=5)) == 5


def test_sub_daily_rules_are_not_expanded(db, source):
    imported(db, source, ics('UID:minutely@test.invalid\nDTSTART:20261012T080000Z\nRRULE:FREQ=MINUTELY\nSUMMARY:Noise'))
    assert len(between(db, date(2026, 10, 12), date(2026, 10, 13))) == 1


def test_today_ai_context_and_page_use_actual_occurrences(db, source):
    imported(db, source, feed('recurring.ics'))
    # Tuesday 10.11.: the 5th week of the lecture – invisible before MRK-40 (only the first instance existed)
    day = date(2026, 11, 10)
    context = TodayContext(db, NOW.replace(tzinfo=None), day, datetime(2026, 11, 10, 8))
    items = integrations.timeline(context)
    assert [(i.title, i.time) for i in items] == [('Synthetic weekly lecture', '10:00')]
    assert items[0].id.startswith('calendar_event:') and '@' in items[0].id and items[0].href.startswith('/calendar?event=')
    upcoming = integrations.upcoming(TodayContext(db, NOW.replace(tzinfo=None), date(2026, 10, 14), datetime(2026, 10, 14, 8)))
    assert len({i.id for i in upcoming}) == len(upcoming), 'each instance is a distinct Today item'
    assert any(i.title == 'Synthetic moved lecture' for i in upcoming)
    text = ' '.join(integrations.context_events(ContextRequest(db, day, NOW)))
    assert 'Synthetic weekly lecture' in text and '2026-11-10 10:00' in text
    page = service.list_calendar(db, today=date(2026, 10, 12))
    keys = [e['key'] for e in page['events']]
    assert len(keys) == len(set(keys))
    assert sum(e['title'] == 'Synthetic weekly lecture' for e in page['events']) == 3  # 13.10., 31.10., 10.11.
    assert all(e['state'] == 'active' for e in page['events'])
    assert any(h['state'] == 'cancelled' for h in page['history'])  # the cancelled 27.10. override
    assert 'rrule' not in page['events'][0] and 'recurrence_key' not in page['events'][0]


def test_occurrence_api_is_bounded_and_authenticated(db, source, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    imported(db, source, feed('recurring.ics'))
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    try:
        with patch.object(main, 'auth_enabled', return_value=True), patch.object(main, 'validate_session_token', return_value=None):
            assert client.get('/calendar/occurrences?start=2026-10-12&end=2026-10-19').status_code == 401
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({'calendar': False})):
            assert client.get('/calendar/occurrences?start=2026-10-12&end=2026-10-19').status_code == 404
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({})):
            ok = client.get('/calendar/occurrences?start=2026-10-12&end=2026-11-12')
            assert ok.status_code == 200
            titles = [o['title'] for o in ok.json()['occurrences']]
            assert titles.count('Synthetic weekly lecture') == 3
            assert client.get('/calendar/occurrences?start=2026-10-12&end=2026-10-12').status_code == 422
            assert client.get('/calendar/occurrences?start=2026-01-01&end=2026-12-31').status_code == 422
            assert client.get('/calendar/occurrences?start=nope&end=2026-10-12').status_code == 422
    finally:
        client.close()


# ---------- source presence ----------

def test_feed_a_b_c_marks_missing_then_restores_the_same_record(db, source):
    assert imported(db, source, feed('presence-a.ics'))['created'] == 2
    dropped = db.query(CalendarEvent).filter_by(external_uid='drop@test.invalid').one()
    identity = dropped.id
    day = date(2026, 10, 12)
    assert len(between(db, day, day + timedelta(days=1))) == 2

    stats = imported(db, source, feed('presence-b.ics'))
    assert stats['missing'] == 1 and stats['unchanged'] == 1
    assert dropped.source_missing_at == NOW and dropped.status == 'active', 'missing is not cancellation'
    assert db.query(CalendarEvent).count() == 2, 'history retained, nothing deleted'
    assert [o.title for o in between(db, day, day + timedelta(days=1))] == ['Synthetic kept lecture']
    context = TodayContext(db, NOW.replace(tzinfo=None), day, datetime(2026, 10, 12, 7))
    assert [i.title for i in integrations.timeline(context)] == ['Synthetic kept lecture']
    assert imported(db, source, feed('presence-b.ics'))['missing'] == 0, 'no per-sync noise'

    stats = imported(db, source, feed('presence-a.ics'))  # feed C: it is back, unchanged
    assert stats['restored'] == 1 and stats['created'] == 0
    assert db.query(CalendarEvent).count() == 2 and dropped.id == identity and dropped.source_missing_at is None
    assert len(between(db, day, day + timedelta(days=1))) == 2
    facts = [f.event_type for f in db.query(models.DomainEvent).filter_by(module_id='calendar').order_by(models.DomainEvent.id)]
    assert facts == ['calendar.event.created', 'calendar.event.created', 'calendar.event.source_missing', 'calendar.event.restored']
    activity = db.query(models.ActivityLog).filter_by(area='calendar').all()
    assert len(activity) == 4, 'one Activity projection per fact, no duplicates'
    from change_feed import build
    feed_items = build(db, ModuleAccess({}), since=NOW - timedelta(hours=1), modules=None, limit=100)['items']
    assert sorted(i['kind'] for i in feed_items) == ['created', 'created', 'restored', 'source_missing']
    assert all(i['source'] == 'event' for i in feed_items)


def test_restore_with_changed_content_is_one_fact(db, source):
    imported(db, source, feed('presence-a.ics'))
    imported(db, source, feed('presence-b.ics'))
    changed = feed('presence-a.ics').replace(b'Synthetic dropped lecture', b'Synthetic renamed lecture')
    stats = imported(db, source, changed)
    assert stats['restored'] == 1 and stats['updated'] == 0
    row = db.query(CalendarEvent).filter_by(external_uid='drop@test.invalid').one()
    assert row.title == 'Synthetic renamed lecture' and row.source_missing_at is None
    assert db.query(models.DomainEvent).filter_by(event_type='calendar.event.restored').count() == 1


@pytest.mark.parametrize('bad', [
    b'',                                                    # unreadable / failed download body
    b'BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n',        # no VEVENT at all: not proof everything ended
    b'not an ics token=canary',                             # malformed whole feed
    ics('DTSTART:20261012T080000Z\nSUMMARY:No UID'),        # unidentifiable component → incomplete snapshot
])
def test_incomplete_or_failed_snapshots_never_hide_events(db, source, bad):
    imported(db, source, feed('presence-a.ics'))
    stats = imported(db, source, bad)
    assert stats['missing'] == 0
    assert db.query(CalendarEvent).filter(CalendarEvent.source_missing_at.isnot(None)).count() == 0


def test_malformed_component_with_known_uid_protects_that_identity(db, source):
    imported(db, source, feed('presence-a.ics'))
    partial = ics('UID:keep@test.invalid\nDTSTART:20261012T080000Z\nDTEND:20261012T090000Z\nSUMMARY:Synthetic kept lecture',
                  'UID:drop@test.invalid\nDTSTART:NOT-A-DATE\nSUMMARY:Broken')
    stats = imported(db, source, partial)
    assert stats['errors'] == 1 and stats['missing'] == 0


def test_failed_fetch_never_reconciles(db, source, monkeypatch):
    imported(db, source, feed('presence-a.ics'))
    monkeypatch.setenv('MOODLE_ICS_URL', 'https://feed.example.invalid/?token=secret-canary')

    def fail(url):
        raise OSError('network down')
    with pytest.raises(service.CalendarSyncError):
        service.sync_moodle(db, fetch=fail, now=NOW)
    db.rollback()
    assert db.query(CalendarEvent).filter(CalendarEvent.source_missing_at.isnot(None)).count() == 0


def test_rollback_discards_presence_changes(db, source):
    imported(db, source, feed('presence-a.ics'))
    service.import_ics(db, source, feed('presence-b.ics'), now=NOW)
    db.rollback()
    assert db.query(CalendarEvent).filter(CalendarEvent.source_missing_at.isnot(None)).count() == 0
    assert db.query(models.DomainEvent).filter_by(event_type='calendar.event.source_missing').count() == 0


def test_missing_override_reverts_to_the_generated_instance_and_master_missing_hides_series(db, source):
    imported(db, source, feed('recurring.ics'))
    without_override = feed('recurring.ics').replace(
        b'BEGIN:VEVENT\nUID:weekly-prague@test.invalid\nRECURRENCE-ID;TZID=Europe/Prague:20261020T100000\n'
        b'DTSTART;TZID=Europe/Prague:20261021T140000\nDTEND;TZID=Europe/Prague:20261021T153000\n'
        b'SUMMARY:Synthetic moved lecture\nEND:VEVENT\n', b'')
    assert without_override != feed('recurring.ics')
    assert imported(db, source, without_override)['missing'] == 1
    titles = [(local(o).date().isoformat(), o.title) for o in between(db, date(2026, 10, 19), date(2026, 10, 23)) if not o.all_day]
    assert titles == [('2026-10-20', 'Synthetic weekly lecture')]
    only_seminar = ics('UID:count-byday@test.invalid\nDTSTART:20261012T070000Z\nDTEND:20261012T080000Z\n'
                       'RRULE:FREQ=WEEKLY;BYDAY=MO,WE;INTERVAL=2;COUNT=4\nSUMMARY:Synthetic seminar')
    imported(db, source, only_seminar)
    assert {o.title for o in between(db, date(2026, 10, 1), date(2026, 12, 1))} == {'Synthetic seminar'}


# ---------- Search policy: only currently relevant facts ----------

def _search_titles(db):
    return sorted(title for _type, _id, title, *_rest in integrations.search_events(db, 'lecture'))


def test_search_shows_active_events_hides_source_missing_and_shows_restored_again(db, source):
    imported(db, source, feed('presence-a.ics'))
    assert _search_titles(db) == ['Synthetic dropped lecture', 'Synthetic kept lecture'], 'active events appear'

    imported(db, source, feed('presence-b.ics'))
    dropped = db.query(CalendarEvent).filter_by(external_uid='drop@test.invalid').one()
    assert dropped.source_missing_at is not None
    assert _search_titles(db) == ['Synthetic kept lecture'], 'source-missing event is not a search result'
    assert db.query(CalendarEvent).count() == 2, 'the durable row is kept, only hidden from Search'

    imported(db, source, feed('presence-a.ics'))
    assert dropped.source_missing_at is None
    assert _search_titles(db) == ['Synthetic dropped lecture', 'Synthetic kept lecture'], 'restored event appears again'


def _event(uid, title, start, extra=''):
    lines = [f'UID:{uid}', f'SUMMARY:{title}', f'DTSTART;TZID=Europe/Prague:{start}',
             f'DTEND;TZID=Europe/Prague:{start[:9]}{int(start[9:11]) + 1:02d}{start[11:]}']
    return '\n'.join(lines + ([extra] if extra else []))


def test_search_hides_cancelled_events_through_global_search(db, source):
    import search_service

    imported(db, source, ics(_event('cancel-me@test.invalid', 'Synthetic cancelled seminar', '20261012T090000'),
                             _event('stay@test.invalid', 'Synthetic staying seminar', '20261012T110000')))

    def found():
        result = search_service.search(db, 'seminar', access=ModuleAccess({'calendar': True}))
        return sorted(r['title'] for r in result['results'] if r['type'] == 'calendar_event')

    assert found() == ['Synthetic cancelled seminar', 'Synthetic staying seminar']
    imported(db, source, ics(_event('cancel-me@test.invalid', 'Synthetic cancelled seminar', '20261012T090000',
                                   extra='STATUS:CANCELLED\nSEQUENCE:1'),
                             _event('stay@test.invalid', 'Synthetic staying seminar', '20261012T110000')))
    cancelled = db.query(CalendarEvent).filter_by(external_uid='cancel-me@test.invalid').one()
    assert cancelled.status == 'cancelled' and cancelled.source_missing_at is None
    assert found() == ['Synthetic staying seminar'], 'cancelled event is not a search result'
    assert db.query(CalendarEvent).count() == 2, 'the cancelled row is kept as history'


def test_synthetic_fixtures_are_checked_out_byte_exact():
    # .gitattributes keeps these LF-stored fixtures from being converted to CRLF on Windows checkouts; tests that
    # edit fixture bytes (e.g. removing an override) would otherwise silently compare unchanged feeds.
    for path in FIXTURES.glob('*.ics'):
        assert b'\r\n' not in path.read_bytes(), f'{path.name} was checked out with converted line endings'
