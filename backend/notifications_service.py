from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, time
import calendar

from sqlalchemy import or_
from sqlalchemy.orm import Session

from goal_history_service import compute_goal_stagnation, compute_goal_progress_and_value
from models import Assignment, Exam, Goal, Notification
from text_utils import days_left_cz, format_date_cz
from time_utils import today_local
from statuses import ASSIGNMENT_DONE_STATUSES, EXAM_OPEN_STATUSES, GOAL_INACTIVE_STATUSES




@dataclass(frozen=True)
class NotificationCandidate:
    dedupe_key: str
    area: str
    title: str
    message: str
    severity: str
    notification_type: str
    source_type: str
    source_id: int | None
    action_url: str | None
    expires_at: datetime | None


def _now() -> datetime:
    return datetime.utcnow()


def _severity_for_days(days_left: int) -> str:
    if days_left <= 3:
        return "important"
    if days_left <= 7:
        return "warning"
    return "info"


def _deadline_band(days_left: int) -> str:
    if days_left <= 3:
        return "3d"
    if days_left <= 7:
        return "7d"
    return "14d"


def _upsert_notification(db: Session, cand: NotificationCandidate, now: datetime) -> Notification:
    existing = (
        db.query(Notification)
        .filter(Notification.dedupe_key == cand.dedupe_key)
        .filter(Notification.resolved == False)
        .first()
    )
    if existing:
        existing.area = cand.area
        existing.title = cand.title
        existing.message = cand.message
        existing.severity = cand.severity
        existing.notification_type = cand.notification_type
        existing.source_type = cand.source_type
        existing.source_id = cand.source_id
        existing.last_triggered_at = now
        existing.expires_at = cand.expires_at
        existing.action_url = cand.action_url
        return existing

    n = Notification(
        area=cand.area,
        title=cand.title,
        message=cand.message,
        severity=cand.severity,
        read=False,
        created_at=now,
        expires_at=cand.expires_at,
        notification_type=cand.notification_type,
        source_type=cand.source_type,
        source_id=cand.source_id,
        dedupe_key=cand.dedupe_key,
        last_triggered_at=now,
        resolved=False,
        action_url=cand.action_url,
    )
    db.add(n)
    return n


def _resolve_other_deadline_notifications(
    db: Session,
    source_type: str,
    source_id: int,
    keep_dedupe_key: str,
) -> int:
    rows = (
        db.query(Notification)
        .filter(Notification.source_type == source_type)
        .filter(Notification.source_id == source_id)
        .filter(Notification.notification_type.in_(["deadline", "overdue"]))
        .filter(Notification.resolved == False)
        .filter(Notification.dedupe_key != keep_dedupe_key)
        .all()
    )
    for r in rows:
        r.resolved = True
    return len(rows)


def _resolve_if_no_longer_relevant(
    db: Session,
    dedupe_keys_still_relevant: set[str],
    now: datetime,
) -> int:
    rows = (
        db.query(Notification)
        .filter(Notification.resolved == False)
        .filter(or_(Notification.expires_at.is_(None), Notification.expires_at >= now))
        .all()
    )
    changed = 0
    for r in rows:
        if r.dedupe_key not in dedupe_keys_still_relevant and r.notification_type in (
            "deadline",
            "overdue",
            "goal_stagnation",
            "work_behind",
            "finance_goal_stagnation",
        ):
            r.resolved = True
            changed += 1
    return changed


def _clean_expired(db: Session, now: datetime) -> int:
    rows = (
        db.query(Notification)
        .filter(Notification.resolved == False)
        .filter(Notification.expires_at.is_not(None))
        .filter(Notification.expires_at < now)
        .all()
    )
    for r in rows:
        r.resolved = True
    return len(rows)


def _deadline_candidates_for_assignment(it: Assignment, today: date) -> NotificationCandidate | None:
    if not it.due_date:
        return None
    if (it.status or "").strip().lower() in ASSIGNMENT_DONE_STATUSES:
        return None  # hotový úkol: žádný deadline (starý se vyřeší jako „no longer relevant")
    days_left = (it.due_date - today).days
    if days_left < 0:
        dedupe_key = f"assignment_overdue:{it.id}"
        return NotificationCandidate(
            dedupe_key=dedupe_key,
            area="school",
            title=f"Po termínu: {it.title}",
            message=f"Úkol měl termín {format_date_cz(it.due_date)} a je po termínu.",
            severity="important",
            notification_type="overdue",
            source_type="assignment",
            source_id=it.id,
            action_url="/school",
            expires_at=datetime.combine(it.due_date, datetime.min.time()) + timedelta(days=30),
        )
    if days_left <= 14:
        band = _deadline_band(days_left)
        dedupe_key = f"assignment_deadline_{band}:{it.id}"
        sev = _severity_for_days(days_left)
        return NotificationCandidate(
            dedupe_key=dedupe_key,
            area="school",
            title=f"Termín: {it.title}",
            message=f"Termín úkolu je {format_date_cz(it.due_date)} ({days_left_cz(days_left)}).",
            severity=sev,
            notification_type="deadline",
            source_type="assignment",
            source_id=it.id,
            action_url="/school",
            expires_at=datetime.combine(it.due_date, datetime.min.time()) + timedelta(days=2),
        )
    return None


def _deadline_candidates_for_exam(it: Exam, today: date) -> NotificationCandidate | None:
    if not it.exam_date:
        return None
    if (it.status or "").strip().lower() not in EXAM_OPEN_STATUSES:
        return None  # složená/neúspěšná zkouška: žádný deadline (starý se vyřeší jako „no longer relevant")
    days_left = (it.exam_date - today).days
    if days_left < 0:
        dedupe_key = f"exam_overdue:{it.id}"
        return NotificationCandidate(
            dedupe_key=dedupe_key,
            area="school",
            title=f"Po termínu: {it.title}",
            message=f"Zkouška měla termín {format_date_cz(it.exam_date)} a je po termínu.",
            severity="important",
            notification_type="overdue",
            source_type="exam",
            source_id=it.id,
            action_url="/school",
            expires_at=datetime.combine(it.exam_date, datetime.min.time()) + timedelta(days=30),
        )
    if days_left <= 14:
        band = _deadline_band(days_left)
        dedupe_key = f"exam_deadline_{band}:{it.id}"
        sev = _severity_for_days(days_left)
        return NotificationCandidate(
            dedupe_key=dedupe_key,
            area="school",
            title=f"Termín: {it.title}",
            message=f"Zkouška je {format_date_cz(it.exam_date)} ({days_left_cz(days_left)}).",
            severity=sev,
            notification_type="deadline",
            source_type="exam",
            source_id=it.id,
            action_url="/school",
            expires_at=datetime.combine(it.exam_date, datetime.min.time()) + timedelta(days=2),
        )
    return None


def _deadline_candidates_for_goal(it: Goal, today: date) -> NotificationCandidate | None:
    if not it.target_date:
        return None
    status = (it.status or "").lower()
    if status in GOAL_INACTIVE_STATUSES:
        return None

    days_left = (it.target_date - today).days
    if days_left < 0:
        dedupe_key = f"goal_overdue:{it.id}"
        return NotificationCandidate(
            dedupe_key=dedupe_key,
            area=it.area or "general",
            title=f"Po termínu: {it.title}",
            message=f"Cíl měl cílové datum {format_date_cz(it.target_date)} a je po termínu.",
            severity="important",
            notification_type="overdue",
            source_type="goal",
            source_id=it.id,
            action_url="/goals",
            expires_at=datetime.combine(it.target_date, datetime.min.time()) + timedelta(days=60),
        )
    if days_left <= 14:
        band = _deadline_band(days_left)
        dedupe_key = f"goal_deadline_{band}:{it.id}"
        sev = _severity_for_days(days_left)
        return NotificationCandidate(
            dedupe_key=dedupe_key,
            area=it.area or "general",
            title=f"Termín: {it.title}",
            message=f"Cílové datum je {format_date_cz(it.target_date)} ({days_left_cz(days_left)}).",
            severity=sev,
            notification_type="deadline",
            source_type="goal",
            source_id=it.id,
            action_url="/goals",
            expires_at=datetime.combine(it.target_date, datetime.min.time()) + timedelta(days=7),
        )
    return None


def _stagnation_threshold_days(priority: str) -> int:
    p = (priority or "medium").lower()
    if p == "high":
        return 7
    if p == "low":
        return 30
    return 14


def _stagnation_candidate_for_goal(db: Session, it: Goal, today: date) -> NotificationCandidate | None:
    status = (it.status or "").lower()
    if status in GOAL_INACTIVE_STATUSES:
        return None

    info = compute_goal_stagnation(db, it.id, today=today)
    if info.days_since_last_positive is None:
        return None

    threshold = _stagnation_threshold_days(it.priority)
    if info.days_since_last_positive < threshold:
        return None

    dedupe_key = f"goal_stagnation:{it.id}"
    return NotificationCandidate(
        dedupe_key=dedupe_key,
        area=it.area or "general",
        title=f"Cíl stagnuje: {it.title}",
        message=f"Cíl se {info.days_since_last_positive} dní neposunul.",
        severity="warning" if (it.priority or "").lower() != "high" else "important",
        notification_type="goal_stagnation",
        source_type="goal",
        source_id=it.id,
        action_url="/goals",
        expires_at=None,
    )


def _work_behind_candidate_for_goal(db: Session, it: Goal, today: date) -> NotificationCandidate | None:
    tracking_type = (it.tracking_type or "manual").lower()
    if tracking_type != "automatic":
        return None
    if (it.source or "") != "work_month_hours":
        return None
    status = (it.status or "").lower()
    if status in GOAL_INACTIVE_STATUSES:
        return None
    if it.target_value is None or float(it.target_value) <= 0:
        return None

    current_progress, current_value = compute_goal_progress_and_value(db, it, today=today)
    if current_value is None:
        return None

    last_day = calendar.monthrange(today.year, today.month)[1]
    elapsed_fraction = max(0.0, min(1.0, float(today.day) / float(last_day)))
    expected_value = elapsed_fraction * float(it.target_value)
    tolerance = 0.10 * float(it.target_value)

    if float(current_value) + tolerance >= expected_value:
        return None

    dedupe_key = f"work_behind:{it.id}"
    return NotificationCandidate(
        dedupe_key=dedupe_key,
        area="work",
        title=f"Práce za plánem: {it.title}",
        message=(
            f"Aktuálně {float(current_value):.1f} h, očekávaně ~{expected_value:.1f} h "
            f"({int(round(elapsed_fraction * 100))} % měsíce)."
        ),
        severity="warning",
        notification_type="work_behind",
        source_type="goal",
        source_id=it.id,
        action_url="/work",
        expires_at=None,
    )


def _finance_goal_stagnation_candidate(db: Session, it: Goal, today: date) -> NotificationCandidate | None:
    tracking_type = (it.tracking_type or "manual").lower()
    if tracking_type != "automatic":
        return None
    if (it.source or "") != "finance_balance":
        return None
    status = (it.status or "").lower()
    if status in GOAL_INACTIVE_STATUSES:
        return None
    if (it.area or "").lower() != "finance":
        return None

    info = compute_goal_stagnation(db, it.id, today=today)
    if info.days_since_last_positive is None:
        return None
    threshold = _stagnation_threshold_days(it.priority)
    if info.days_since_last_positive < threshold:
        return None

    dedupe_key = f"finance_goal_stagnation:{it.id}"
    sev = "warning" if (it.priority or "").lower() != "high" else "important"
    return NotificationCandidate(
        dedupe_key=dedupe_key,
        area="finance",
        title=f"Finanční cíl stagnuje: {it.title}",
        message=f"Finanční cíl se {info.days_since_last_positive} dní neposunul.",
        severity=sev,
        notification_type="finance_goal_stagnation",
        source_type="goal",
        source_id=it.id,
        action_url="/finance",
        expires_at=None,
    )


def generate_notifications(db: Session, today: date | None = None, now: datetime | None = None) -> dict:
    d = today or today_local()
    if now is None:
        if today is not None:
            now = datetime.combine(today, time(9, 0, 0))
        else:
            now = _now()

    expired_resolved = _clean_expired(db, now)

    assignments = db.query(Assignment).all()
    exams = db.query(Exam).all()
    goals = db.query(Goal).all()

    candidates: list[NotificationCandidate] = []

    for it in assignments:
        cand = _deadline_candidates_for_assignment(it, d)
        if cand:
            candidates.append(cand)

    for it in exams:
        cand = _deadline_candidates_for_exam(it, d)
        if cand:
            candidates.append(cand)

    for it in goals:
        cand = _deadline_candidates_for_goal(it, d)
        if cand:
            candidates.append(cand)

    for it in goals:
        cand = _stagnation_candidate_for_goal(db, it, d)
        if cand:
            candidates.append(cand)

    for it in goals:
        cand = _work_behind_candidate_for_goal(db, it, d)
        if cand:
            candidates.append(cand)

    for it in goals:
        cand = _finance_goal_stagnation_candidate(db, it, d)
        if cand:
            candidates.append(cand)

    relevant_keys = {c.dedupe_key for c in candidates}

    created = 0
    updated = 0
    resolved_other_thresholds = 0
    for c in candidates:
        before_id = (
            db.query(Notification.id)
            .filter(Notification.dedupe_key == c.dedupe_key)
            .filter(Notification.resolved == False)
            .first()
        )
        _upsert_notification(db, c, now)
        if before_id:
            updated += 1
        else:
            created += 1

        if c.notification_type in ("deadline", "overdue") and c.source_id is not None:
            resolved_other_thresholds += _resolve_other_deadline_notifications(
                db,
                source_type=c.source_type,
                source_id=c.source_id,
                keep_dedupe_key=c.dedupe_key,
            )

    resolved_irrelevant = _resolve_if_no_longer_relevant(db, relevant_keys, now)

    return {
        "created": created,
        "updated": updated,
        "resolved_other_thresholds": resolved_other_thresholds,
        "resolved_irrelevant": resolved_irrelevant,
        "expired_resolved": expired_resolved,
    }


def list_notifications(
    db: Session,
    unread_only: bool = False,
    severity: str | None = None,
    area: str | None = None,
    include_resolved: bool = False,
    now: datetime | None = None,
) -> list[dict]:
    now_dt = now or _now()
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.read == False)
    if severity:
        q = q.filter(Notification.severity == severity)
    if area:
        q = q.filter(Notification.area == area)
    if not include_resolved:
        q = q.filter(Notification.resolved == False)
    q = q.filter(or_(Notification.expires_at.is_(None), Notification.expires_at >= now_dt))

    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()).all()
    return [
        {
            "id": n.id,
            "area": n.area,
            "title": n.title,
            "message": n.message,
            "severity": n.severity,
            "read": bool(n.read),
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "created_at_ts": n.created_at.timestamp() if n.created_at else None,
            "expires_at": n.expires_at.isoformat() if n.expires_at else None,
            "notification_type": n.notification_type,
            "source_type": n.source_type,
            "source_id": n.source_id,
            "dedupe_key": n.dedupe_key,
            "last_triggered_at": n.last_triggered_at.isoformat() if n.last_triggered_at else None,
            "resolved": bool(n.resolved),
            "action_url": n.action_url,
        }
        for n in rows
    ]


def notifications_summary(db: Session, now: datetime | None = None) -> dict:
    now_dt = now or _now()
    q = (
        db.query(Notification)
        .filter(Notification.resolved == False)
        .filter(or_(Notification.expires_at.is_(None), Notification.expires_at >= now_dt))
    )

    unread = q.filter(Notification.read == False).count()
    important = q.filter(Notification.read == False).filter(Notification.severity == "important").count()
    warning = q.filter(Notification.read == False).filter(Notification.severity == "warning").count()
    info = q.filter(Notification.read == False).filter(Notification.severity == "info").count()

    return {
        "unread": unread,
        "important": important,
        "warning": warning,
        "info": info,
    }


def mark_read(db: Session, notification_id: int) -> bool:
    item = db.query(Notification).filter(Notification.id == notification_id).first()
    if item is None:
        return False
    item.read = True
    return True


def mark_all_read(db: Session) -> int:
    items = db.query(Notification).filter(Notification.read == False).all()
    for it in items:
        it.read = True
    return len(items)


def resolve(db: Session, notification_id: int) -> bool:
    item = db.query(Notification).filter(Notification.id == notification_id).first()
    if item is None:
        return False
    item.resolved = True
    return True


def create_overdue_and_upcoming_notifications(db: Session, today: date | None = None) -> int:
    stats = generate_notifications(db, today=today)
    return int(stats.get("created", 0) or 0)


def create_goal_progress_notifications(db: Session, today: date | None = None) -> int:
    stats = generate_notifications(db, today=today)
    return int(stats.get("created", 0) or 0)


def create_all_overdue_and_upcoming_notifications(db) -> int:
    created = 0
    try:
        created += create_overdue_and_upcoming_notifications(db)
    except Exception:
        pass
    try:
        created += create_goal_progress_notifications(db)
    except Exception:
        pass
    return created
