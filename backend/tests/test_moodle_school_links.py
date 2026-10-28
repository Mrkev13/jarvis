"""MRK-76: Moodle calendar events → school subjects via CATEGORIES (course short name). Synthetic feeds only."""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import ActivityLog, DomainEvent, Exam, Subject
from module_contracts import ContextRequest
import school_moodle as school_links
from modules.calendar import parser, service
from modules.calendar.models import CalendarEvent, CalendarSource
from modules.school.models import StudyCourse
from school_integrations import context_school, get_upcoming, today_moodle_upcoming
from scripts.check_moodle_ics_categories import report
from today_types import TodayContext

NOW = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)  # Monday 10:00 Prague
TODAY = date(2026, 10, 12)


def vevent(uid, summary, start, categories=None, extra=''):
    cats = ''.join(f'CATEGORIES:{c}\r\n' for c in (categories or ()))
    return (f'BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\nDTSTART:{start}\r\nDTEND:{start}\r\n'
            f'DTSTAMP:20261001T000000Z\r\n{cats}{extra}END:VEVENT\r\n')


def ics(*events):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic//Moodle//CS\r\n' + ''.join(events)
            + 'END:VCALENDAR\r\n').encode()


FEED = ics(
    vevent('quiz@moodle', 'Test 1 se zavírá', '20261014T200000Z', ['PRA101']),       # → Právo
    vevent('due@moodle', 'Esej – odevzdání', '20261016T215900Z', ['pra101 ']),       # case/space-insensitive
    vevent('eng@moodle', 'Quiz closes', '20261015T100000Z', ['ENG2']),               # course not mapped
    vevent('plain@moodle', 'Uživatelská událost', '20261013T090000Z'),                # no CATEGORIES
    vevent('dup@moodle', 'Zápočet', '20261020T080000Z', ['PRA101']),                  # manual exam the same day
    vevent('later@moodle', 'Závěrečný test', '20261110T080000Z', ['PRA101']),         # outside 7 days
)


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    law = Subject(name='Právo', code='PRA', active=True)
    session.add(law)
    session.flush()
    session.add_all([StudyCourse(source='moodle', external_id='1', name='Právo I', short_name='PRA101', subject_id=law.id),
                     StudyCourse(source='moodle', external_id='2', name='English', short_name='ENG2'),
                     Exam(title='Zápočet z práva', subject_id=law.id, exam_date=date(2026, 10, 20), status='upcoming')])
    source = CalendarSource(kind='ics', name='Moodle', config_key='moodle', enabled=True, timezone='Europe/Prague')
    session.add(source)
    session.flush()
    service.import_ics(session, source, FEED, now=NOW)
    session.commit()
    session.law, session.source = law, source
    yield session
    session.close()
    engine.dispose()


def by_uid(db, uid):
    return db.query(CalendarEvent).filter_by(external_uid=uid).one()


def test_parser_reads_a_single_category_only():
    events = {e.external_uid: e for e in parser.parse_ics(ics(
        vevent('one', 'A', '20261014T200000Z', ['PRA101']),
        vevent('none', 'B', '20261014T200000Z'),
        vevent('two', 'C', '20261014T200000Z', ['PRA101', 'ENG2']),
        vevent('list', 'D', '20261014T200000Z', extra='CATEGORIES:X,Y\r\n'),
        vevent('long', 'E', '20261014T200000Z', ['X' * 101]),
    )).events}
    assert len(events) == 5, 'categories never drop an event'
    assert {uid: e.course_ref for uid, e in events.items()} == {'one': 'PRA101', 'none': None, 'two': None,
                                                               'list': None, 'long': None}


def test_import_stores_course_ref_and_backfills_without_activity(db):
    assert by_uid(db, 'quiz@moodle').course_ref == 'PRA101'
    assert by_uid(db, 'plain@moodle').course_ref is None
    # an older row without the column value (before the migration) is filled silently by the next sync
    by_uid(db, 'quiz@moodle').course_ref = None
    db.commit()
    activity, events = db.query(ActivityLog).count(), db.query(DomainEvent).count()
    stats = service.import_ics(db, db.source, FEED, now=NOW)
    db.commit()
    assert by_uid(db, 'quiz@moodle').course_ref == 'PRA101'
    assert stats['updated'] == 0 and (db.query(ActivityLog).count(), db.query(DomainEvent).count()) == (activity, events)


def test_school_deadlines_match_deterministically_without_duplicates(db):
    items = school_links.school_deadlines(db, TODAY, date(2026, 11, 30))
    assert [(i['title'], i['subject_name'], i['date']) for i in items] == [
        ('Test 1 se zavírá', 'Právo', '2026-10-14'),
        ('Esej – odevzdání', 'Právo', '2026-10-16'),   # 23:59 Prague
        ('Závěrečný test', 'Právo', '2026-11-10'),
    ]
    assert items[0]['href'] == f"/calendar?event={by_uid(db, 'quiz@moodle').id}" and items[0]['time'] == '22:00'
    # nothing is lost: unmatched events stay ordinary calendar events
    assert db.query(CalendarEvent).count() == 6


def test_ambiguous_or_unmapped_short_name_matches_nothing(db):
    other = Subject(name='Jiný předmět', active=True)
    db.add(other)
    db.flush()
    db.add(StudyCourse(source='moodle_export', external_id='9', name='Kopie', short_name='Pra101', subject_id=other.id))
    db.commit()
    assert school_links.school_deadlines(db, TODAY, date(2026, 11, 30)) == []


def test_today_shows_each_moodle_deadline_once_as_school_item(db):
    import today_service
    from module_registry import ModuleAccess
    context = TodayContext(db, NOW.replace(tzinfo=None), TODAY, datetime(2026, 10, 12, 10))
    items = {i.title: i for i in today_moodle_upcoming(context)}
    assert set(items) == {'Test 1 se zavírá', 'Esej – odevzdání'}
    assert (items['Test 1 se zavírá'].area, items['Test 1 se zavírá'].subtitle) == ('school', 'Moodle · Právo')
    # whole Dnes: the school version replaces the Calendar duplicate (same ref), unmatched events stay calendar items
    upcoming = today_service.build_today(db, NOW, access=ModuleAccess({}))['upcoming']
    by_title = {}
    for i in upcoming:
        by_title.setdefault(i['title'], []).append(i)
    assert [i['area'] for i in by_title['Test 1 se zavírá']] == ['school']
    assert [i['area'] for i in by_title['Quiz closes']] == ['calendar']
    # Calendar switched off → the Moodle items disappear with it
    off = today_service.build_today(db, NOW, access=ModuleAccess({'calendar': False}))['upcoming']
    assert not any(i['type'] == 'calendar_event' for i in off)


def test_dashboard_and_ai_school_context_list_moodle_deadlines(db):
    upcoming = [u for u in get_upcoming(db, limit=10, today=TODAY) if u['type'] == 'calendar_event']
    assert [(u['title'], u['days_left'], u['subject_name']) for u in upcoming] == [
        ('Test 1 se zavírá', 2, 'Právo'), ('Esej – odevzdání', 4, 'Právo')]
    with patch.object(school_links, 'calendar_enabled', return_value=True):
        lines = ' '.join(context_school(ContextRequest(db, TODAY, NOW)))
    assert 'Moodle termíny do' in lines and 'Test 1 se zavírá, Právo, 2026-10-14' in lines
    with patch.object(school_links, 'calendar_enabled', return_value=False):
        assert 'Moodle' not in ' '.join(context_school(ContextRequest(db, TODAY, NOW)))


def test_endpoint_under_school_and_gated_by_calendar(db, monkeypatch):
    import database
    import main
    from module_registry import ModuleAccess
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    with patch.object(main, 'auth_enabled', return_value=False), patch.object(school_links, 'today_local', return_value=TODAY):
        for access, titles in ((ModuleAccess({}), ['Test 1 se zavírá', 'Esej – odevzdání']),
                               (ModuleAccess({'calendar': False}), [])):
            with patch.object(main, 'current_access', return_value=access), \
                    patch('module_registry.current_access', return_value=access):
                body = TestClient(main.app).get('/school/moodle-deadlines?days=7').json()
                assert [i['title'] for i in body['items']] == titles


def test_check_script_prints_counts_and_shapes_only():
    lines = report(FEED, course_keys={'pra101'})
    text = '\n'.join(lines)
    assert 'S CATEGORIES: 5 (ano)' in text and "tvar 'AAA999'" in text and 'odpovídají namapovanému kurzu: 1 z 2' in text
    for secret in ('PRA101', 'ENG2', 'Test 1', 'Esej', 'moodle'):
        assert secret not in text
