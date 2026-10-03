"""Filtrované a omezené read dotazy pro AI tooly (Roadmap 3.0 A5).

REST endpointy dál používají plné seznamy z `tools.py` (tvar odpovědí se nemění). AI tooly místo toho
dostanou jen to, co dotaz potřebuje: filtry (typ, kategorie, projekt, stav, období) a strop počtu položek.
Výsledek je obálka `{"items", "total", "returned", "truncated", "filters"}` – model tak ví, že existuje víc
dat a může se doptat užším filtrem, místo aby dostal stovky řádků do promptu.

Všechny funkce berou `db` (session aktuálního AI requestu); data se jen čtou.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models import ActivityLog, Assignment, Exam, FinanceTransaction, Subject, WorkSession
from time_utils import local_day_bounds_utc, utc_now

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_ACTIVITY_DAYS = 7
MAX_ACTIVITY_DAYS = 90

ASSIGNMENT_DONE_STATUSES = frozenset({"done", "completed", "hotovo", "closed", "finished"})
EXAM_OPEN_STATUSES = frozenset({"upcoming", "scheduled", ""})
GOAL_OPEN_EXCLUDED = frozenset({"completed", "cancelled"})


def _limit(value) -> int:
    try:
        n = int(value) if value is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(1, min(n, MAX_LIMIT))


def _parse_date(value, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"{name} musí být datum YYYY-MM-DD") from exc


def _envelope(items: list[dict], total: int, filters: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "returned": len(items),
        "truncated": total > len(items),
        "filters": {k: v for k, v in filters.items() if v not in (None, "")},
    }


def _like(column, text: str):
    return func.lower(column).like(f"%{text.strip().lower()}%")


def query_finance_transactions(
    db: Session,
    limit: int | None = None,
    transaction_type: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Transakce od nejnovější; období je v pražských kalendářních dnech (včetně obou krajních)."""
    n = _limit(limit)
    start, end = _parse_date(date_from, "date_from"), _parse_date(date_to, "date_to")
    q = db.query(FinanceTransaction)
    if transaction_type:
        q = q.filter(func.lower(FinanceTransaction.transaction_type) == transaction_type.strip().lower())
    if category and category.strip():
        q = q.filter(_like(FinanceTransaction.category, category))
    if start:
        q = q.filter(FinanceTransaction.created_at >= local_day_bounds_utc(start)[0])
    if end:
        q = q.filter(FinanceTransaction.created_at < local_day_bounds_utc(end)[1])
    total = q.count()
    rows = q.order_by(FinanceTransaction.created_at.desc(), FinanceTransaction.id.desc()).limit(n).all()
    items = [
        {
            "id": t.id,
            "amount": t.amount,
            "category": t.category,
            "description": t.description,
            "transaction_type": t.transaction_type,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]
    return _envelope(items, total, {
        "limit": n, "transaction_type": transaction_type, "category": category,
        "date_from": date_from, "date_to": date_to,
    })


def query_work_sessions(
    db: Session,
    limit: int | None = None,
    project: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Pracovní směny od nejnovější, volitelně jen projekt (podřetězec) a období."""
    n = _limit(limit)
    start, end = _parse_date(date_from, "date_from"), _parse_date(date_to, "date_to")
    q = db.query(WorkSession)
    if project and project.strip():
        q = q.filter(_like(WorkSession.project, project))
    if start:
        q = q.filter(WorkSession.date >= start)
    if end:
        q = q.filter(WorkSession.date <= end)
    total = q.count()
    rows = q.order_by(WorkSession.date.desc(), WorkSession.id.desc()).limit(n).all()
    items = [
        {
            "id": s.id,
            "date": s.date.isoformat(),
            "hours": s.hours,
            "project": s.project,
            "description": s.description,
            "hourly_rate": s.hourly_rate,
            "earnings": round((s.hours or 0) * (s.hourly_rate or 0), 2),
            "finance_transaction_id": s.finance_transaction_id,
            "sync_to_finance": bool(s.sync_to_finance if s.sync_to_finance is not None else True),
        }
        for s in rows
    ]
    return _envelope(items, total, {"limit": n, "project": project, "date_from": date_from, "date_to": date_to})


def _subject_names(db: Session, subject_ids: set[int]) -> dict[int, str]:
    if not subject_ids:
        return {}
    return {s.id: s.name for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()}


def query_school_assignments(
    db: Session,
    limit: int | None = None,
    status: str | None = "open",
    subject_id: int | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
) -> dict:
    """Úkoly podle termínu (bez termínu na konci). status: open (default = nehotové), all, nebo přesný stav."""
    n = _limit(limit)
    start, end = _parse_date(due_from, "due_from"), _parse_date(due_to, "due_to")
    status_norm = (status or "open").strip().lower()
    q = db.query(Assignment)
    if status_norm == "open":
        q = q.filter(or_(Assignment.status.is_(None), func.lower(Assignment.status).notin_(ASSIGNMENT_DONE_STATUSES)))
    elif status_norm != "all":
        q = q.filter(func.lower(Assignment.status) == status_norm)
    if subject_id is not None:
        q = q.filter(Assignment.subject_id == subject_id)
    if start:
        q = q.filter(Assignment.due_date >= start)
    if end:
        q = q.filter(Assignment.due_date <= end)
    total = q.count()
    rows = q.order_by(Assignment.due_date.is_(None), Assignment.due_date, Assignment.id).limit(n).all()
    names = _subject_names(db, {a.subject_id for a in rows})
    items = [
        {
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "due_date": a.due_date.isoformat() if a.due_date else None,
            "priority": a.priority,
            "status": a.status,
            "subject_id": a.subject_id,
            "subject_name": names.get(a.subject_id, ""),
        }
        for a in rows
    ]
    return _envelope(items, total, {
        "limit": n, "status": status_norm, "subject_id": subject_id, "due_from": due_from, "due_to": due_to,
    })


def query_school_exams(
    db: Session,
    limit: int | None = None,
    status: str | None = "open",
    subject_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Zkoušky podle data. status: open (default = upcoming/scheduled), all, nebo přesný stav."""
    n = _limit(limit)
    start, end = _parse_date(date_from, "date_from"), _parse_date(date_to, "date_to")
    status_norm = (status or "open").strip().lower()
    q = db.query(Exam)
    if status_norm == "open":
        q = q.filter(or_(Exam.status.is_(None), func.lower(Exam.status).in_(EXAM_OPEN_STATUSES)))
    elif status_norm != "all":
        q = q.filter(func.lower(Exam.status) == status_norm)
    if subject_id is not None:
        q = q.filter(Exam.subject_id == subject_id)
    if start:
        q = q.filter(Exam.exam_date >= start)
    if end:
        q = q.filter(Exam.exam_date <= end)
    total = q.count()
    rows = q.order_by(Exam.exam_date.is_(None), Exam.exam_date, Exam.id).limit(n).all()
    names = _subject_names(db, {e.subject_id for e in rows})
    items = [
        {
            "id": e.id,
            "title": e.title,
            "exam_type": e.exam_type,
            "exam_date": e.exam_date.isoformat() if e.exam_date else None,
            "status": e.status,
            "notes": e.notes,
            "subject_id": e.subject_id,
            "subject_name": names.get(e.subject_id, ""),
        }
        for e in rows
    ]
    return _envelope(items, total, {
        "limit": n, "status": status_norm, "subject_id": subject_id, "date_from": date_from, "date_to": date_to,
    })


def query_goals(
    db: Session,
    limit: int | None = None,
    area: str | None = None,
    status: str | None = None,
) -> dict:
    """Cíle se stejným výpočtem progresu jako REST /goals (tools.get_goals), jen filtrované a omezené.

    status: open (bez completed/cancelled), all (default), nebo přesný stav.
    """
    import tools  # lokálně: tools.get_goals počítá automatický progres (sdílená logika, žádná kopie)

    n = _limit(limit)
    status_norm = (status or "all").strip().lower()
    goals = tools.get_goals()
    if area and area.strip():
        goals = [g for g in goals if (g.get("area") or "").lower() == area.strip().lower()]
    if status_norm == "open":
        goals = [g for g in goals if (g.get("status") or "").lower() not in GOAL_OPEN_EXCLUDED]
    elif status_norm != "all":
        goals = [g for g in goals if (g.get("status") or "").lower() == status_norm]
    return _envelope(goals[:n], len(goals), {"limit": n, "area": area, "status": status_norm})


def query_recent_activity(
    db: Session,
    limit: int | None = None,
    area: str | None = None,
    days: int | None = None,
    now_utc: datetime | None = None,
) -> dict:
    """Poslední změny v aplikaci (activity log) za posledních `days` dní, od nejnovější. Bez delta JSON."""
    n = _limit(limit)
    try:
        d = int(days) if days is not None else DEFAULT_ACTIVITY_DAYS
    except (TypeError, ValueError):
        d = DEFAULT_ACTIVITY_DAYS
    d = max(1, min(d, MAX_ACTIVITY_DAYS))
    since = (now_utc or utc_now()) - timedelta(days=d)
    q = db.query(ActivityLog).filter(ActivityLog.timestamp >= since)
    if area and area.strip():
        q = q.filter(func.lower(ActivityLog.area) == area.strip().lower())
    total = q.count()
    rows = q.order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc()).limit(n).all()
    items = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "area": r.area,
            "action_type": r.action_type,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "summary": r.summary,
        }
        for r in rows
    ]
    return _envelope(items, total, {"limit": n, "area": area, "days": d})
