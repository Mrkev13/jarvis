"""REST tabulky M-ek (MRK-106) – `/wot/mastery`. Auth a brána vypnutého modulu WoT (404) platí automaticky
(router se připojuje přes `ModuleIntegrations.routers`)."""
from __future__ import annotations

from fastapi import APIRouter

import database
import wot_mastery_service as service
import wot_wargaming

router = APIRouter(prefix="/wot/mastery", tags=["wot"])


@router.get("")
def wot_mastery_overview():
    db = database.SessionLocal()
    try:
        return service.overview(db)
    finally:
        db.close()


@router.post("/refresh")
def wot_mastery_refresh():
    db = database.SessionLocal()
    try:
        out = service.sync(db, wot_wargaming.client(), force=True, user_context="manual")
        db.commit()
        return {**out, "message": service.ERROR_TEXT.get(out["result"]), "mastery": service.overview(db)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
