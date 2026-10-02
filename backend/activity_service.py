import hashlib
import json as _json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import ActivityLog


def _default_dedupe_key(area: str, action_type: str, entity_type: str | None, entity_id: int | None, summary: str) -> str:
    digest = hashlib.md5(summary.encode("utf-8")).hexdigest()[:8]
    return f"{area}:{action_type}:{entity_type or ''}:{entity_id or ''}:{digest}"


def delta_dict(old_obj: Any | None, new_obj: Any | None, fields: list[str]) -> dict:
    result: dict = {}
    for f in fields:
        old_val = getattr(old_obj, f, None) if old_obj is not None else None
        new_val = getattr(new_obj, f, None) if new_obj is not None else None
        if hasattr(old_val, "isoformat"):
            try:
                old_val = old_val.isoformat()
            except Exception:
                old_val = str(old_val)
        if hasattr(new_val, "isoformat"):
            try:
                new_val = new_val.isoformat()
            except Exception:
                new_val = str(new_val)
        result[f] = {"old": old_val, "new": new_val}
    return result


def log_activity(
    db: Session,
    area: str,
    action_type: str,
    summary: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    delta: dict | None = None,
    user_context: str | None = None,
    dedupe_key: str | None = None,
) -> ActivityLog | None:
    if not area or not action_type or not summary:
        raise ValueError("area, action_type, summary are required")

    dk = dedupe_key or _default_dedupe_key(area, action_type, entity_type, entity_id, summary)

    try:
        db.flush()
    except Exception:
        pass
    existing = db.execute(select(ActivityLog.id).where(ActivityLog.dedupe_key == dk)).scalar_one_or_none()
    if existing is not None:
        return None

    delta_serialized: str | None = None
    if delta is not None:
        try:
            delta_serialized = _json.dumps(delta, ensure_ascii=False, default=str)
        except Exception:
            delta_serialized = _json.dumps({"_raw": str(delta)}, ensure_ascii=False)

    activity = ActivityLog(
        area=area,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        delta_json=delta_serialized,
        user_context=user_context,
        dedupe_key=dk,
    )

    db.add(activity)
    return activity
