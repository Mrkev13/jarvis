from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import calendar

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from goal_history_service import compute_goal_progress_and_value, compute_goal_stagnation
from models import Assignment, Exam, Goal, Memory, PlannerRecommendationHistory
from read_queries import EXAM_OPEN_STATUSES


@dataclass(frozen=True)
class PlannerActionCandidate:
    mode: str
    area: str
    title: str
    reason: str
    priority: int
    recommendation_key: str


def _now() -> datetime:
    return datetime.utcnow()


def _stagnation_threshold_days(priority: str) -> int:
    p = (priority or "medium").lower()
    if p == "high":
        return 7
    if p == "low":
        return 30
    return 14


def _days_left(target: date, today: date) -> int:
    return (target - today).days


def _deadline_actions_for_assignments(mode: str, db: Session, today: date) -> list[PlannerActionCandidate]:
    actions: list[PlannerActionCandidate] = []
    items = db.query(Assignment).filter(Assignment.due_date.is_not(None)).all()

    for it in items:
        if not it.due_date:
            continue
        dl = _days_left(it.due_date, today)
        if dl < 0:
            actions.append(
                PlannerActionCandidate(
                    mode=mode,
                    area="school",
                    title=f"Vyřešit overdue úkol: {it.title}",
                    reason=f"Deadline byl {it.due_date.isoformat()} (po termínu).",
                    priority=1,
                    recommendation_key=f"assignment:overdue:{it.id}",
                )
            )
            continue

        max_days = 3 if mode == "daily" else 14
        if dl > max_days:
            continue
        if mode == "weekly" and dl > 14:
            continue
        if mode == "daily" and dl > 3:
            continue

        actions.append(
            PlannerActionCandidate(
                mode=mode,
                area="school",
                title=f"Připravit/odevzdat úkol: {it.title}",
                reason=f"Deadline {it.due_date.isoformat()} (zbývá {dl} dní).",
                priority=2 if dl > 0 else 1,
                recommendation_key=f"assignment:deadline:{dl}:{it.id}",
            )
        )

    return actions


def _deadline_actions_for_exams(mode: str, db: Session, today: date) -> list[PlannerActionCandidate]:
    actions: list[PlannerActionCandidate] = []
    items = db.query(Exam).filter(Exam.exam_date.is_not(None)).all()

    for it in items:
        if not it.exam_date:
            continue
        if (it.status or "").strip().lower() not in EXAM_OPEN_STATUSES:
            continue  # složená/neúspěšná zkouška už není úkol (stejně jako Denní přehled a AI kontext)
        dl = _days_left(it.exam_date, today)
        if dl < 0:
            actions.append(
                PlannerActionCandidate(
                    mode=mode,
                    area="school",
                    title=f"Zkontrolovat overdue zkoušku: {it.title}",
                    reason=f"Termín byl {it.exam_date.isoformat()} (po termínu).",
                    priority=1,
                    recommendation_key=f"exam:overdue:{it.id}",
                )
            )
            continue

        max_days = 3 if mode == "daily" else 14
        if dl > max_days:
            continue
        if mode == "daily" and dl > 3:
            continue

        actions.append(
            PlannerActionCandidate(
                mode=mode,
                area="school",
                title=f"Připravit se na zkoušku: {it.title}",
                reason=f"Termín {it.exam_date.isoformat()} (zbývá {dl} dní).",
                priority=2 if dl > 0 else 1,
                recommendation_key=f"exam:deadline:{dl}:{it.id}",
            )
        )

    return actions


def _deadline_actions_for_goals(mode: str, db: Session, today: date) -> list[PlannerActionCandidate]:
    actions: list[PlannerActionCandidate] = []
    items = db.query(Goal).filter(Goal.target_date.is_not(None)).all()

    for it in items:
        if not it.target_date:
            continue
        status = (it.status or "").lower()
        if status in ("completed", "paused", "cancelled"):
            continue

        dl = _days_left(it.target_date, today)
        if dl < 0:
            actions.append(
                PlannerActionCandidate(
                    mode=mode,
                    area=(it.area or "general"),
                    title=f"Řešit overdue cíl: {it.title}",
                    reason=f"Target date byl {it.target_date.isoformat()} (po termínu).",
                    priority=1,
                    recommendation_key=f"goal:overdue:{it.id}",
                )
            )
            continue

        if mode == "daily":
            if dl > 3:
                continue
        else:
            if dl > 14:
                continue

        actions.append(
            PlannerActionCandidate(
                mode=mode,
                area=(it.area or "general"),
                title=f"Posunout cíl: {it.title}",
                reason=f"Target date {it.target_date.isoformat()} (zbývá {dl} dní).",
                priority=2,
                recommendation_key=f"goal:deadline:{dl}:{it.id}",
            )
        )

    return actions


def _stagnation_actions(mode: str, db: Session, today: date) -> list[PlannerActionCandidate]:
    actions: list[PlannerActionCandidate] = []
    goals = db.query(Goal).all()
    for g in goals:
        status = (g.status or "").lower()
        if status in ("completed", "paused", "cancelled"):
            continue
        info = compute_goal_stagnation(db, g.id, today=today)
        if info.days_since_last_positive is None:
            continue
        threshold = _stagnation_threshold_days(g.priority)
        if info.days_since_last_positive < threshold:
            continue

        prio = 3 if (g.priority or "").lower() == "high" else 4
        if mode == "daily" and (g.priority or "").lower() != "high":
            prio = 5

        actions.append(
            PlannerActionCandidate(
                mode=mode,
                area=(g.area or "general"),
                title=f"Posunout stagnující cíl: {g.title}",
                reason=f"Cíl se {info.days_since_last_positive} dní neposunul.",
                priority=prio,
                recommendation_key=f"goal:stagnation:{g.id}",
            )
        )
    return actions


def _work_behind_actions(mode: str, db: Session, today: date) -> list[PlannerActionCandidate]:
    actions: list[PlannerActionCandidate] = []
    goals = (
        db.query(Goal)
        .filter(func.lower(func.coalesce(Goal.tracking_type, "manual")) == "automatic")
        .filter(Goal.source == "work_month_hours")
        .all()
    )
    last_day = calendar.monthrange(today.year, today.month)[1]
    elapsed_fraction = max(0.0, min(1.0, float(today.day) / float(last_day)))

    for g in goals:
        status = (g.status or "").lower()
        if status in ("completed", "paused", "cancelled"):
            continue
        if g.target_value is None or float(g.target_value) <= 0:
            continue
        progress, current_value = compute_goal_progress_and_value(db, g, today=today)
        if current_value is None:
            continue
        expected = elapsed_fraction * float(g.target_value)
        tolerance = 0.10 * float(g.target_value)
        if float(current_value) + tolerance >= expected:
            continue

        actions.append(
            PlannerActionCandidate(
                mode=mode,
                area="work",
                title=f"Zvýšit work tempo: {g.title}",
                reason=f"Aktuálně {float(current_value):.1f} h, očekávaně ~{expected:.1f} h.",
                priority=3 if mode == "daily" else 4,
                recommendation_key=f"work:behind:{g.id}",
            )
        )
    return actions


def _relevant_memories(db: Session) -> list[dict]:
    items = (
        db.query(Memory)
        .filter(Memory.active == True)
        .order_by(Memory.importance.desc(), Memory.updated_at.desc())
        .limit(6)
        .all()
    )
    return [
        {
            "id": it.id,
            "area": it.area,
            "category": it.category,
            "content": it.content,
            "importance": it.importance,
        }
        for it in items
    ]


def _apply_recommendation_history(
    db: Session,
    mode: str,
    candidates: list[PlannerActionCandidate],
    now: datetime,
) -> tuple[list[PlannerActionCandidate], int]:
    window_days = 1 if mode == "daily" else 3
    cutoff = now - timedelta(days=window_days)

    keys = {c.recommendation_key for c in candidates}
    if not keys:
        return candidates, 0

    recent = (
        db.query(PlannerRecommendationHistory)
        .filter(PlannerRecommendationHistory.mode == mode)
        .filter(PlannerRecommendationHistory.recommendation_key.in_(list(keys)))
        .filter(PlannerRecommendationHistory.created_at >= cutoff)
        .all()
    )
    recent_set = {r.recommendation_key for r in recent}

    adjusted: list[PlannerActionCandidate] = []
    for c in candidates:
        if c.recommendation_key in recent_set:
            adjusted.append(
                PlannerActionCandidate(
                    mode=c.mode,
                    area=c.area,
                    title=c.title,
                    reason=f"Stále platí: {c.reason}",
                    priority=c.priority,
                    recommendation_key=c.recommendation_key,
                )
            )
        else:
            adjusted.append(c)

    created = 0
    for c in candidates:
        if c.recommendation_key in recent_set:
            continue
        db.add(
            PlannerRecommendationHistory(
                mode=mode,
                area=c.area,
                recommendation_key=c.recommendation_key,
                title=c.title,
                created_at=now,
            )
        )
        created += 1

    return adjusted, created


def generate_plan(db: Session, mode: str, today: date | None = None) -> dict:
    d = today or date.today()
    now = _now()
    m = (mode or "").strip().lower()
    if m not in ("daily", "weekly", "goal_review"):
        m = "weekly"

    if m == "goal_review":
        goals = db.query(Goal).all()
        items = []
        for g in goals:
            status = (g.status or "").lower()
            if status in ("completed", "paused", "cancelled"):
                continue

            progress, current_value = compute_goal_progress_and_value(db, g, today=d)
            info = compute_goal_stagnation(db, g.id, today=d)

            trend = "unknown"
            hist = (
                db.query(func.count())
                .select_from(PlannerRecommendationHistory)
                .filter(PlannerRecommendationHistory.mode == "goal_review")
                .filter(PlannerRecommendationHistory.recommendation_key == f"goal_review:{g.id}")
                .scalar()
            )
            _ = hist

            on_track = "unknown"
            if (g.tracking_type or "").lower() == "automatic" and (g.source or "") == "work_month_hours" and g.target_value:
                last_day = calendar.monthrange(d.year, d.month)[1]
                elapsed_fraction = max(0.0, min(1.0, float(d.day) / float(last_day)))
                expected = elapsed_fraction * float(g.target_value)
                tolerance = 0.10 * float(g.target_value)
                if current_value is not None:
                    if float(current_value) + tolerance < expected:
                        on_track = "behind"
                    else:
                        on_track = "on_track"

            stagnating = False
            if info.days_since_last_positive is not None:
                threshold = _stagnation_threshold_days(g.priority)
                stagnating = info.days_since_last_positive >= threshold

            items.append(
                {
                    "id": g.id,
                    "area": g.area,
                    "title": g.title,
                    "status": g.status,
                    "priority": g.priority,
                    "tracking_type": (g.tracking_type or "manual").lower(),
                    "progress": progress,
                    "current_value": current_value,
                    "target_value": float(g.target_value) if g.target_value is not None else None,
                    "source": g.source,
                    "target_date": g.target_date.isoformat() if g.target_date else None,
                    "days_since_last_positive": info.days_since_last_positive,
                    "stagnating": stagnating,
                    "on_track": on_track,
                    "trend": trend,
                }
            )

        return {
            "mode": "goal_review",
            "summary": f"Aktivních cílů: {len(items)}",
            "goals": items,
        }

    candidates: list[PlannerActionCandidate] = []
    candidates.extend(_deadline_actions_for_assignments(m, db, d))
    candidates.extend(_deadline_actions_for_exams(m, db, d))
    candidates.extend(_deadline_actions_for_goals(m, db, d))
    candidates.extend(_work_behind_actions(m, db, d))
    candidates.extend(_stagnation_actions(m, db, d))

    candidates.sort(key=lambda c: (c.priority, c.area, c.title))

    adjusted, history_created = _apply_recommendation_history(db, m, candidates, now)

    max_actions = 5 if m in ("daily", "weekly") else 8
    chosen = adjusted[:max_actions]

    memories = _relevant_memories(db) if m == "weekly" else []
    summary = (
        "Denní plán: nejdůležitější věci podle deadlinů, práce a stagnace."
        if m == "daily"
        else "Týdenní plán: priority podle deadlinů, práce, cílů a relevantních memory."
    )
    if memories:
        summary += f" Memory: {len(memories)} relevantních položek."

    return {
        "mode": m,
        "summary": summary,
        "actions": [
            {
                "priority": idx + 1,
                "area": a.area,
                "title": a.title,
                "reason": a.reason,
            }
            for idx, a in enumerate(chosen)
        ],
        "meta": {
            "history_created": history_created,
            "memories": memories,
        },
    }
