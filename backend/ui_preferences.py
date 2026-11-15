"""MRK-78: UI preferences stored on the server so they follow the user across devices (PC ↔ phone).

Only allowlisted keys; values are validated, size-bounded JSON with no personal data (widget ids, order, size,
visibility). The frontend still normalises whatever it gets (unknown ids dropped, defaults filled), so the server
check is about shape and size, not about the widget registry. Every save is audited in the same transaction.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from activity_service import log_activity
from models import UiPreference
from time_utils import utc_now

MAX_BYTES = 8 * 1024
MAX_WIDGETS = 64
KEYS = ("dashboard_layout",)
_SIZES = ("small", "medium", "large", "full")

router = APIRouter(prefix="/preferences", tags=["preferences"])


class PreferenceBody(BaseModel):
    value: dict


def _valid_layout(value: dict) -> dict:
    widgets = value.get("widgets")
    if not isinstance(value.get("version"), int) or not isinstance(widgets, list) or len(widgets) > MAX_WIDGETS:
        raise ValueError("shape")
    clean = []
    for w in widgets:
        if not (isinstance(w, dict) and isinstance(w.get("id"), str) and 0 < len(w["id"]) <= 64
                and isinstance(w.get("visible"), bool) and isinstance(w.get("order"), (int, float))
                and not isinstance(w.get("order"), bool) and w.get("size") in _SIZES):
            raise ValueError("widget")
        clean.append({"id": w["id"], "visible": w["visible"], "order": w["order"], "size": w["size"]})
    return {"version": value["version"], "widgets": clean}


def _key(key: str) -> None:
    if key not in KEYS:
        raise HTTPException(status_code=404, detail={"category": "unknown_preference"})


@router.get("/{key}")
def get_preference(key: str):
    _key(key)
    db = database.SessionLocal()
    try:
        row = db.get(UiPreference, key)
        return {"key": key, "value": json.loads(row.value) if row else None,
                "updated_at": row.updated_at.isoformat() + "Z" if row else None}
    finally:
        db.close()


@router.put("/{key}")
def put_preference(key: str, body: PreferenceBody):
    _key(key)
    try:
        value = _valid_layout(body.value)
    except ValueError:
        raise HTTPException(status_code=422, detail={"category": "invalid_preference"}) from None
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(status_code=413, detail={"category": "preference_too_large"})
    db = database.SessionLocal()
    try:
        now = utc_now()
        row = db.get(UiPreference, key)
        if row is not None and row.value == raw:
            return {"key": key, "value": value, "updated_at": row.updated_at.isoformat() + "Z"}
        if row is None:
            row = UiPreference(key=key, value=raw, updated_at=now)
            db.add(row)
        else:
            row.value, row.updated_at = raw, now
        # at most one Activity row per minute: editing the layout is many quick clicks
        log_activity(db, "system", "update", "Rozložení Řídicího centra uloženo", entity_type="UiPreference",
                     user_context="manual", dedupe_key=f"ui-preference:{key}:{now:%Y-%m-%dT%H:%M}")
        db.commit()
        return {"key": key, "value": value, "updated_at": now.isoformat() + "Z"}
    finally:
        db.close()


@router.delete("/{key}")
def delete_preference(key: str):
    """Reset to defaults: the row goes away (future default changes then apply on every device)."""
    _key(key)
    db = database.SessionLocal()
    try:
        row = db.get(UiPreference, key)
        if row is not None:
            db.delete(row)
            log_activity(db, "system", "update", "Rozložení Řídicího centra obnoveno na výchozí",
                         entity_type="UiPreference", user_context="manual",
                         dedupe_key=f"ui-preference:{key}:reset:{utc_now():%Y-%m-%dT%H:%M:%S}")
            db.commit()
        return {"key": key, "value": None, "updated_at": None}
    finally:
        db.close()
