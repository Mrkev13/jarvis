"""Stav zápočtu, výsledky zkoušek a týdenní docházka u předmětu (MRK-86).

Všechno se počítá deterministicky tady (žádné LLM): souhrn pro stránku Škola, varování o absencích pro Dnes
(Pozornost / Co hoří) a řádky pro AI kontext Školy – AI dostane jen výsledek, nikdy nic nepočítá.

- Zápočet: `Subject.credit_status` pending | passed | failed (NULL = nesplněn) + `credit_date`. Změna stavu je
  doménový fakt `school.subject.credit_changed` (Aktivita = jeho projekce, stejná transakce).
- Docházka: jeden řádek byl/nebyl na předmět a týden (`week_start` = pondělí v Europe/Prague). Nezapsaný týden
  se nepočítá. Zápis jde jen do aktivního předmětu a ne do budoucího týdne; každý zápis = `log_activity`.
- Absence: volitelný `Subject.absence_limit` (počet povolených absencí, PATCH /school/subject/{id}). Varování,
  když zbývá poslední povolená absence, limit je vyčerpaný nebo překročený; u splněného zápočtu se nevaruje.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4
import datetime as dt
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from activity_service import log_activity
from domain_events import ActivityProjection, append_domain_event
from models import Exam, Subject
from modules.school.models import SchoolAttendance
from school_service import EXAM_OUTCOMES
from statuses import is_exam_open
from time_utils import today_local, utc_now
from today_types import TodayItem

CREDIT_LABELS = {"pending": "nesplněn", "passed": "splněn", "failed": "neuznán"}
OUTCOME_LABELS = {"passed": "složeno", "failed": "nesloženo", "closed": "bez hodnocení"}
HISTORY_WEEKS = 16  # kolik posledních zapsaných týdnů vrací přehled (počty jsou vždy ze všech)
RESULTS_PREVIEW = 5
WARNING_LEVELS = ("last", "exhausted", "exceeded")

router = APIRouter(prefix="/school", tags=["school"])


class ProgressError(ValueError):
    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


def week_start(d: date) -> date:
    """Pondělí týdne, do kterého patří pražské datum `d`."""
    return d - timedelta(days=d.weekday())


def credit_status(s: Subject) -> str:
    return s.credit_status if s.credit_status in CREDIT_LABELS else "pending"


def week_label(start: date) -> str:
    return f"týden od {start.day}. {start.month}."


# ---------- výpočet (čistý, testovatelný) ----------


@dataclass(frozen=True)
class Absences:
    present: int
    absent: int
    limit: int | None

    @property
    def recorded(self) -> int:
        return self.present + self.absent

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else self.limit - self.absent

    @property
    def level(self) -> str | None:
        """None (bez limitu) | ok | last (zbývá poslední) | exhausted (žádná nezbývá) | exceeded (překročeno)."""
        remaining = self.remaining
        if remaining is None:
            return None
        if remaining < 0:
            return "exceeded"
        if remaining == 0:
            return "exhausted"
        return "last" if remaining == 1 else "ok"

    def text(self) -> str:
        """„byl 5 z 6, absence 1 z max. 2 (zbývá 1)" – stejný text pro stránku i AI."""
        if not self.recorded:
            base = "docházka zatím nezapsaná"
        else:
            base = f"byl {self.present} z {self.recorded}"
        if self.limit is None:
            return base if not self.absent else f"{base}, absence {self.absent}"
        tail = {"exceeded": f"limit překročen o {-self.remaining}", "exhausted": "už žádná nezbývá",
                "last": "zbývá poslední"}.get(self.level, f"zbývá {self.remaining}")
        return f"{base}, absence {self.absent} z max. {self.limit} ({tail})"


def warning_text(name: str, a: Absences) -> str | None:
    if a.level == "exceeded":
        return f"{name}: limit absencí překročen ({a.absent} z max. {a.limit})"
    if a.level == "exhausted":
        return f"{name}: vyčerpané absence ({a.absent} z max. {a.limit}) – další už nejde"
    if a.level == "last":
        return f"{name}: zbývá poslední povolená absence ({a.absent} z max. {a.limit})"
    return None


def _attendance_by_subject(db, subject_ids: list[int]) -> dict[int, list[SchoolAttendance]]:
    out: dict[int, list[SchoolAttendance]] = {sid: [] for sid in subject_ids}
    if not subject_ids:
        return out
    rows = (db.query(SchoolAttendance).filter(SchoolAttendance.subject_id.in_(subject_ids))
            .order_by(SchoolAttendance.week_start.desc()).all())
    for r in rows:
        out[r.subject_id].append(r)
    return out


def absences_for(subject: Subject, rows: list[SchoolAttendance]) -> Absences:
    present = sum(1 for r in rows if r.present)
    return Absences(present=present, absent=len(rows) - present, limit=subject.absence_limit)


def _exam_summary(exams: list[Exam]) -> dict:
    closed = [e for e in exams if not is_exam_open(e.status)]
    closed.sort(key=lambda e: (e.exam_date or date.min, e.id), reverse=True)
    results = []
    for e in closed[:RESULTS_PREVIEW]:
        outcome = e.status if e.status in EXAM_OUTCOMES else "closed"
        value = e.result_value if e.result_value and e.result_type != "pass_fail" else None
        results.append({"id": e.id, "title": e.title, "date": e.exam_date.isoformat() if e.exam_date else None,
                        "outcome": outcome, "outcome_label": OUTCOME_LABELS[outcome], "result": value})
    return {
        "open": len(exams) - len(closed),
        "closed": len(closed),
        "passed": sum(1 for e in closed if e.status == "passed"),
        "failed": sum(1 for e in closed if e.status == "failed"),
        "results": results,
    }


def subject_progress(db, today: date | None = None, *, include_archived: bool = False) -> dict:
    """GET /school/progress: aktivní předměty (archivované jen na požádání) se zápočtem, zkouškami a docházkou."""
    today = today or today_local()
    current = week_start(today)
    q = db.query(Subject)
    if not include_archived:
        q = q.filter(Subject.active.isnot(False))
    subjects = q.order_by(Subject.name, Subject.id).all()
    ids = [s.id for s in subjects]
    attendance = _attendance_by_subject(db, ids)
    exams: dict[int, list[Exam]] = {sid: [] for sid in ids}
    if ids:
        for e in db.query(Exam).filter(Exam.subject_id.in_(ids)).all():
            exams[e.subject_id].append(e)
    items = []
    for s in subjects:
        rows = attendance[s.id]
        a = absences_for(s, rows)
        this_week = next((r.present for r in rows if r.week_start == current), None)
        status = credit_status(s)
        items.append({
            "id": s.id, "name": s.name, "code": s.code or "", "semester": s.semester or "", "active": s.active is not False,
            "credit": {"status": status, "label": CREDIT_LABELS[status],
                       "date": s.credit_date.isoformat() if s.credit_date else None},
            "exams": _exam_summary(exams[s.id]),
            "attendance": {
                "present": a.present, "absent": a.absent, "recorded": a.recorded, "limit": a.limit,
                "remaining": a.remaining, "level": a.level,
                # varovat jen u nesplněného zápočtu (po splnění na docházce už nezáleží)
                "warning": warning_text(s.name, a) if status != "passed" else None,
                "text": a.text(), "this_week": this_week,
                "weeks": [{"week_start": r.week_start.isoformat(), "present": r.present} for r in rows[:HISTORY_WEEKS]],
            },
        })
    return {"week_start": current.isoformat(), "previous_week_start": (current - timedelta(days=7)).isoformat(),
            "subjects": items}


def warnings(db, today: date | None = None) -> list[tuple[Subject, Absences]]:
    """Aktivní předměty se splněným zápočtem se přeskočí; zbytek s úrovní last / exhausted / exceeded."""
    subjects = (db.query(Subject).filter(Subject.active.isnot(False), Subject.absence_limit.isnot(None))
                .order_by(Subject.name, Subject.id).all())
    subjects = [s for s in subjects if credit_status(s) != "passed"]
    attendance = _attendance_by_subject(db, [s.id for s in subjects])
    out = []
    for s in subjects:
        a = absences_for(s, attendance[s.id])
        if a.level in WARNING_LEVELS:
            out.append((s, a))
    return out


# ---------- zápisy ----------


def _subject(db, subject_id: int) -> Subject:
    s = db.get(Subject, subject_id)
    if s is None:
        raise ProgressError("Předmět neexistuje.", 404, "not_found")
    return s


def set_credit(db, subject_id: int, status: str, on: date | None = None, *, today: date | None = None) -> Subject:
    """Stav zápočtu + datum (u splněn/neuznán výchozí dnešek, u nesplněn žádné). Volající commituje."""
    if status not in CREDIT_LABELS:
        raise ProgressError("Stav zápočtu: nesplněn, splněn nebo neuznán.", 422, "invalid_credit_status")
    today = today or today_local()
    s = _subject(db, subject_id)
    new_date = None if status == "pending" else (on or today)
    if new_date and new_date > today:
        raise ProgressError("Datum zápočtu nemůže být v budoucnosti.", 422, "future_date")
    old_status, old_date = credit_status(s), s.credit_date
    if old_status == status and old_date == new_date:
        return s
    s.credit_status, s.credit_date = status, new_date
    db.flush()
    delta = {}
    if old_status != status:
        delta["credit_status"] = {"old": old_status, "new": status}
    if old_date != new_date:
        delta["credit_date"] = {"old": old_date.isoformat() if old_date else None,
                                "new": new_date.isoformat() if new_date else None}
    append_domain_event(
        db, event_type="school.subject.credit_changed", aggregate_type="subject", aggregate_id=s.id,
        payload={"subject_id": s.id, "credit_status": status, "previous_status": old_status,
                 "credit_date": new_date.isoformat() if new_date else None},
        activity=ActivityProjection("school", "update", f"Zápočet {CREDIT_LABELS[status]}: {s.name}",
                                    entity_type="Subject", entity_id=s.id, delta=delta),
    )
    return s


def set_attendance(db, subject_id: int, week: date, present: bool | None, *, today: date | None = None) -> Subject:
    """Byl / nebyl za týden (`present` None = záznam smazat). Jen aktivní předmět, ne budoucí týden."""
    today = today or today_local()
    if week.weekday() != 0:
        raise ProgressError("Týden začíná pondělím.", 422, "invalid_week")
    if week > week_start(today):
        raise ProgressError("Docházku nejde zapsat do budoucího týdne.", 422, "future_week")
    s = _subject(db, subject_id)
    if s.active is False:
        raise ProgressError("Předmět je archivovaný.", 409, "archived")
    row = (db.query(SchoolAttendance)
           .filter(SchoolAttendance.subject_id == s.id, SchoolAttendance.week_start == week).one_or_none())
    old = None if row is None else row.present
    if old == present:
        return s
    if present is None:
        db.delete(row)
    elif row is None:
        db.add(SchoolAttendance(subject_id=s.id, week_start=week, present=present, updated_at=utc_now()))
    else:
        row.present, row.updated_at = present, utc_now()
    db.flush()
    word = {True: "byl", False: "nebyl", None: "nezapsáno"}
    # vlastní klíč pro každou skutečnou změnu: výchozí klíč (souhrn) by Byl → Nebyl → Byl zahodil jako duplikát;
    # opakovaný stejný požadavek sem nedojde (výše `old == present` = nic)
    log_activity(db, "school", "update", f"Docházka {s.name}, {week_label(week)}: {word[present]}",
                 entity_type="Subject", entity_id=s.id,
                 delta={"attendance": {"week_start": week.isoformat(), "old": old, "new": present}},
                 dedupe_key=f"school.attendance:{s.id}:{week.isoformat()}:{uuid4().hex}")
    return s


# ---------- Dnes (Pozornost / Co hoří) a AI kontext ----------


def today_overdue(c) -> list[TodayItem]:
    items = []
    for s, a in warnings(c.db, c.today):
        items.append(TodayItem(
            id=f"subject:{s.id}", type="subject", title=s.name,
            subtitle=f"Docházka · absence {a.absent} z max. {a.limit}"
                     + {"exceeded": " · limit překročen", "exhausted": " · už žádná nezbývá",
                        "last": " · zbývá poslední"}[a.level],
            area="school", date=c.today.isoformat(), status="open",
            severity="important" if a.level == "exceeded" else "warning",
            href=f"/school?subject={s.id}", source_id=s.id,
        ))
    return items


def context_lines(db, today: date) -> list[str]:
    """Výsledky výpočtu pro AI kontext Školy (jen aktivní předměty, žádné surové záznamy)."""
    data = subject_progress(db, today)["subjects"]
    if not data:
        return []
    credits = []
    attendance = []
    for s in data:
        c = s["credit"]
        credits.append(f"{s['name']} {c['label']}" + (f" ({c['date']})" if c["date"] else ""))
        ex = s["exams"]
        if ex["closed"]:
            res = ", ".join(f"{r['title']}: {r['result'] or r['outcome_label']}" for r in ex["results"][:3])
            credits[-1] += f"; zkoušky uzavřené {ex['closed']} (složeno {ex['passed']}, nesloženo {ex['failed']}): {res}"
        a = s["attendance"]
        if a["recorded"] or a["limit"] is not None:
            attendance.append(f"{s['name']}: {a['text']}")
    lines = ["Zápočty: " + "; ".join(credits)]
    if attendance:
        lines.append("Docházka (týdny): " + "; ".join(attendance))
    warn = [warning_text(s.name, a) for s, a in warnings(db, today)]
    if warn:
        lines.append("Varování absencí: " + "; ".join(w for w in warn if w))
    return lines


# ---------- REST ----------


class CreditRequest(BaseModel):
    status: str
    date: dt.date | None = None  # pole se jmenuje jako typ – proto dt.date


class AttendanceRequest(BaseModel):
    week_start: date
    # povinné, ale nullable: smazání je jen explicitní `null`; chybějící pole = 422, nic se nesmaže (review)
    present: bool | None


def _run(fn, *, commit: bool = False):
    db = database.SessionLocal()
    try:
        result = fn(db)
        if commit:
            db.commit()
        return result
    except ProgressError as error:
        db.rollback()
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from None
    finally:
        db.close()


@router.get("/progress")
def progress_get(include_archived: bool = False):
    return _run(lambda db: subject_progress(db, include_archived=include_archived))


def _one(db, subject_id: int) -> dict:
    s = _subject(db, subject_id)
    return next(x for x in subject_progress(db, include_archived=True)["subjects"] if x["id"] == s.id)


@router.put("/subject/{subject_id}/credit")
def credit_put(subject_id: int, request: CreditRequest):
    def run(db):
        set_credit(db, subject_id, request.status, request.date)
        db.commit()
        return _one(db, subject_id)
    return _run(run)


@router.put("/subject/{subject_id}/attendance")
def attendance_put(subject_id: int, request: AttendanceRequest):
    def run(db):
        set_attendance(db, subject_id, request.week_start, request.present)
        db.commit()
        return _one(db, subject_id)
    return _run(run)
