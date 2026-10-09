"""MRK-32: free blocks from active Calendar occurrences – merging, clipping, DST, bounds, API. Synthetic data only."""
import json
from datetime import date, datetime, time, timedelta, timezone
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
from modules.calendar import free_blocks, integrations, service
from modules.calendar.free_blocks import FreeBlockError, get_free_blocks, merge_intervals
from modules.calendar.models import CalendarSource
from modules.calendar.occurrences import local_window

FIXTURES = Path(__file__).parent / 'fixtures/calendar'
NOW = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
PRAGUE = ZoneInfo('Europe/Prague')
UTC = timezone.utc
DAY = date(2026, 10, 12)  # Monday, CEST


def ics(*events):
    body = ''.join('BEGIN:VEVENT\n' + e.strip() + '\nEND:VEVENT\n' for e in events)
    return ('BEGIN:VCALENDAR\nVERSION:2.0\n' + body + 'END:VCALENDAR\n').encode()


def event(uid, start, end, extra=''):
    """Prague-local timed event: 'YYYYMMDDTHHMMSS'."""
    return (f'UID:{uid}@test.invalid\nDTSTART;TZID=Europe/Prague:{start}\nDTEND;TZID=Europe/Prague:{end}\n'
            f'SUMMARY:Busy {uid}\n{extra}')


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


def load(db, source, *events):
    service.import_ics(db, source, ics(*events), now=NOW)
    db.commit()


def blocks(db, day=DAY, days=1, **options):
    lo, hi = local_window(day, day + timedelta(days=days))
    return [(b['local_date'], b['local_start'], b['local_end'], b['duration_minutes'])
            for b in (x.as_dict() for x in get_free_blocks(db, start=lo, end=hi, **options).blocks)]


def test_no_events_whole_day_window_is_free(db, source):
    assert blocks(db) == [('2026-10-12', '07:00', '22:00', 900)]
    assert blocks(db, day_start=time(0), day_end=None) == [('2026-10-12', '00:00', '24:00', 1440)]


def test_middle_start_end_events_and_clipping(db, source):
    load(db, source,
         event('early', '20261012T060000', '20261012T080000'),     # starts before the window → clipped
         event('mid', '20261012T120000', '20261012T130000'),
         event('late', '20261012T210000', '20261012T233000'))      # ends after the window → clipped
    assert blocks(db) == [('2026-10-12', '08:00', '12:00', 240), ('2026-10-12', '13:00', '21:00', 480)]


def test_overlapping_nested_and_touching_events_merge_without_double_counting(db, source):
    load(db, source,
         event('a', '20261012T090000', '20261012T110000'),
         event('b', '20261012T100000', '20261012T120000'),          # overlaps a
         event('c', '20261012T093000', '20261012T094500'),          # nested in a
         event('d', '20261012T120000', '20261012T130000'),          # touches b
         event('e', '20261012T150000', '20261012T150000'))          # zero-length: blocks nothing
    assert blocks(db) == [('2026-10-12', '07:00', '09:00', 120), ('2026-10-12', '13:00', '22:00', 540)]
    assert merge_intervals([(3, 4), (1, 2), (2, 3), (1, 1)]) == [(1, 4)]


def test_event_exactly_on_window_boundary(db, source):
    load(db, source, event('edge', '20261012T060000', '20261012T070000'),
         event('edge2', '20261012T220000', '20261012T230000'))
    assert blocks(db) == [('2026-10-12', '07:00', '22:00', 900)]


def test_min_duration_filter_and_buffer(db, source):
    load(db, source, event('a', '20261012T090000', '20261012T100000'), event('b', '20261012T102000', '20261012T120000'))
    assert ('2026-10-12', '10:00', '10:20', 20) in blocks(db, min_minutes=15)
    assert all(b[3] >= 30 for b in blocks(db))  # 20-minute gap dropped by the default 30
    assert blocks(db, min_minutes=15, buffer_minutes=10) == [('2026-10-12', '07:00', '08:50', 110),
                                                             ('2026-10-12', '12:10', '22:00', 590)]


def test_all_day_event_blocks_only_when_marked_busy(db, source):
    load(db, source, 'UID:holiday@test.invalid\nDTSTART;VALUE=DATE:20261012\nDTEND;VALUE=DATE:20261013\nSUMMARY:All day')
    assert blocks(db) == [('2026-10-12', '07:00', '22:00', 900)], 'all-day does not block by default (MRK-32)'
    assert blocks(db, all_day_busy=True) == []
    assert blocks(db, day=date(2026, 10, 13), all_day_busy=True) == [('2026-10-13', '07:00', '22:00', 900)]


def test_recurring_exdate_moved_and_cancelled_overrides(db, source):
    service.import_ics(db, source, (FIXTURES / 'recurring.ics').read_bytes(), now=NOW)
    db.commit()
    # 13.10. Tue: weekly lecture 10:00–11:30 → busy
    assert blocks(db, day=date(2026, 10, 13)) == [('2026-10-13', '07:00', '10:00', 180), ('2026-10-13', '11:30', '22:00', 630)]
    # 20.10.: instance moved to 21.10. 14:00–15:30 → 20.10. free, 21.10. busy in the afternoon
    assert blocks(db, day=date(2026, 10, 20)) == [('2026-10-20', '07:00', '22:00', 900)]
    assert ('2026-10-21', '15:30', '22:00', 390) in blocks(db, day=date(2026, 10, 21))
    # 27.10. cancelled occurrence and 3.11. EXDATE → free (lecture time is not busy)
    assert blocks(db, day=date(2026, 10, 27)) == [('2026-10-27', '07:00', '22:00', 900)]
    assert blocks(db, day=date(2026, 11, 3)) == [('2026-11-03', '07:00', '22:00', 900)]


def test_cancelled_and_source_missing_events_do_not_block(db, source):
    load(db, source, event('gone', '20261012T090000', '20261012T100000'), event('stays', '20261012T120000', '20261012T130000'))
    load(db, source, event('stays', '20261012T120000', '20261012T130000'))  # complete snapshot without "gone"
    assert ('2026-10-12', '07:00', '12:00', 300) in blocks(db)
    load(db, source, event('stays', '20261012T120000', '20261012T130000', 'STATUS:CANCELLED\nSEQUENCE:1'))
    assert blocks(db) == [('2026-10-12', '07:00', '22:00', 900)]


def test_multi_day_range_is_ordered_and_deterministic(db, source):
    load(db, source, event('a', '20261013T090000', '20261013T100000'))
    result = blocks(db, days=3)
    assert [b[0] for b in result] == ['2026-10-12', '2026-10-13', '2026-10-13', '2026-10-14']
    assert result == blocks(db, days=3)


@pytest.mark.parametrize('day,expected_day_minutes', [(date(2026, 3, 29), 1380), (date(2026, 10, 25), 1500)])
def test_dst_days_have_exact_real_durations(db, source, day, expected_day_minutes):
    whole = get_free_blocks(db, start=local_window(day, day + timedelta(days=1))[0],
                            end=local_window(day, day + timedelta(days=1))[1], day_start=time(0), day_end=None).blocks
    assert len(whole) == 1 and whole[0].duration_minutes == expected_day_minutes, '23 h spring / 25 h autumn day'
    load(db, source, event('night', day.strftime('%Y%m%d') + 'T010000', day.strftime('%Y%m%d') + 'T040000'))
    got = blocks(db, day=day, day_start=time(0), day_end=None)
    # 01:00–04:00 local spans the switch: really 2 h (spring) / 4 h (autumn); the rest of the day stays exact
    busy_minutes = expected_day_minutes - sum(b[3] for b in got)
    assert busy_minutes == (120 if day.month == 3 else 240)
    assert got[0][1:3] == ('00:00', '01:00') and got[1][1:3] == ('04:00', '24:00')
    assert got[1][3] == 20 * 60, 'no fake gap or duplicate hour after the switch'
    default = blocks(db, day=day)
    assert default == [(day.isoformat(), '07:00', '22:00', 900)], '07–22 window is 15 real hours on a DST day'


def test_invalid_and_excessive_windows(db, source):
    lo, hi = local_window(DAY, DAY + timedelta(days=1))
    for kwargs in [dict(start=hi, end=lo), dict(start=lo, end=lo), dict(start=lo, end=lo + timedelta(days=32)),
                   dict(start=lo.replace(tzinfo=None), end=hi.replace(tzinfo=None)),
                   dict(start=lo, end=hi, min_minutes=1), dict(start=lo, end=hi, min_minutes=10_000),
                   dict(start=lo, end=hi, buffer_minutes=-1), dict(start=lo, end=hi, day_start=time(22), day_end=time(7))]:
        with pytest.raises(FreeBlockError):
            get_free_blocks(db, **kwargs)


def test_max_range_of_local_days_is_accepted_across_dst(db, source):
    # 12.10.–12.11. = 31 local days but 31 d + 1 h of real time (autumn switch on 25.10.)
    result = free_blocks.free_blocks_between(db, date(2026, 10, 12), date(2026, 11, 12))
    assert len(result['blocks']) == 31 and {b['duration_minutes'] for b in result['blocks']} == {900}
    with pytest.raises(FreeBlockError):
        free_blocks.free_blocks_between(db, date(2026, 10, 12), date(2026, 11, 13))


def test_multi_day_all_day_event_blocks_its_dates_only_when_busy(db, source):
    # 24.–26.10. (exclusive end 27.10.) spans the autumn DST switch on 25.10.
    load(db, source, 'UID:trip@test.invalid\nDTSTART;VALUE=DATE:20261024\nDTEND;VALUE=DATE:20261027\nSUMMARY:Trip')
    window = blocks(db, day=date(2026, 10, 23), days=5)
    assert [b[0] for b in window] == ['2026-10-23', '2026-10-24', '2026-10-25', '2026-10-26', '2026-10-27']
    busy = blocks(db, day=date(2026, 10, 23), days=5, all_day_busy=True)
    assert busy == [('2026-10-23', '07:00', '22:00', 900), ('2026-10-27', '07:00', '22:00', 900)]


def test_block_cap_marks_result_truncated(db, source, monkeypatch):
    monkeypatch.setattr(free_blocks, 'MAX_BLOCKS', 2)
    lo, hi = local_window(DAY, DAY + timedelta(days=5))
    result = get_free_blocks(db, start=lo, end=hi)
    assert len(result.blocks) == 2 and result.truncated is True


def test_ai_context_marks_truncated_free_time_as_uncertain(db, source, monkeypatch):
    monkeypatch.setattr(free_blocks, 'MAX_OCCURRENCES', 0)
    lines = integrations.context_events(ContextRequest(db, DAY, datetime(2026, 10, 12, 8, 0)))
    assert all('neúplné' in line for line in lines if 'volno' in line)


def test_occurrence_cap_marks_result_truncated(db, source, monkeypatch):
    load(db, source, event('a', '20261012T090000', '20261012T100000'))
    monkeypatch.setattr(free_blocks, 'MAX_OCCURRENCES', 1)
    lo, hi = local_window(DAY, DAY + timedelta(days=1))
    assert get_free_blocks(db, start=lo, end=hi).truncated is True


def test_one_occurrence_query_per_free_block_query(db, source):
    load(db, source, event('a', '20261012T090000', '20261012T100000'))
    calls = []
    real = free_blocks.get_calendar_occurrences
    with patch.object(free_blocks, 'get_calendar_occurrences', side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
        blocks(db, days=7)
    assert len(calls) == 1


def test_free_blocks_are_projections_not_facts(db, source):
    load(db, source, event('a', '20261012T090000', '20261012T100000'))
    before = (db.query(models.ActivityLog).count(), db.query(models.DomainEvent).count())
    blocks(db, days=7)
    assert (db.query(models.ActivityLog).count(), db.query(models.DomainEvent).count()) == before
    assert not any('free' in str(s.name) for _o, s in ModuleAccess({}).contributions('search'))


def test_ai_context_lists_bounded_free_time(db, source):
    load(db, source, event('a', '20261012T090000', '20261012T100000'))
    lines = integrations.context_events(ContextRequest(db, DAY, datetime(2026, 10, 12, 8, 0)))
    free = [line for line in lines if 'volno' in line]
    assert free == ['Kalendář – volno dnes (07–22, min. 30 min): 08:00–09:00 (1 h), 10:00–22:00 (12 h)',
                    'Kalendář – volno zítra (07–22, min. 30 min): 07:00–22:00 (15 h)']
    late = integrations.context_events(ContextRequest(db, DAY, datetime(2026, 10, 12, 21, 50)))
    assert 'Kalendář – volno dnes (07–22, min. 30 min): žádné' in late


def test_free_blocks_api(db, source, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    load(db, source, event('a', '20261012T090000', '20261012T100000', 'RRULE:FREQ=DAILY;COUNT=3'))
    monkeypatch.setattr(database, 'SessionLocal', lambda: db)
    monkeypatch.setattr(db, 'close', lambda: None)
    client = TestClient(main.app)
    url = '/calendar/free-blocks?start=2026-10-12&end=2026-10-13'
    try:
        with patch.object(main, 'auth_enabled', return_value=True), patch.object(main, 'validate_session_token', return_value=None):
            assert client.get(url).status_code == 401
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({'calendar': False})):
            assert client.get(url).status_code == 404
        with patch.object(main, 'auth_enabled', return_value=False), patch.object(main, 'current_access', return_value=ModuleAccess({})):
            ok = client.get(url + '&min_minutes=60')
            assert ok.status_code == 200
            body = ok.json()
            assert set(body) == {'start', 'end', 'min_minutes', 'truncated', 'blocks'}
            assert [(b['local_start'], b['local_end']) for b in body['blocks']] == [('07:00', '09:00'), ('10:00', '22:00')]
            assert set(body['blocks'][0]) == {'starts_at', 'ends_at', 'local_date', 'local_start', 'local_end', 'duration_minutes'}
            assert 'RRULE' not in ok.text and 'recurrence' not in ok.text and 'test.invalid' not in ok.text
            assert client.get(url + '&day_start=00:00&day_end=24:00').json()['blocks'][0]['local_start'] == '00:00'
            for bad in ['?start=2026-10-12&end=2026-10-12', '?start=2026-10-01&end=2026-12-01', '?start=nope&end=2026-10-13',
                        '?start=2026-10-12&end=2026-10-13&min_minutes=1', '?start=2026-10-12&end=2026-10-13&min_minutes=721',
                        '?start=2026-10-12&end=2026-10-13&buffer_minutes=500', '?start=2026-10-12&end=2026-10-13&day_start=25:00',
                        '?start=2026-10-12&end=2026-10-13&day_start=22:00&day_end=07:00',
                        '?start=2026-10-12&end=2026-10-13&day_start=24:00']:
                assert client.get('/calendar/free-blocks' + bad).status_code == 422, bad
            assert json.loads(client.get(url).text)['truncated'] is False
            assert client.get('/calendar/free-blocks?start=2026-10-12&end=2026-11-12').status_code == 200  # 31 days over DST
    finally:
        client.close()
