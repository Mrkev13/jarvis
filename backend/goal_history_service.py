from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import calendar

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import FinanceTransaction, Goal, GoalProgressHistory, WorkSession, MffCharacter, Assignment, Exam
from statuses import ASSIGNMENT_DONE_STATUSES, EXAM_PASSED_STATUSES, MFF_BUILT_STATUSES, norm
from time_utils import local_month_bounds_utc, today_local


def _float_equal(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 1e-9


def _is_tier_t4(tier: str | None) -> bool:
    t = (tier or "").strip().lower().replace(" ", "")
    return t in ("t4", "tier4", "transcendent")


def compute_automatic_goal_current_value_with_ok(db: Session, source: str, today: date | None = None) -> tuple[float, bool]:
    d = today or today_local()

    if source == "work_month_hours":
        month_start = date(d.year, d.month, 1)
        last_day = calendar.monthrange(d.year, d.month)[1]
        month_end = date(d.year, d.month, last_day)
        hours = (
            db.query(func.coalesce(func.sum(WorkSession.hours), 0.0))
            .filter(WorkSession.date >= month_start)
            .filter(WorkSession.date <= month_end)
            .scalar()
        )
        return float(hours or 0.0), True

    if source == "work_month_earnings":
        month_start = date(d.year, d.month, 1)
        last_day = calendar.monthrange(d.year, d.month)[1]
        month_end = date(d.year, d.month, last_day)
        rows = (
            db.query(WorkSession)
            .filter(WorkSession.date >= month_start)
            .filter(WorkSession.date <= month_end)
            .all()
        )
        total = sum(float(r.hours or 0.0) * float(r.hourly_rate or 0.0) for r in rows)
        return float(total), True

    if source == "work_total_hours":
        hours = (
            db.query(func.coalesce(func.sum(WorkSession.hours), 0.0))
            .scalar()
        )
        return float(hours or 0.0), True

    if source in ("finance_balance", "finance_total_balance"):
        income = (
            db.query(func.coalesce(func.sum(FinanceTransaction.amount), 0.0))
            .filter(FinanceTransaction.transaction_type == "income")
            .scalar()
        )
        expenses = (
            db.query(func.coalesce(func.sum(FinanceTransaction.amount), 0.0))
            .filter(FinanceTransaction.transaction_type == "expense")
            .scalar()
        )
        return float(income or 0.0) - float(expenses or 0.0), True

    if source in ("finance_month_income", "finance_month_expenses"):
        # created_at je naive UTC → pražský kalendářní měsíc převedený do UTC, [start, end).
        month_start_utc, month_end_utc = local_month_bounds_utc(d)
        kind = "income" if source == "finance_month_income" else "expense"
        amount = (
            db.query(func.coalesce(func.sum(FinanceTransaction.amount), 0.0))
            .filter(FinanceTransaction.transaction_type == kind)
            .filter(FinanceTransaction.created_at >= month_start_utc)
            .filter(FinanceTransaction.created_at < month_end_utc)
            .scalar()
        )
        return float(amount or 0.0), True

    if source == "school_completed_assignments":
        total = (
            db.query(func.count(Assignment.id))
            .filter(func.lower(func.trim(func.coalesce(Assignment.status, ""))).in_(ASSIGNMENT_DONE_STATUSES))
            .scalar()
        )
        return float(total or 0), True

    if source == "school_open_assignments":
        total_all = db.query(func.count(Assignment.id)).scalar() or 0
        completed = (
            db.query(func.count(Assignment.id))
            .filter(func.lower(func.trim(func.coalesce(Assignment.status, ""))).in_(ASSIGNMENT_DONE_STATUSES))
            .scalar()
        ) or 0
        return float(total_all - completed), True

    if source == "school_exams_passed":
        total = (
            db.query(func.count(Exam.id))
            .filter(func.lower(func.trim(func.coalesce(Exam.status, ""))).in_(EXAM_PASSED_STATUSES))
            .scalar()
        )
        return float(total or 0), True

    if source == "mff_t4_count":
        chars = db.query(MffCharacter).all()
        return float(sum(1 for c in chars if _is_tier_t4(c.tier))), True

    if source == "mff_built_t4_count":
        chars = db.query(MffCharacter).all()
        return float(
            sum(
                1
                for c in chars
                if _is_tier_t4(c.tier) and norm(c.status) in MFF_BUILT_STATUSES
            )
        ), True

    if source == "mff_high_priority_built_count":
        chars = db.query(MffCharacter).all()
        return float(
            sum(
                1
                for c in chars
                if (c.priority or "").strip().lower() == "high"
                and norm(c.status) in MFF_BUILT_STATUSES
            )
        ), True

    return 0.0, False


def compute_automatic_goal_current_value(db: Session, source: str, today: date | None = None) -> float:
    value, _ok = compute_automatic_goal_current_value_with_ok(db, source, today=today)
    return value


def compute_goal_progress_and_value(db: Session, goal: Goal, today: date | None = None) -> tuple[int, float | None]:
    tracking_type = (goal.tracking_type or "manual").lower()
    target_value = goal.target_value
    source = goal.source

    if tracking_type == "automatic" and source and target_value is not None and float(target_value) > 0:
        current_value, ok = compute_automatic_goal_current_value_with_ok(db, source, today=today)
        if ok:
            progress = min(100, max(0, int(round(float(current_value) / float(target_value) * 100))))
            return progress, float(current_value)

    progress = max(0, min(100, int(goal.progress or 0)))
    return progress, None


def record_goal_progress_snapshot(
    db: Session,
    goal_id: int,
    progress: int,
    current_value: float | None,
    recorded_at: datetime | None = None,
) -> bool:
    last = (
        db.query(GoalProgressHistory)
        .filter(GoalProgressHistory.goal_id == goal_id)
        .order_by(GoalProgressHistory.recorded_at.desc(), GoalProgressHistory.id.desc())
        .first()
    )
    progress_int = max(0, min(100, int(progress or 0)))
    now = recorded_at or datetime.utcnow()

    if last and int(last.progress or 0) == progress_int and _float_equal(last.current_value, current_value):
        return False

    db.add(
        GoalProgressHistory(
            goal_id=goal_id,
            progress=progress_int,
            current_value=float(current_value) if current_value is not None else None,
            recorded_at=now,
        )
    )
    return True


def ensure_goal_progress_snapshot(db: Session, goal: Goal, today: date | None = None) -> bool:
    progress, current_value = compute_goal_progress_and_value(db, goal, today=today)
    return record_goal_progress_snapshot(db, goal.id, progress, current_value)


@dataclass(frozen=True)
class GoalStagnationInfo:
    last_positive_at: datetime | None
    days_since_last_positive: int | None


def compute_goal_stagnation(db: Session, goal_id: int, today: date | None = None) -> GoalStagnationInfo:
    d = today or date.today()
    rows = (
        db.query(GoalProgressHistory)
        .filter(GoalProgressHistory.goal_id == goal_id)
        .order_by(GoalProgressHistory.recorded_at.asc(), GoalProgressHistory.id.asc())
        .all()
    )
    if len(rows) < 2:
        return GoalStagnationInfo(last_positive_at=None, days_since_last_positive=None)

    last_positive_at: datetime | None = None
    max_progress = -1
    max_value: float | None = None

    for r in rows:
        prog = int(r.progress or 0)
        val = r.current_value
        improved = False
        if prog > max_progress:
            improved = True
        if val is not None:
            if max_value is None or float(val) > float(max_value):
                improved = True

        if improved:
            max_progress = max(max_progress, prog)
            if val is not None:
                max_value = float(val) if max_value is None else max(float(max_value), float(val))
            last_positive_at = r.recorded_at

    if last_positive_at is None:
        return GoalStagnationInfo(last_positive_at=None, days_since_last_positive=None)

    days = (d - last_positive_at.date()).days
    return GoalStagnationInfo(last_positive_at=last_positive_at, days_since_last_positive=days)


def ensure_goal_progress_snapshot_for_all_active_automatic_goals(db) -> dict:
    from models import Goal
    goals = db.query(Goal).filter(Goal.status == "active").filter(Goal.tracking_type == "automatic").all()
    result = {"total_count": len(goals), "snapshots_created": 0}
    for g in goals:
        ok = ensure_goal_progress_snapshot(db, g)
        if ok:
            result["snapshots_created"] += 1
            result[g.id] = "snap"
    return result

