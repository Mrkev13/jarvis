"""REST Návyků (MRK-21) – `/habits/*`. Auth a brána vypnutého modulu (404) platí automaticky: router se připojuje
k aplikaci přes `ModuleIntegrations.router` a dědí globální dependencies `main.app`."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from modules.habits import service

router = APIRouter(prefix="/habits", tags=["habits"])


class HabitCreate(BaseModel):
    name: str
    kind: str = "check"
    target_value: float | None = None
    unit: str | None = None


class EntryWrite(BaseModel):
    state: str
    date: dt.date | None = None
    value: float | None = None
    duration_minutes: int | None = None
    note: str | None = None


def _ctx(source: str | None) -> str:
    # jen „today" má vlastní kontext (akce z Dnes), jinak ruční zápis ze stránky
    return "today" if source == "today" else "manual"


def _run(fn):
    db = database.SessionLocal()
    try:
        result = fn(db)
        db.commit()
        return result
    except service.HabitError as err:
        db.rollback()
        raise HTTPException(status_code=err.status, detail=err.message)
    finally:
        db.close()


@router.get("")
def habits_list():
    return _run(lambda db: service.list_habits(db))


@router.post("")
def habits_create(body: HabitCreate, source: str | None = None):
    def go(db):
        h = service.create_habit(db, body.name, body.kind, body.target_value, body.unit, user_context=_ctx(source))
        return {"ok": True, "id": h.id}
    return _run(go)


@router.post("/{habit_id}/archive")
def habits_archive(habit_id: int):
    return _run(lambda db: {"ok": True, "active": service.set_active(db, habit_id, False, user_context="manual").active})


@router.post("/{habit_id}/restore")
def habits_restore(habit_id: int):
    return _run(lambda db: {"ok": True, "active": service.set_active(db, habit_id, True, user_context="manual").active})


@router.post("/{habit_id}/entries")
def habits_entry(habit_id: int, body: EntryWrite, source: str | None = None):
    def go(db):
        e = service.set_entry(db, habit_id, body.state, day=body.date, value=body.value,
                              duration_minutes=body.duration_minutes, note=body.note, user_context=_ctx(source))
        return {"ok": True, "entry": service.entry_dict(e)}
    return _run(go)
