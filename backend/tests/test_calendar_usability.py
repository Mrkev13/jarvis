"""Read-only Calendar usability: next useful gap, recurrence/DST and no historical writes."""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import models
from database import Base
from modules.calendar import integrations, service
from modules.calendar.models import CalendarSource
from modules.calendar.free_blocks import FreeBlockResult
from modules.calendar.occurrences import local_window
from tests.test_calendar_free_blocks import ics, event
from today_types import TodayContext

DAY = date(2026, 10, 12)


@pytest.fixture
def db():
    engine = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def load(db, *events):
    source = CalendarSource(kind='ics', name='Synthetic', config_key='MOODLE_ICS_URL', enabled=True)
    db.add(source); db.flush()
    service.import_ics(db, source, ics(*events)); db.commit()


def context(db, hour=10, day=DAY):
    # October12 is CEST:10UTC =12Prague. Fixed clock; no production network.
    return TodayContext(db, datetime.combine(day, datetime.min.time()).replace(hour=hour),
                        day, datetime.combine(day, datetime.min.time()).replace(hour=hour+2))


def test_today_clips_past_gap_and_uses_one_read_for_both_sections(db):
    c = context(db)
    with patch.object(integrations, 'get_free_blocks', wraps=integrations.get_free_blocks) as fetch:
        rows = integrations.next_free_block_today(c)
        assert rows[0].title == 'Volno 12:00–22:00 (10 h)'
        assert rows[0].date == DAY.isoformat() and rows[0].actions == []
        assert integrations.next_free_block_upcoming(c) == []
        assert fetch.call_count == 1
    assert db.query(models.ActivityLog).count() == db.query(models.DomainEvent).count() == 0


def test_fully_busy_today_falls_back_to_tomorrow_upcoming(db):
    load(db, event('full', '20261012T070000', '20261012T220000'))
    c = context(db)
    assert integrations.next_free_block_today(c) == []
    item = integrations.next_free_block_upcoming(c)[0]
    assert item.date == '2026-10-13' and '07:00–22:00' in item.title


def test_no_gap_today_or_tomorrow_returns_no_suggestion(db):
    load(db, event('full', '20261012T070000', '20261013T220000'))
    c = context(db)
    assert integrations.next_free_block_today(c) == integrations.next_free_block_upcoming(c) == []


def test_short_remaining_gap_is_skipped(db):
    c = context(db, 19)  #21:00 local
    load(db, event('end', '20261012T212000', '20261012T220000'))
    assert integrations.next_free_block_today(c) == []
    assert integrations.next_free_block_upcoming(c)[0].date == '2026-10-13'


def test_truncated_data_reports_uncertainty_not_a_free_time(db):
    c = context(db)
    with patch.object(integrations, 'get_free_blocks', return_value=FreeBlockResult((), True)):
        item = integrations.next_free_block_today(c)[0]
        assert 'spolehlivě' in item.title and 'Neúplná' in item.subtitle
        assert item.time is None and item.severity == 'warning'
        assert integrations.next_free_block_upcoming(c) == []


def test_week_range_dst_override_and_source_state(db):
    load(db,
         event('weekly', '20261019T090000', '20261019T100000', 'RRULE:FREQ=DAILY;COUNT=7'),
         event('weekly', '20261025T110000', '20261025T120000',
               'RECURRENCE-ID;TZID=Europe/Prague:20261025T090000'),
         event('cancelled', '20261025T120000', '20261025T130000', 'STATUS:CANCELLED'))
    payload = service.occurrences_between(db, date(2026,10,19), date(2026,10,26))
    assert len(payload['occurrences']) == 7
    moved = next(o for o in payload['occurrences'] if o['starts_at'].startswith('2026-10-25'))
    assert '10:00:00' in moved['starts_at']  #11CET, after DST
    lo, hi = local_window(date(2026,10,19), date(2026,10,26))
    assert (hi-lo).total_seconds() == (7*24+1)*3600
    for row in db.query(models.CalendarEvent).filter_by(external_uid='weekly@test.invalid').all():
        row.source_missing_at = datetime(2026,10,26,tzinfo=timezone.utc)
    db.commit()
    assert service.occurrences_between(db,date(2026,10,19),date(2026,10,26))['occurrences'] == []


def test_occurrence_api_exposes_incomplete_range(db):
    from modules.calendar.occurrences import MAX_OCCURRENCES
    with patch.object(service, 'get_calendar_occurrences', return_value=[{}]*MAX_OCCURRENCES), \
         patch.object(service, 'occurrence_dict', side_effect=lambda value:value):
        assert service.occurrences_between(db,DAY,date(2026,10,19))['truncated'] is True
    assert service.occurrences_between(db,DAY,date(2026,10,19))['truncated'] is False


def test_today_framework_gate_and_tomorrow_date_are_preserved(db):
    from module_registry import ModuleAccess
    from today_service import build_today
    load(db,event('full','20261012T070000','20261012T220000'))
    on = build_today(db,now_utc=datetime(2026,10,12,10),access=ModuleAccess({}))
    assert not any(row['type']=='calendar_free_block' for row in on['timeline'])
    assert any(row['type']=='calendar_free_block' and row['date']=='2026-10-13' for row in on['upcoming'])
    off = build_today(db,now_utc=datetime(2026,10,12,10),access=ModuleAccess({'calendar':False}))
    assert not any(row['type']=='calendar_free_block' for row in off['upcoming'])
