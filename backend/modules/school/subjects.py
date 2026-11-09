"""School subjects: edit and archive (MRK-75). Inherits application auth and the School module gate (`/school`).

Archiving is `Subject.active = False`; nothing is ever deleted. Assignments, exams, course mappings and study
materials keep their subject, so history, Search and Activity still show it (labelled as archived). Archived subjects
are only left out of the places that offer a subject for something new: forms, Quick Add, the AI subject list, course
mapping and its suggestion.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from domain_events import ActivityProjection, append_domain_event
from models import Subject

FIELDS = ("name", "code", "semester", "credits", "active", "absence_limit")
NULLABLE = frozenset({"absence_limit"})  # MRK-86: null = bez limitu absencí
MAX_ABSENCE_LIMIT = 52
LIMITS = {"name": 150, "code": 50, "semester": 50}
MAX_CREDITS = 99

router = APIRouter(prefix="/school/subject", tags=["school"])


class SubjectError(ValueError):
    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


class SubjectUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    semester: str | None = None
    credits: int | None = None
    active: bool | None = None
    absence_limit: int | None = None


def subject_dict(s: Subject) -> dict:
    return {"id": s.id, "name": s.name, "code": s.code, "semester": s.semester, "credits": s.credits,
            "active": s.active is not False, "absence_limit": s.absence_limit}


def _clean(values: dict) -> dict:
    out = {}
    for key, value in values.items():
        if value is None and key in NULLABLE:
            out[key] = None
            continue
        if value is None:
            raise SubjectError("Pole nesmí být prázdné.", 422, "empty_field")
        if key in LIMITS:
            value = value.strip()
            if key == "name" and not value:
                raise SubjectError("Název předmětu je povinný.", 422, "name_required")
            if len(value) > LIMITS[key]:
                raise SubjectError("Text je příliš dlouhý.", 422, "too_long")
        if key == "credits" and not 0 <= value <= MAX_CREDITS:
            raise SubjectError(f"Kredity musí být 0–{MAX_CREDITS}.", 422, "invalid_credits")
        if key == "absence_limit" and not 0 <= value <= MAX_ABSENCE_LIMIT:
            raise SubjectError(f"Limit absencí musí být 0–{MAX_ABSENCE_LIMIT}.", 422, "invalid_absence_limit")
        out[key] = value
    return out


def update_subject(db, subject_id: int, values: dict) -> Subject:
    """Partial update in the caller's transaction (caller commits). Archive/restore = change of `active`."""
    s = db.get(Subject, subject_id)
    if s is None:
        raise SubjectError("Předmět neexistuje.", 404, "not_found")
    changes = _clean({k: v for k, v in values.items() if k in FIELDS})
    before = {k: getattr(s, k) for k in FIELDS}
    before["active"] = before["active"] is not False  # NULL in old rows = active
    delta = {k: {"old": before[k], "new": v} for k, v in changes.items() if before[k] != v}
    if not delta:
        return s
    for key, change in delta.items():
        setattr(s, key, change["new"])
    db.flush()
    if "active" in delta:
        action, activity_type, label = (("restored", "restore", "Předmět obnoven") if s.active
                                        else ("archived", "archive", "Předmět archivován"))
    else:
        action, activity_type, label = "updated", "update", "Předmět upraven"
    append_domain_event(
        db, event_type=f"school.subject.{action}", aggregate_type="subject", aggregate_id=s.id,
        payload={"subject_id": s.id, "active": s.active is not False},
        activity=ActivityProjection("school", activity_type, f"{label}: {s.name}", entity_type="Subject",
                                    entity_id=s.id, delta=delta),
    )
    return s


@router.patch("/{subject_id}")
def patch_subject(subject_id: int, request: SubjectUpdate):
    db = database.SessionLocal()
    try:
        s = update_subject(db, subject_id, request.model_dump(exclude_unset=True))
        db.commit()
        return subject_dict(s)
    except SubjectError as error:
        db.rollback()
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from None
    finally:
        db.close()
