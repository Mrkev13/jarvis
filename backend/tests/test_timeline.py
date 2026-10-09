"""MRK-13: unified day timeline – module contributions, sections, ordering, overlaps, free blocks, DST, gates,
no persistence, API and AI summary. Synthetic data only, no LLM."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import timeline_service as ts
from core_integrations import context_timeline
from database import Base
from models import Assignment, Exam, Reminder, Subject, WorkSession
from module_contracts import ContextRequest
from module_registry import ModuleAccess
from modules.calendar import integrations as calendar_integrations
from modules.calendar import service
from modules.calendar.models import CalendarSource

FIXTURES = Path(__file__).parent / 'fixtures/calendar'
UTC = timezone.utc
DAY = date(2026, 10, 12)  # Monday, CEST (UTC+2)
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)  # 08:00 Prague
ALL = ModuleAccess({})


def ics(*events):
    body = ''.join('BEGIN:VEVENT\n' + e.strip() + '\nEND:VEVENT\n' for e in events)
    return ('BEGIN:VCALENDAR\nVERSION:2.0\n' + body + 'END:VCALENDAR\n').encode()


def event(uid, start, end, title=None):
    return (f'UID:{uid}@test.invalid\nDTSTART;TZID=Europe/Prague:{start}\nDTEND;TZID=Europe/Prague:{end}\n'
            f'SUMMARY:{title or uid}')


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def subject(db):
    item = Subject(name='Math')
    db.add(item)
    db.flush()
    return item.id


@pytest.fixture
def source(db):
    item = CalendarSource(kind='ics', name='Synthetic', config_key='moodle', enabled=True, timezone='Europe/Prague')
    db.add(item)
    db.flush()
    return item


def load(db, source, *events):
    service.import_ics(db, source, ics(*events), now=NOW)
    db.commit()


def day(db, d=DAY, access=ALL, **kw):
    return ts.get_day_timeline(db, access, day=d, now=kw.pop('now', NOW), **kw)


def timed(data):
    return [(i['kind'], i['local_start'], i['local_end'], i['title']) for i in data['timed_items']]


def free(data):
    return [(b['local_start'], b['local_end']) for b in data['free_blocks']]


def test_empty_day_has_no_items_and_whole_window_free(db, source):
    data = day(db)
    assert data['all_day_items'] == [] and data['timed_items'] == []
    assert free(data) == [('07:00', '22:00')] and data['truncated'] is False
    assert data['free_blocks_from'] == ['calendar']
    assert set(data) == {'date', 'all_day_items', 'timed_items', 'free_blocks', 'free_blocks_from', 'truncated'}


def test_calendar_only_day_uses_actual_occurrences(db, source):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000', 'Lecture'))
    data = day(db)
    assert timed(data) == [('calendar_event', '10:00', '11:30', 'Lecture')]
    item = data['timed_items'][0]
    assert item['module_id'] == 'calendar' and item['busy'] is True and item['href'].startswith('/calendar?event=')
    assert item['status'] == 'upcoming'
    assert free(data) == [('07:00', '10:00'), ('11:30', '22:00')]


def test_recurring_occurrence_appears_on_a_later_week(db, source):
    service.import_ics(db, source, (FIXTURES / 'recurring.ics').read_bytes(), now=NOW)
    db.commit()
    data = day(db, date(2026, 11, 10), now=datetime(2026, 11, 10, 6, tzinfo=UTC))
    assert ('calendar_event', '10:00', '11:30', 'Synthetic weekly lecture') in timed(data)
    assert data['timed_items'][0]['id'].startswith('calendar_event:') and '@' in data['timed_items'][0]['id']


def test_school_deadlines_go_to_the_day_section_without_invented_times(db, source, subject):
    load(db, source, 'UID:holiday@test.invalid\nDTSTART;VALUE=DATE:20261012\nDTEND;VALUE=DATE:20261013\nSUMMARY:Holiday',
         event('lecture', '20261012T100000', '20261012T110000', 'Lecture'))
    db.add_all([Assignment(subject_id=subject, title='Essay', due_date=DAY), Exam(subject_id=subject, title='Algebra exam', exam_date=DAY),
                Assignment(subject_id=subject, title='Other day', due_date=DAY + timedelta(days=1))])
    db.commit()
    data = day(db)
    assert [(i['kind'], i['title']) for i in data['all_day_items']] == [
        ('exam', 'Algebra exam'), ('assignment', 'Essay'), ('calendar_event', 'Holiday')]
    assert all(i['starts_at'] is None or i['all_day'] for i in data['all_day_items'])
    assert {i['module_id'] for i in data['all_day_items']} == {'school', 'calendar'}
    assert timed(data) == [('calendar_event', '10:00', '11:00', 'Lecture')]
    assert free(data) == [('07:00', '10:00'), ('11:00', '22:00')], 'all-day/deadlines never block free time'


def test_reminder_overlap_and_same_start_ties_are_listed_not_merged(db, source):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000', 'Lecture'),
         event('meeting', '20261012T110000', '20261012T120000', 'Meeting'))
    db.add_all([Reminder(title='Take pills', due_at=datetime(2026, 10, 12, 8, 0)),       # 10:00 Prague, same start
                Reminder(title='Call', due_at=datetime(2026, 10, 12, 9, 15))])          # 11:15 Prague, inside both
    db.commit()
    data = day(db)
    assert timed(data) == [
        ('reminder', '10:00', None, 'Take pills'),   # point at 10:00 before the lecture that ends later
        ('calendar_event', '10:00', '11:30', 'Lecture'),
        ('calendar_event', '11:00', '12:00', 'Meeting'),
        ('reminder', '11:15', None, 'Call'),
    ]
    assert data['timed_items'][0]['module_id'] is None and data['timed_items'][0]['busy'] is False
    assert free(data) == [('07:00', '10:00'), ('12:00', '22:00')], 'reminders do not occupy time'
    assert data == day(db), 'deterministic'


def test_work_sessions_without_times_are_not_turned_into_slots(db, source):
    db.add(WorkSession(date=DAY, hours=3, project='Servind'))
    db.commit()
    data = day(db)
    assert data['timed_items'] == [] and data['all_day_items'] == []
    assert free(data) == [('07:00', '22:00')]


def test_module_gates(db, source, subject):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000', 'Lecture'))
    db.add_all([Assignment(subject_id=subject, title='Essay', due_date=DAY), Reminder(title='Ping', due_at=datetime(2026, 10, 12, 10))])
    db.commit()
    no_calendar = day(db, access=ModuleAccess({'calendar': False}))
    assert [i['kind'] for i in no_calendar['timed_items']] == ['reminder']
    assert no_calendar['free_blocks'] == [] and no_calendar['free_blocks_from'] == []
    no_school = day(db, access=ModuleAccess({'school': False}))
    assert no_school['all_day_items'] == []
    assert len(no_school['timed_items']) == 2


def test_dst_day_keeps_real_times(db, source):
    autumn = date(2026, 10, 25)
    load(db, source, event('night', '20261025T010000', '20261025T040000', 'Night shift'))
    data = day(db, autumn, now=datetime(2026, 10, 24, 12, tzinfo=UTC))
    item = data['timed_items'][0]
    assert (item['local_start'], item['local_end']) == ('01:00', '04:00')
    start, end = datetime.fromisoformat(item['starts_at']), datetime.fromisoformat(item['ends_at'])
    assert end - start == timedelta(hours=4), 'repeated hour counted once more, not hidden'
    assert free(data) == [('07:00', '22:00')]
    assert data['free_blocks'][0]['duration_minutes'] == 900


def test_one_occurrence_load_shared_with_free_blocks(db, source):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000'))
    calls = []
    real = calendar_integrations.get_calendar_occurrences
    with patch.object(calendar_integrations, 'get_calendar_occurrences',
                      side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
        day(db)
    assert len(calls) == 1


def test_capped_occurrence_load_marks_the_day_truncated_even_without_free_blocks(db, source, monkeypatch):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000'))
    monkeypatch.setattr(calendar_integrations, 'MAX_OCCURRENCES', 1)
    assert day(db, include_free_blocks=False)['truncated'] is True
    assert day(db)['truncated'] is True


def test_reminders_near_midnight_land_on_their_prague_day(db, source):
    db.add_all([Reminder(title='Late', due_at=datetime(2026, 10, 12, 21, 30)),     # 23:30 Prague on the 12th
                Reminder(title='Early next', due_at=datetime(2026, 10, 12, 22, 30)),  # 00:30 Prague on the 13th
                Reminder(title='Just after midnight', due_at=datetime(2026, 10, 11, 22, 0))])  # 00:00 on the 12th
    db.commit()
    assert [i['title'] for i in day(db)['timed_items']] == ['Just after midnight', 'Late']
    assert [i['title'] for i in day(db, DAY + timedelta(days=1))['timed_items']] == ['Early next']


def test_failing_source_is_isolated(db, source, subject):
    db.add(Assignment(subject_id=subject, title='Essay', due_date=DAY))
    db.commit()
    with patch.object(calendar_integrations, 'get_calendar_occurrences', side_effect=RuntimeError('boom')):
        data = day(db)
    assert [i['title'] for i in data['all_day_items']] == ['Essay']
    assert data['timed_items'] == [] and data['free_blocks'] == []


def test_timeline_is_a_projection_not_a_fact(db, source):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000'))
    before = (db.query(models.ActivityLog).count(), db.query(models.DomainEvent).count())
    day(db)
    assert (db.query(models.ActivityLog).count(), db.query(models.DomainEvent).count()) == before
    assert not any(owner and 'timeline' in str(s.name) for owner, s in ALL.contributions('search'))


def test_ai_summary_is_bounded_and_deterministic(db, source, subject):
    load(db, source, event('lecture', '20261012T100000', '20261012T113000', 'Lecture'))
    db.add(Assignment(subject_id=subject, title='Essay', due_date=DAY))
    db.commit()
    req = ContextRequest(db, DAY, datetime(2026, 10, 12, 8, 0), day_timeline=lambda: day(db))
    assert context_timeline(req) == ['Den dnes: další 10:00 Lecture; nejbližší volno 08:00–10:00; '
                                     'celodenní/termíny: Essay']
    # the running 07:00–10:00 block is reported from now (08:00); without an injected timeline there is no section
    assert context_timeline(ContextRequest(db, DAY, datetime(2026, 10, 12, 8, 0))) == []


def test_day_timeline_api(db, source, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    load(db, source, event('lecture', '20261012T100000', '20261012T113000', 'Lecture'))
    monkeypatch.setattr(main, 'SessionLocal', lambda: db)
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    try:
        with patch.object(main, 'auth_enabled', return_value=True), patch.object(main, 'validate_session_token', return_value=None):
            assert client.get('/timeline/day?date=2026-10-12').status_code == 401
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({})):
            ok = client.get('/timeline/day?date=2026-10-12&min_minutes=60')
            assert ok.status_code == 200
            body = ok.json()
            assert [i['title'] for i in body['timed_items']] == ['Lecture']
            assert set(body['timed_items'][0]) >= {'id', 'kind', 'module_id', 'title', 'starts_at', 'ends_at', 'all_day',
                                                   'date', 'status', 'href', 'local_start', 'local_end'}
            assert 'test.invalid' not in ok.text and 'RRULE' not in ok.text
            assert client.get('/timeline/day?date=2026-10-12&free_blocks=false').json()['free_blocks'] == []
            for bad in ['', '?date=nope', '?date=2026-13-01', '?date=2026-10-12&min_minutes=1', '?date=2026-10-12&min_minutes=9999']:
                assert client.get('/timeline/day' + bad).status_code == 422, bad
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({'calendar': False})):
            assert client.get('/timeline/day?date=2026-10-12').json()['timed_items'] == []
    finally:
        client.close()
