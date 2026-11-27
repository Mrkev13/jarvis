"""REST propojení s Wargaming účtem (MRK-105) – `/wot/account`. Auth a brána vypnutého modulu WoT platí automaticky
(router se připojuje přes `ModuleIntegrations.routers`). Odpovědi nikdy neobsahují token ani account_id."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

import database
import wot_account_service as service
import wot_wargaming

router = APIRouter(prefix="/wot/account", tags=["wot"])
service.redact_access_log()


def _fail(exc: service.AccountError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message}) from None


@router.get("")
def wot_account_status():
    db = database.SessionLocal()
    try:
        client = wot_wargaming.client()
        # otevření /wot = příležitost k synchronizaci (sama se omezí na 1× za 50 min)
        out = service.sync(db, client, user_context="system")
        db.commit()
        return {**service.status(db, client), "sync": out["result"]}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/login")
def wot_account_login(body: dict = Body(default_factory=dict)):
    try:
        return service.start_login(str(body.get("origin") or ""), wot_wargaming.client())
    except service.AccountError as exc:
        _fail(exc)


@router.post("/connect")
def wot_account_connect(body: dict = Body(default_factory=dict)):
    db = database.SessionLocal()
    try:
        out = service.connect(db, body, wot_wargaming.client())
        db.commit()
        return out
    except service.AccountError as exc:
        db.rollback()
        _fail(exc)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/sync")
def wot_account_sync():
    db = database.SessionLocal()
    try:
        client = wot_wargaming.client()
        out = service.sync(db, client, force=True, user_context="manual")
        db.commit()
        return {**service.status(db, client), "sync": out["result"]}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.delete("")
def wot_account_disconnect():
    db = database.SessionLocal()
    try:
        out = service.disconnect(db, wot_wargaming.client())
        db.commit()
        return out
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
