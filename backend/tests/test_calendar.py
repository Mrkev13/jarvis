"""Synthetic Calendar feeds only; no real feed, production DB or LLM."""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from module_registry import ModuleAccess
from modules.calendar import parser, service, integrations
from modules.calendar.models import CalendarEvent, CalendarSource
from module_contracts import ContextRequest
from today_types import TodayContext

FIXTURES = Path(__file__).parent / 'fixtures/calendar'
NOW = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)


def feed(name):
    return (FIXTURES / name).read_bytes()


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


def test_parser_timezone_date_text_and_duplicates():
    parsed = parser.parse_ics(feed('basic.ics'))
    assert parsed.errors == 0 and len(parsed.events) == 3
    lecture = parsed.events[0]
    assert lecture.starts_at == datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    assert lecture.description == 'Line one\nLine two, escaped; text'
    assert lecture.location == 'Room A, building B'
    assert parsed.events[1].starts_on == date(2026, 10, 9)
    assert parsed.events[1].ends_on == date(2026, 10, 11)
    mixed = parser.parse_ics(feed('mixed.ics'))
    assert mixed.errors == 1
    assert len(mixed.events) == 3
    assert next(e for e in mixed.events if e.external_uid.startswith('duplicate')).title == 'Newer synthetic duplicate'
    assert next(e for e in mixed.events if e.rrule).rrule == 'FREQ=WEEKLY;COUNT=3'
    assert next(e for e in mixed.events if e.recurrence_id).recurrence_id.endswith('+00:00')


def test_import_idempotent_changed_cancelled_missing_retained(db, source):
    first = service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    assert first == {'created': 3, 'updated': 0, 'unchanged': 0, 'cancelled': 0, 'errors': 0, 'missing': 0, 'restored': 0}
    before = db.query(CalendarEvent).filter_by(external_uid='lecture-1@test.invalid').one()
    identity = before.id
    stamp = before.updated_at
    events = db.query(models.DomainEvent).count()
    second = service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    assert second['unchanged'] == 3 and db.query(CalendarEvent).count() == 3
    assert before.updated_at == stamp and db.query(models.DomainEvent).count() == events
    assert service.import_ics(db, source, feed('changed.ics'), now=NOW)['updated'] == 1
    db.commit()
    assert before.id == identity and before.title == 'Synthetic changed lecture'
    assert before.starts_at.hour == 13 and before.starts_at.tzinfo is not None
    assert service.import_ics(db, source, feed('cancelled.ics'), now=NOW)['cancelled'] == 1
    db.commit()
    assert before.status == 'cancelled' and before.cancelled_at == NOW
    assert db.query(CalendarEvent).count() == 3
    assert service.import_ics(db, source, feed('cancelled.ics'), now=NOW)['unchanged'] == 1
    db.commit()
    facts = db.query(models.DomainEvent).filter_by(module_id='calendar').all()
    # MRK-40: changed.ics/cancelled.ics are complete snapshots holding only lecture-1 → the other two records go
    # source-missing once (retained, never deleted); repeating the same snapshot adds nothing.
    assert [f.event_type for f in facts].count('calendar.event.source_missing') == 2
    assert len(facts) == 7 and facts[-1].event_type == 'calendar.event.cancelled'
    assert db.query(CalendarEvent).filter(CalendarEvent.source_missing_at.isnot(None)).count() == 2
    assert all('Synthetic' not in json.dumps(f.payload) for f in facts)


def test_bad_component_and_whole_feed_preserve_good_data(db, source):
    service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    assert service.import_ics(db, source, feed('mixed.ics'), now=NOW)['errors'] == 1
    db.commit()
    assert db.query(CalendarEvent).count() == 6
    stats = service.import_ics(db, source, b'private invalid feed token=canary', now=NOW)
    assert stats['errors'] == 1 and stats['created'] == 0
    assert 'canary' not in repr(stats)


def test_source_identity_stale_versions_and_atomic_rollback(db, source):
    service.import_ics(db, source, feed('changed.ics'), now=NOW)
    db.commit()
    identity = db.query(CalendarEvent).one().id
    assert service.import_ics(db, source, feed('basic.ics'), now=NOW)['unchanged'] == 1
    db.commit()
    assert db.get(CalendarEvent, identity).title == 'Synthetic changed lecture'
    other = CalendarSource(kind='ics', name='Other', enabled=True, timezone='Europe/Prague')
    db.add(other)
    db.flush()
    service.import_ics(db, other, feed('changed.ics'), now=NOW)
    db.rollback()
    assert db.query(CalendarEvent).count() == 3
    assert db.query(models.DomainEvent).count() == 3


def test_contributions_today_search_context_changes_and_disabled(db, source):
    service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    context = TodayContext(db, NOW.replace(tzinfo=None), date(2026, 10, 9), datetime(2026, 10, 9, 12))
    items = integrations.timeline(context)
    assert len(items) == 2
    assert next(i for i in items if i.title == 'Synthetic lecture').time == '14:00'
    assert next(i for i in items if 'two-day' in i.title).time is None
    assert len(integrations.upcoming(context)) == 1
    assert all(i.href.startswith('/calendar?event=') and not i.actions for i in items)
    assert list(integrations.search_events(db, 'Room'))
    text = integrations.context_events(ContextRequest(db, context.today, NOW))
    assert 'Synthetic lecture' in ' '.join(text)
    assert 'description' not in ' '.join(text).lower()
    access = ModuleAccess({'calendar': False})
    for key in ['search', 'today', 'context', 'changes']:
        assert not any(owner == 'calendar' for owner, _ in access.contributions(key))
    from change_feed import build
    result = build(db, ModuleAccess({}), since=NOW.replace(hour=0), modules=None, limit=100)
    assert any(i['module_id'] == 'calendar' for i in result['items'])


def test_secret_safe_sync_and_api_metadata(db, monkeypatch, caplog):
    monkeypatch.setenv('MOODLE_ICS_URL', 'https://feed.example.invalid/private?token=secret-canary')
    def fail(url):
        raise RuntimeError(url)
    with pytest.raises(service.CalendarSyncError) as error:
        service.sync_moodle(db, fetch=fail)
    assert 'secret-canary' not in str(error.value) + caplog.text
    stats = service.sync_moodle(db, fetch=lambda _: feed('basic.ics'), now=NOW)
    db.commit()
    assert stats['created'] == 3
    payload = service.list_calendar(db, today=date(2026, 10, 9))
    assert 'secret-canary' not in json.dumps(payload)
    assert 'external_uid' not in json.dumps(payload)
    assert payload['sources'][0]['configured'] is True


@pytest.mark.parametrize('body,expected', [
    ('UID:floating@test.invalid\nDTSTART:20261009T140000\nSUMMARY:Floating', 0),
    ('UID:missing-end@test.invalid\nDTSTART;VALUE=DATE:20261009\nSUMMARY:One day', 0),
    ('UID:gap@test.invalid\nDTSTART;TZID=Europe/Prague:20260329T023000\nSUMMARY:DST gap', 1),
    ('UID:bad-zone@test.invalid\nDTSTART;TZID=Invalid/Secret:20261009T140000\nSUMMARY:Bad zone', 1),
    ('UID:negative@test.invalid\nDTSTART:20261009T140000Z\nDTEND:20261009T130000Z\nSUMMARY:Negative', 1),
    ('UID:duration@test.invalid\nDTSTART:20261009T140000Z\nDURATION:PT1H\nSUMMARY:Duration', 0),
])
def test_parser_validation_boundaries(body, expected):
    result = parser.parse_ics(('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n' + body + '\nEND:VEVENT\nEND:VCALENDAR\n').encode())
    assert result.errors == expected
    if not expected:
        assert result.events[0].starts_at.tzinfo is not None
        assert result.events[0].ends_at >= result.events[0].starts_at


def test_conflicting_equal_uid_revision_rejected_and_feed_limit():
    one = 'BEGIN:VEVENT\nUID:conflict@test.invalid\nDTSTART:20261009T140000Z\nSUMMARY:One\nEND:VEVENT\n'
    data = ('BEGIN:VCALENDAR\nVERSION:2.0\n' + one + one.replace('SUMMARY:One', 'SUMMARY:Two') + 'END:VCALENDAR\n').encode()
    result = parser.parse_ics(data)
    assert result.errors == 1 and not result.events
    assert parser.parse_ics(b'x' * (parser.MAX_FEED_BYTES + 1)).errors == 1


def test_all_day_dst_exclusive_end(db, source):
    data = b'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:dst@test.invalid\nDTSTART;VALUE=DATE:20260329\nDTEND;VALUE=DATE:20260330\nSUMMARY:Synthetic DST date\nEND:VEVENT\nEND:VCALENDAR\n'
    service.import_ics(db, source, data, now=NOW)
    db.commit()
    event = db.query(CalendarEvent).one()
    assert (event.ends_at - event.starts_at).total_seconds() == 23 * 3600
    context = TodayContext(db, NOW.replace(tzinfo=None), date(2026, 3, 30), datetime(2026, 3, 30))
    assert integrations.timeline(context) == []


def test_fetch_failure_and_redirect_never_expose_url(monkeypatch, caplog):
    url = 'https://feed.example.invalid/?token=secret-canary'
    class Broken:
        def open(self, request, **kwargs):
            assert kwargs['timeout'] == 15
            raise OSError(request.full_url)
    monkeypatch.setattr(service, 'build_opener', lambda *args: Broken())
    with pytest.raises(service.CalendarSyncError) as failure:
        service.fetch_feed(url)
    assert str(failure.value) == 'feed_unavailable'
    assert 'secret-canary' not in caplog.text + str(failure.value)
    with pytest.raises(service.CalendarSyncError, match='feed_redirect_rejected'):
        service._NoRedirect().redirect_request(None, None, 302, None, None, url)
    with pytest.raises(service.CalendarSyncError, match='invalid_feed_configuration'):
        service.fetch_feed('http://example.invalid/?token=secret-canary')


def test_actual_aggregators_module_disable_and_event_rollback(db, source):
    from search_service import search
    from today_service import build_today
    from context_service import build_current_context
    from change_feed import build
    service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    on, off = ModuleAccess({}), ModuleAccess({'calendar': False})
    assert any(item['type'] == 'calendar_event' for item in search(db, 'Synthetic', access=on)['results'])
    assert not any(item['type'] == 'calendar_event' for item in search(db, 'Synthetic', access=off)['results'])
    assert 'Synthetic lecture' in str(build_today(db, now_utc=NOW.replace(tzinfo=None), access=on))
    assert 'Synthetic lecture' not in str(build_today(db, now_utc=NOW.replace(tzinfo=None), access=off))
    assert 'Synthetic lecture' in str(build_current_context(db, 'kalendář', now_utc=NOW.replace(tzinfo=None), access=on))
    assert 'Synthetic lecture' not in str(build_current_context(db, 'kalendář', now_utc=NOW.replace(tzinfo=None), access=off))
    assert not any(item['module_id'] == 'calendar' for item in build(db, off, since=NOW.replace(hour=0), modules=None, limit=100)['items'])
    with patch('modules.calendar.service.append_domain_event', side_effect=RuntimeError('intentional failure')):
        with pytest.raises(RuntimeError):
            service.import_ics(db, source, feed('changed.ics'), now=NOW)
    db.rollback()
    assert db.query(CalendarEvent).filter_by(external_uid='lecture-1@test.invalid').one().title == 'Synthetic lecture'
    assert db.query(models.DomainEvent).count() == 3


def test_api_auth_module_disabled_and_secret_errors(db, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    monkeypatch.setenv('MOODLE_ICS_URL', 'https://feed.example.invalid/?token=secret-canary')
    client = TestClient(main.app)  # no lifespan: isolated test DB, no migrations/scheduler
    try:
        with patch.object(main, 'auth_enabled', return_value=True), patch.object(main, 'validate_session_token', return_value=None):
            assert client.get('/calendar').status_code == 401
            assert client.post('/calendar/sync').status_code == 401
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({'calendar': False})):
            assert client.get('/calendar').status_code == 404
            assert client.post('/calendar/sync').status_code == 404
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({})):
            with patch.object(service, 'fetch_feed', return_value=feed('basic.ics')):
                assert client.post('/calendar/sync').json()['created'] == 3
            response = client.get('/calendar')
            assert response.status_code == 200 and 'secret-canary' not in response.text
            def fail(url):
                raise RuntimeError(url)
            with patch.object(service, 'fetch_feed', side_effect=fail):
                error = client.post('/calendar/sync')
                assert error.status_code == 503 and 'secret-canary' not in error.text
            assert client.get('/calendar?event=-1').status_code == 422
    finally:
        client.close()


def test_calendar_sqlite_migration_roundtrip_and_parity(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect
    backend = Path(__file__).resolve().parents[1]
    url = 'sqlite+pysqlite:///' + str(tmp_path / 'calendar-test.db')
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'alembic'))
    config.set_main_option('version_locations', str(backend / 'alembic/versions'))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
    command.upgrade(config, 'head')
    engine = create_engine(url)
    with engine.connect() as connection:
        assert {'calendar_events', 'calendar_sources'} <= set(inspect(connection).get_table_names())
        assert not compare_metadata(MigrationContext.configure(connection), Base.metadata)
    command.downgrade(config, '0019_calendar')  # 0020: only the presence column goes, every row stays
    with engine.connect() as connection:
        columns = {c['name'] for c in inspect(connection).get_columns('calendar_events')}
        assert 'source_missing_at' not in columns and 'external_uid' in columns
    command.downgrade(config, '-1')  # 0019
    with engine.connect() as connection:
        assert 'calendar_events' not in inspect(connection).get_table_names()
    command.upgrade(config, 'head')
    engine.dispose()


def test_stale_session_cannot_overwrite_newer_source_revision(db, source):
    service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    other = sessionmaker(bind=db.get_bind())()
    stale = other.query(CalendarEvent).filter_by(external_uid='lecture-1@test.invalid').one()
    assert stale.sequence == 1
    service.import_ics(db, source, feed('changed.ics'), now=NOW)
    db.commit()
    older = feed('changed.ics').replace(b'SEQUENCE:2', b'SEQUENCE:1').replace(b'Synthetic changed lecture', b'Synthetic intermediate lecture')
    assert service.import_ics(other, other.get(CalendarSource, source.id), older, now=NOW)['unchanged'] == 1
    other.commit()
    db.expire_all()
    assert db.get(CalendarEvent, stale.id).title == 'Synthetic changed lecture'
    other.close()


def test_identity_only_cancellation_without_revision_is_supported(db, source):
    service.import_ics(db, source, feed('changed.ics'), now=NOW)
    db.commit()
    cancellation = b'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:lecture-1@test.invalid\nSTATUS:CANCELLED\nEND:VEVENT\nEND:VCALENDAR\n'
    assert service.import_ics(db, source, cancellation, now=NOW)['cancelled'] == 1
    db.commit()
    assert db.query(CalendarEvent).one().status == 'cancelled'


def test_search_uses_global_czech_folding_and_location(db, source):
    from search_service import search
    data = feed('basic.ics').replace(b'Synthetic lecture', 'Přednáška pro testy'.encode())
    service.import_ics(db, source, data, now=NOW)
    db.commit()
    assert any(r['title'] == 'Přednáška pro testy' for r in search(db, 'prednaska', access=ModuleAccess({}))['results'])
    assert any(r['title'] == 'Přednáška pro testy' for r in search(db, 'Room', access=ModuleAccess({}))['results'])


def test_revision_watermark_and_cancel_timestamp_do_not_create_noise(db, source):
    service.import_ics(db, source, feed('changed.ics'), now=NOW)
    db.commit()
    before = db.query(CalendarEvent).one().updated_at
    count = db.query(models.DomainEvent).count()
    later = feed('changed.ics').replace(b'SEQUENCE:2', b'SEQUENCE:5')
    assert service.import_ics(db, source, later, now=NOW)['unchanged'] == 1
    db.commit()
    assert db.query(CalendarEvent).one().sequence == 5
    assert db.query(CalendarEvent).one().updated_at == before
    assert db.query(models.DomainEvent).count() == count
    cancellation = feed('cancelled.ics').replace(b'SEQUENCE:3', b'SEQUENCE:6')
    service.import_ics(db, source, cancellation, now=NOW)
    db.commit()
    first_cancel = db.query(CalendarEvent).one().cancelled_at
    changed_cancel = cancellation.replace(b'SEQUENCE:6', b'SEQUENCE:7').replace(b'STATUS:CANCELLED', b'STATUS:CANCELLED\nSUMMARY:Synthetic cancelled correction')
    service.import_ics(db, source, changed_cancel, now=NOW.replace(hour=11))
    db.commit()
    assert db.query(CalendarEvent).one().cancelled_at == first_cancel


def test_historical_query_target_and_source_disabled(db, source):
    service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    event = db.query(CalendarEvent).filter_by(external_uid='lecture-1@test.invalid').one()
    assert service.list_calendar(db, today=date(2027, 10, 9))['events'] == []
    # out-of-window search target: returned as `selected`, never mixed into the active occurrence list
    assert service.list_calendar(db, today=date(2027, 10, 9), event_id=event.id)['selected']['id'] == event.id
    source.enabled = False
    db.commit()
    with pytest.raises(service.CalendarSyncError, match='source_disabled'):
        service.import_ics(db, source, feed('changed.ics'), now=NOW)


def test_all_day_date_identity_does_not_shift_with_source_timezone(db, source):
    source.timezone = 'America/New_York'
    data = b'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:ny-date@test.invalid\nDTSTART;VALUE=DATE:20261009\nDTEND;VALUE=DATE:20261010\nSUMMARY:Synthetic date only\nEND:VEVENT\nEND:VCALENDAR\n'
    service.import_ics(db, source, data, now=NOW)
    db.commit()
    day_after = TodayContext(db, NOW.replace(tzinfo=None), date(2026, 10, 10), datetime(2026, 10, 10))
    assert integrations.timeline(day_after) == []
    actual_day = TodayContext(db, NOW.replace(tzinfo=None), date(2026, 10, 9), datetime(2026, 10, 9))
    assert len(integrations.timeline(actual_day)) == 1


def test_cancellation_with_time_but_no_summary_keeps_the_known_title(db, source):
    service.import_ics(db, source, feed('basic.ics'), now=NOW)
    db.commit()
    row = db.query(CalendarEvent).filter_by(external_uid='lecture-1@test.invalid').one()
    title = row.title
    cancelled = (b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:lecture-1@test.invalid\r\n'
                 b'STATUS:CANCELLED\r\nSEQUENCE:4\r\nDTSTART:20261009T120000Z\r\nDTEND:20261009T133000Z\r\n'
                 b'END:VEVENT\r\nEND:VCALENDAR\r\n')
    assert service.import_ics(db, source, cancelled, now=NOW)['cancelled'] == 1
    db.commit()
    assert row.status == 'cancelled' and row.title == title  # history keeps the real name
    unknown = cancelled.replace(b'lecture-1@test.invalid', b'never-seen@test.invalid')
    assert service.import_ics(db, source, unknown, now=NOW)['cancelled'] == 1
    db.commit()
    assert db.query(CalendarEvent).filter_by(external_uid='never-seen@test.invalid').one().title == 'Zrušená událost'
