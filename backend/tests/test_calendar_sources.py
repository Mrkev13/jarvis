"""MRK-77: several read-only ICS sources (Moodle + Google) side by side. Synthetic feeds only, no network."""
import json
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import school_moodle
from database import Base
from models import Subject
from module_registry import ModuleAccess
from modules.calendar import service
from modules.calendar.models import CalendarEvent, CalendarSource
from modules.school.models import StudyCourse

NOW = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
MOODLE_URL = 'https://moodle.example.invalid/export?token=moodle-secret-canary'
GOOGLE_URL = 'https://calendar.example.invalid/basic.ics?key=google-secret-canary'


def vevent(uid, summary, start, categories=None):
    cats = f'CATEGORIES:{categories}\r\n' if categories else ''
    return (f'BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\nDTSTART:{start}\r\nDTEND:{start}\r\n'
            f'DTSTAMP:20261001T000000Z\r\n{cats}END:VEVENT\r\n')


def ics(*events):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic//EN\r\n' + ''.join(events) + 'END:VCALENDAR\r\n').encode()


MOODLE = ics(vevent('quiz@moodle', 'Test 1 se zavírá', '20261014T200000Z', 'PRA101'))
GOOGLE_A = ics(vevent('dentist@google', 'Zubař', '20261012T070000Z'),
               vevent('party@google', 'Narozeniny', '20261013T170000Z', 'PRA101'))   # same text as a course
GOOGLE_B = ics(vevent('dentist@google', 'Zubař', '20261012T070000Z'))                 # party removed


@pytest.fixture
def db(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setenv('MOODLE_ICS_URL', MOODLE_URL)
    monkeypatch.setenv('GOOGLE_ICS_URL', GOOGLE_URL)
    yield session
    session.close()
    engine.dispose()


def feeds(google=GOOGLE_A, fail=()):
    def fetch(url):
        key = 'moodle' if url == MOODLE_URL else 'google'
        if key in fail:
            raise RuntimeError(url)  # raw exception carrying the URL must never surface
        return MOODLE if key == 'moodle' else google
    return fetch


def by_source(db):
    keys = {s.id: s.config_key for s in db.query(CalendarSource)}
    out = {}
    for e in db.query(CalendarEvent).order_by(CalendarEvent.external_uid):
        out.setdefault(keys[e.source_id], []).append((e.external_uid, e.source_missing_at is None))
    return out


def test_two_sources_side_by_side_and_reconcile_is_per_source(db):
    result = service.sync_all(db, fetch=feeds(), now=NOW)
    db.commit()
    assert result['created'] == 3 and result['sources']['moodle']['created'] == 1 and result['sources']['google']['created'] == 2
    assert {s.config_key: s.name for s in db.query(CalendarSource)} == {'moodle': 'Moodle', 'google': 'Google Kalendář'}
    # the Google snapshot drops one event: only that Google event goes missing, Moodle is untouched
    result = service.sync_all(db, fetch=feeds(google=GOOGLE_B), now=NOW)
    db.commit()
    assert result['sources']['google']['missing'] == 1 and result['sources']['moodle']['missing'] == 0
    assert by_source(db) == {'google': [('dentist@google', True), ('party@google', False)],
                             'moodle': [('quiz@moodle', True)]}


def test_one_failing_source_neither_blocks_nor_undoes_the_other(db):
    result = service.sync_all(db, fetch=feeds(fail=('google',)), now=NOW)
    db.commit()
    assert result['sources']['google'] == {'error': 'feed_unavailable'}
    assert result['sources']['moodle']['created'] == 1 and result['created'] == 1
    assert by_source(db) == {'moodle': [('quiz@moodle', True)]}
    assert 'canary' not in json.dumps(result)


def test_all_failing_or_none_configured_raise_an_allowlisted_category(db, monkeypatch):
    with pytest.raises(service.CalendarSyncError) as error:
        service.sync_all(db, fetch=feeds(fail=('google', 'moodle')), now=NOW)
    assert error.value.category == 'feed_unavailable' and 'canary' not in str(error.value)
    monkeypatch.delenv('MOODLE_ICS_URL')
    monkeypatch.delenv('GOOGLE_ICS_URL')
    with pytest.raises(service.CalendarSyncError) as error:
        service.sync_all(db, fetch=feeds(), now=NOW)
    assert error.value.category == 'feed_not_configured'


def test_only_google_configured_still_syncs(db, monkeypatch):
    monkeypatch.delenv('MOODLE_ICS_URL')
    assert service.configured_sources() == ['google']
    assert service.sync_all(db, fetch=feeds(), now=NOW)['created'] == 2


def test_google_event_is_never_a_school_deadline(db):
    law = Subject(name='Právo', active=True)
    db.add(law)
    db.flush()
    db.add(StudyCourse(source='moodle', external_id='1', name='Právo I', short_name='PRA101', subject_id=law.id))
    service.sync_all(db, fetch=feeds(), now=NOW)
    db.commit()
    titles = [d['title'] for d in school_moodle.school_deadlines(db, date(2026, 10, 9), date(2026, 10, 20))]
    assert titles == ['Test 1 se zavírá'], 'same CATEGORIES text on a Google event does not make it a deadline'


def test_page_payload_lists_sources_without_urls(db, monkeypatch):
    service.sync_all(db, fetch=feeds(), now=NOW)
    db.commit()
    payload = service.list_calendar(db, today=date(2026, 10, 9))
    assert payload['available_sources'] == [{'key': 'moodle', 'name': 'Moodle', 'configured': True},
                                            {'key': 'google', 'name': 'Google Kalendář', 'configured': True}]
    assert {s['key']: s['configured'] for s in payload['sources']} == {'moodle': True, 'google': True}
    assert payload['configured'] and payload['moodle_configured']
    assert 'canary' not in json.dumps(payload, default=str)
    monkeypatch.delenv('GOOGLE_ICS_URL')
    payload = service.list_calendar(db, today=date(2026, 10, 9))
    assert {s['key']: s['configured'] for s in payload['available_sources']} == {'moodle': True, 'google': False}


def test_api_sync_all_and_single_source_never_leak_urls(db, monkeypatch):
    import database
    import main
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    try:
        with patch.object(main, 'auth_enabled', return_value=False), \
                patch.object(main, 'current_access', return_value=ModuleAccess({})):
            with patch.object(service, 'fetch_feed', side_effect=feeds(fail=('google',))):
                response = client.post('/calendar/sync')
                assert response.status_code == 200 and response.json()['sources']['google'] == {'error': 'feed_unavailable'}
                assert 'canary' not in response.text
                single = client.post('/calendar/sync/google')
                assert single.status_code == 503 and 'canary' not in single.text
            with patch.object(service, 'fetch_feed', side_effect=feeds()):
                assert client.post('/calendar/sync/google').json()['created'] == 2
            assert client.post('/calendar/sync/outlook').status_code == 404
            page = client.get('/calendar')
            assert page.status_code == 200 and 'canary' not in page.text
    finally:
        client.close()
