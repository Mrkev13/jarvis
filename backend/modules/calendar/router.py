"""Calendar inherits application auth and module gating. No URL is accepted from clients."""
import datetime as dt

from fastapi import APIRouter, HTTPException, Query

import database
from modules.calendar import free_blocks, service

router = APIRouter(prefix='/calendar', tags=['calendar'])


def _run(fn):
    db = database.SessionLocal()
    try:
        result = fn(db)
        db.commit()
        return result
    except service.CalendarSyncError as error:
        db.rollback()
        raise HTTPException(status_code=503, detail={'category': error.category}) from None
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail={'category': 'calendar_operation_failed'}) from None
    finally:
        db.close()


@router.get('')
def calendar_list(event: int | None = Query(default=None, ge=1)):
    return _run(lambda db: service.list_calendar(db, event_id=event))


@router.get('/occurrences')
def calendar_occurrences(start: dt.date, end: dt.date):
    """MRK-40: bounded active occurrences for local days [start, end), max 92 days."""
    db = database.SessionLocal()
    try:
        return service.occurrences_between(db, start, end)
    except service.CalendarWindowError:
        raise HTTPException(status_code=422, detail={'category': 'invalid_window'}) from None
    finally:
        db.close()


_CLOCK = r'^([01][0-9]|2[0-3]):[0-5][0-9]$|^24:00$'


def _clock(value: str):
    """'HH:MM' → time; '24:00' → None (= next local midnight)."""
    return None if value == '24:00' else dt.time(int(value[:2]), int(value[3:]))


@router.get('/free-blocks')
def calendar_free_blocks(start: dt.date, end: dt.date,
                         min_minutes: int = Query(default=30, ge=free_blocks.MIN_MINUTES_RANGE[0], le=free_blocks.MIN_MINUTES_RANGE[1]),
                         buffer_minutes: int = Query(default=0, ge=free_blocks.BUFFER_RANGE[0], le=free_blocks.BUFFER_RANGE[1]),
                         day_start: str = Query(default='07:00', pattern=_CLOCK),
                         day_end: str = Query(default='22:00', pattern=_CLOCK),
                         all_day_busy: bool = False):
    """MRK-32: free blocks for local days [start, end) (max 31) between daily bounds; derived, never stored."""
    if day_start == '24:00':
        raise HTTPException(status_code=422, detail={'category': 'invalid_window'})
    db = database.SessionLocal()
    try:
        return free_blocks.free_blocks_between(db, start, end, min_minutes=min_minutes, buffer_minutes=buffer_minutes,
                                               day_start=_clock(day_start), day_end=_clock(day_end),
                                               all_day_busy=all_day_busy)
    except free_blocks.FreeBlockError:
        raise HTTPException(status_code=422, detail={'category': 'invalid_window'}) from None
    finally:
        db.close()


@router.post('/sync')
def calendar_sync():
    """MRK-77: all configured sources; one failing feed does not stop or undo the others."""
    return _run(service.sync_all)


@router.post('/sync/{key}')
def calendar_sync_source(key: str):
    if key not in service.SOURCES:
        raise HTTPException(status_code=404, detail={'category': 'unknown_source'})
    return _run(lambda db: service.sync_source(db, key))
