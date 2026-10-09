"""Calendar inherits application auth and module gating. No URL is accepted from clients."""
import datetime as dt

from fastapi import APIRouter, HTTPException, Query

import database
from modules.calendar import service

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


@router.post('/sync')
def calendar_sync():
    return _run(service.sync_moodle)
