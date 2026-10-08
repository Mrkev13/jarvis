"""Škola – splnění úkolu, uzavření zkoušky a znovuotevření (MRK-14). Deterministické, bez LLM.

- Úkol: „Splnit" → status done + completed_at; „Znovu otevřít" → status todo, completed_at null.
- Zkouška: „Uzavřít" → status passed / failed / closed (bez hodnocení) + completed_at + volitelný výsledek
  (procenta, body, známka, splněno/nesplněno). „Znovu otevřít" → upcoming, výsledek se vymaže.
- Záznam se nikdy nemaže (to je samostatná akce). Každý přechod jde do Aktivity s původními hodnotami (delta),
  takže historie včetně dřívějšího výsledku zůstává dohledatelná i po znovuotevření.
- Termín po splatnosti splnění nebrání. Dvojí splnění / uzavření → 409 (stránka je zastaralá).
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from domain_events import ActivityProjection, append_domain_event, iso
from models import Assignment, Exam
from statuses import is_assignment_done, is_exam_open
from time_utils import utc_now

EXAM_OUTCOMES = ("passed", "failed", "closed")
RESULT_TYPES = ("percent", "points", "grade", "pass_fail")
_POINTS_RE = re.compile(r"^\d{1,4}([.,]\d{1,2})?(\s*/\s*\d{1,4}([.,]\d{1,2})?)?$")
_GRADE_RE = re.compile(r"^([1-5]([+-]|,5)?|[A-Fa-f][+-]?)$")


class SchoolError(ValueError):
    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _get(db: Session, model, item_id: int, label: str):
    item = db.get(model, item_id)
    if item is None:
        raise SchoolError(f"{label} neexistuje.", status=404, code="not_found")
    return item


def normalize_result(result_type, result_value, outcome: str) -> tuple[str | None, str | None]:
    """Volitelný výsledek → (druh, hodnota). Prázdné = bez výsledku. pass_fail se odvodí z výsledku zkoušky."""
    rt = (result_type or "").strip() or None
    raw = str(result_value).strip() if result_value is not None else ""
    if rt is None:
        if raw:
            raise SchoolError("Vyber druh výsledku.", code="invalid_result_type")
        return None, None
    if rt not in RESULT_TYPES:
        raise SchoolError("Neznámý druh výsledku.", code="invalid_result_type")
    if rt == "pass_fail":
        if outcome not in ("passed", "failed"):
            raise SchoolError("Splněno / nesplněno potřebuje výsledek zkoušky.", code="invalid_result_value")
        return rt, outcome
    if not raw:
        raise SchoolError("Vyplň hodnotu výsledku.", code="invalid_result_value")
    if rt == "percent":
        try:
            v = float(raw.replace(",", ".").rstrip("%").strip())
        except ValueError:
            raise SchoolError("Procenta: číslo 0–100.", code="invalid_result_value") from None
        if not 0 <= v <= 100:
            raise SchoolError("Procenta: číslo 0–100.", code="invalid_result_value")
        return rt, (f"{v:g}").replace(".", ",")
    if rt == "points":
        if not _POINTS_RE.fullmatch(raw):
            raise SchoolError("Body: číslo, případně „42/50“.", code="invalid_result_value")
        return rt, re.sub(r"\s*/\s*", "/", raw)
    if not _GRADE_RE.fullmatch(raw):
        raise SchoolError("Známka: 1–5 (třeba 2-) nebo A–F.", code="invalid_result_value")
    return rt, raw.upper()


def serialize_assignment_state(a: Assignment) -> dict:
    return {"id": a.id, "status": a.status, "completed_at": _iso(a.completed_at)}


def serialize_exam_state(e: Exam) -> dict:
    return {"id": e.id, "status": e.status, "completed_at": _iso(e.completed_at), "result_type": e.result_type,
            "result_value": e.result_value}


def complete_assignment(db: Session, item_id: int, *, now: datetime | None = None) -> Assignment:
    a = _get(db, Assignment, item_id, "Úkol")
    if is_assignment_done(a.status):
        raise SchoolError("Úkol už je splněný.", status=409, code="already_completed")
    old = a.status
    a.status = "done"
    a.completed_at = now or utc_now()
    # MRK-19: fakt = doménová událost; řádek Aktivity je její projekce ve stejné transakci (právě jednou)
    append_domain_event(
        db, event_type="school.assignment.completed", aggregate_type="assignment", aggregate_id=a.id,
        payload={"assignment_id": a.id, "subject_id": a.subject_id, "completed_at": iso(a.completed_at)},
        activity=ActivityProjection(
            "school", "complete", f"Úkol splněn: {a.title}", entity_type="Assignment", entity_id=a.id,
            delta={"status": {"old": old, "new": "done"}, "completed_at": {"old": None, "new": a.completed_at.isoformat()}}),
    )
    return a


def reopen_assignment(db: Session, item_id: int) -> Assignment:
    a = _get(db, Assignment, item_id, "Úkol")
    if not is_assignment_done(a.status):
        raise SchoolError("Úkol je otevřený.", status=409, code="not_completed")
    old_status, old_at = a.status, a.completed_at
    a.status = "todo"
    a.completed_at = None
    append_domain_event(
        db, event_type="school.assignment.reopened", aggregate_type="assignment", aggregate_id=a.id,
        payload={"assignment_id": a.id, "subject_id": a.subject_id, "previous_completed_at": iso(old_at)},
        activity=ActivityProjection(
            "school", "update", f"Úkol znovu otevřen: {a.title}", entity_type="Assignment", entity_id=a.id,
            delta={"status": {"old": old_status, "new": "todo"},
                   "completed_at": {"old": old_at.isoformat() if old_at else None, "new": None}}),
    )
    return a


def close_exam(db: Session, item_id: int, data: dict, *, now: datetime | None = None) -> Exam:
    e = _get(db, Exam, item_id, "Zkouška")
    if not is_exam_open(e.status):
        raise SchoolError("Zkouška už je uzavřená.", status=409, code="already_completed")
    outcome = (data.get("outcome") or "passed").strip()
    if outcome not in EXAM_OUTCOMES:
        raise SchoolError("Výsledek zkoušky: složeno, nesloženo nebo bez hodnocení.", code="invalid_outcome")
    rt, rv = normalize_result(data.get("result_type"), data.get("result_value"), outcome)
    old = {"status": e.status, "result_type": e.result_type, "result_value": e.result_value}
    e.status, e.result_type, e.result_value = outcome, rt, rv
    e.completed_at = now or utc_now()
    delta = {k: {"old": v, "new": getattr(e, k)} for k, v in old.items() if v != getattr(e, k)}
    delta["completed_at"] = {"old": None, "new": e.completed_at.isoformat()}
    append_domain_event(
        db, event_type="school.exam.closed", aggregate_type="exam", aggregate_id=e.id,
        payload={"exam_id": e.id, "subject_id": e.subject_id, "outcome": e.status, "result_type": e.result_type,
                 "completed_at": iso(e.completed_at)},
        activity=ActivityProjection(
            "school", "complete", f"Zkouška uzavřena: {e.title}" + (f" ({rv})" if rv and rt != "pass_fail" else ""),
            entity_type="Exam", entity_id=e.id, delta=delta),
    )
    return e


def reopen_exam(db: Session, item_id: int) -> Exam:
    e = _get(db, Exam, item_id, "Zkouška")
    if is_exam_open(e.status):
        raise SchoolError("Zkouška je otevřená.", status=409, code="not_completed")
    old = {"status": e.status, "result_type": e.result_type, "result_value": e.result_value,
           "completed_at": e.completed_at.isoformat() if e.completed_at else None}
    e.status, e.result_type, e.result_value, e.completed_at = "upcoming", None, None, None
    # původní výsledek zůstává v Aktivitě (delta.old) – historie se neztratí
    append_domain_event(
        db, event_type="school.exam.reopened", aggregate_type="exam", aggregate_id=e.id,
        payload={"exam_id": e.id, "subject_id": e.subject_id, "previous_outcome": old["status"]},
        activity=ActivityProjection(
            "school", "update", f"Zkouška znovu otevřena: {e.title}", entity_type="Exam", entity_id=e.id,
            delta={k: {"old": v, "new": None if k != "status" else "upcoming"} for k, v in old.items()}),
    )
    return e
