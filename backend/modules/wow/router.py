"""REST WoW (MRK-127) – `/wow/*`. Auth a brána vypnutého modulu (404) platí automaticky (router se připojuje
přes `ModuleIntegrations.routers`)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from modules.wow import battlenet, collections, service

router = APIRouter(prefix="/wow", tags=["wow"])


class CharacterCreate(BaseModel):
    name: str
    realm: str
    target_level: int | None = None


class CharacterUpdate(BaseModel):
    target_level: int | None = None


class WishCreate(BaseModel):
    kind: str
    name: str


def _run(fn):
    db = database.SessionLocal()
    try:
        result = fn(db)
        db.commit()
        return result
    except (service.WowError, collections.CollectionError) as err:
        db.rollback()
        raise HTTPException(status_code=err.status, detail=err.message)
    finally:
        db.close()


@router.get("")
def wow_overview():
    return _run(service.overview)


@router.post("/characters")
def wow_add(body: CharacterCreate):
    return _run(lambda db: service.add_character(db, body.name, body.realm, body.target_level))


@router.patch("/characters/{character_id}")
def wow_update(character_id: int, body: CharacterUpdate):
    return _run(lambda db: service.set_target(db, character_id, body.target_level))


@router.delete("/characters/{character_id}")
def wow_delete(character_id: int):
    def go(db):
        service.delete_character(db, character_id)
        return {"ok": True}
    return _run(go)


@router.post("/characters/{character_id}/refresh")
def wow_refresh_one(character_id: int):
    return _run(lambda db: service.sync_one(db, character_id))


@router.post("/refresh")
def wow_refresh_all():
    return _run(lambda db: service.sync_due(db, force=True, user_context="manual"))


# ---------- MRK-128: sbírky ----------


@router.post("/collections/refresh")
def wow_collections_refresh():
    def go(db):
        result = collections.sync_collections(db, battlenet.client(), force=True, user_context="manual")
        if result == "ok":
            service._refresh_goals(db, "manual")
        return {"result": result, "collections": collections.overview(db)}
    return _run(go)


@router.post("/wishes")
def wow_wish_add(body: WishCreate):
    return _run(lambda db: collections.add_wish(db, body.kind, body.name, battlenet.client()))


@router.delete("/wishes/{wish_id}")
def wow_wish_delete(wish_id: int):
    def go(db):
        collections.delete_wish(db, wish_id)
        return {"ok": True}
    return _run(go)
