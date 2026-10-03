from datetime import datetime
import json as _json
import re

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Date, Boolean, Index, TypeDecorator
from sqlalchemy.orm import relationship

from database import Base


class JsonAsText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        try:
            parsed = _json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        if isinstance(value, str) and value.strip():
            return [p.strip() for p in re.split(r"[·,;|/\\]+", value) if p.strip()]
        return []


MFF_ROLE_OPTIONS = ["ABX", "ABL", "GBR", "World Boss", "PvP", "Dispatch", "Other"]


def compute_mff_build_completeness(
    tier: str | None,
    level: int | None,
    uniform: str | None,
    ctp: str | None,
    artifact: str | None,
    uru_slots_total: int | None,
    uru_slots_filled: int | None,
    iso8_set: str | None,
    team_supports: str | None,
) -> int:
    completed = 0
    total = 8
    t = (tier or "").strip().lower().replace(" ", "")
    if t in ("t4", "tier4", "transcendent"):
        completed += 1
    lv = int(level or 0)
    if lv >= 80:
        completed += 1
    if (uniform or "").strip():
        completed += 1
    if (ctp or "").strip():
        completed += 1
    if (artifact or "").strip():
        completed += 1
    ut = int(uru_slots_total or 0)
    uf = int(uru_slots_filled or 0)
    if ut > 0 and uf >= ut:
        completed += 1
    if (iso8_set or "").strip():
        completed += 1
    if (team_supports or "").strip():
        completed += 1
    return round(completed / total * 100)


def parse_legacy_uru_state(uru_state: str | None) -> tuple[int, int, int]:
    uru_total = 20
    uru_filled = 0
    ob_count = 0
    s = (uru_state or "").strip()
    if not s:
        return uru_total, uru_filled, ob_count
    slot_match = re.search(r"(\d+)\s*/\s*(\d+)", s)
    if slot_match:
        uru_filled = int(slot_match.group(1))
        uru_total = int(slot_match.group(2))
    ob_match = re.search(r"(\d+)\s*OB", s, flags=re.IGNORECASE)
    if ob_match:
        ob_count = int(ob_match.group(1))
    if uru_total <= 0:
        uru_total = 20
    uru_filled = max(0, min(uru_filled, uru_total))
    ob_count = max(0, ob_count)
    return uru_total, uru_filled, ob_count


def legacy_role_string_to_list(role_str: str | None) -> list[str]:
    s = (role_str or "").strip()
    if not s:
        return []
    try:
        parsed = _json.loads(s)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    parts = re.split(r"[·,;|/\\]+", s)
    normalized: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        matched = None
        pl = p.lower()
        for opt in MFF_ROLE_OPTIONS:
            if pl == opt.lower() or pl in opt.lower():
                matched = opt
                break
        if matched:
            if matched not in normalized:
                normalized.append(matched)
        else:
            if p not in normalized:
                normalized.append(p)
    return normalized


class FinanceTransaction(Base):
    __tablename__ = "finance_transactions"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float, nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(String(255), default="")
    transaction_type = Column(String(20), nullable=False)  # income / expense
    created_at = Column(DateTime, default=datetime.utcnow)


class Goal(Base):
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    area = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    status = Column(String(50), default="active")
    priority = Column(String(20), default="medium")
    progress = Column(Integer, default=0)
    tracking_type = Column(String(50), default="manual")
    target_value = Column(Float, nullable=True)
    source = Column(String(50), nullable=True)
    target_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Memory(Base):
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)

    area = Column(String(50), default="general")
    category = Column(String(50), default="context")

    content = Column(Text, nullable=False)

    importance = Column(Integer, default=5)
    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class WotResource(Base):
    __tablename__ = "wot_resources"
    id = Column(Integer, primary_key=True, index=True)
    resource = Column(String(100), unique=True, nullable=False)
    amount = Column(Float, nullable=False)

class WotGrind(Base):
    __tablename__ = "wot_grinds"

    id = Column(Integer, primary_key=True, index=True)
    tank = Column(String(100), unique=True, nullable=False)
    xp_remaining = Column(Float, default=0)
    priority = Column(String(20), default="medium")
    status = Column(String(20), default="active")


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), default="")
    semester = Column(String(50), default="")
    credits = Column(Integer, default=0)
    active = Column(Boolean, default=True)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1000), default="")
    due_date = Column(Date, nullable=True)
    priority = Column(String(20), default="medium")
    status = Column(String(20), default="todo")

    subject_id = Column(
        Integer,
        ForeignKey("subjects.id"),
        nullable=False
    )

    subject = relationship("Subject")


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    exam_type = Column(String(50), default="exam")
    exam_date = Column(Date, nullable=True)
    status = Column(String(20), default="upcoming")
    notes = Column(String(1000), default="")

    subject_id = Column(
        Integer,
        ForeignKey("subjects.id"),
        nullable=False
    )

    subject = relationship("Subject")


class WorkSession(Base):
    __tablename__ = "work_sessions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    hours = Column(Float, nullable=False)
    project = Column(String(150), default="")
    description = Column(String(500), default="")
    hourly_rate = Column(Float, default=0)
    finance_transaction_id = Column(
        Integer,
        ForeignKey("finance_transactions.id"),
        nullable=True
    )
    sync_to_finance = Column(Boolean, default=True)


class MffCharacter(Base):
    __tablename__ = "mff_characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    tier = Column(String(20), default="T3")
    level = Column(Integer, default=80)
    uniform = Column(String(150), default="")
    ctp = Column(String(100), default="")
    artifact = Column(String(100), default="")
    priority = Column(String(20), default="medium")
    status = Column(String(30), default="built")
    notes = Column(String(1000), default="")
    role = Column(String(150), default="")
    team = Column(String(255), default="")
    uru_state = Column(String(60), default="")
    iso8_set = Column(String(100), default="")
    build_completeness = Column(Integer, default=0)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    roles = Column(JsonAsText, default=list)
    team_supports = Column(String(255), default="")
    uru_slots_total = Column(Integer, default=20)
    uru_slots_filled = Column(Integer, default=0)
    odin_blessings_count = Column(Integer, default=0)


Index("ix_mff_characters_tier", MffCharacter.tier)
Index("ix_mff_characters_priority", MffCharacter.priority)
Index("ix_mff_characters_status", MffCharacter.status)
Index("ix_mff_characters_build_completeness", MffCharacter.build_completeness)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), default="Nový chat")
    # A4: shrnutí starší historie + ID poslední zprávy, kterou shrnutí pokrývá.
    summary = Column(Text, nullable=True)
    summarized_until_message_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    area = Column(String(50), default="general", nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(20), default="info", nullable=False)
    read = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    notification_type = Column(String(50), nullable=False)
    source_type = Column(String(50), nullable=False)
    source_id = Column(Integer, nullable=True)
    dedupe_key = Column(String(150), nullable=False)
    last_triggered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    action_url = Column(String(255), nullable=True)


Index("ix_notifications_read", Notification.read)
Index("ix_notifications_resolved", Notification.resolved)
Index("ix_notifications_created_at", Notification.created_at)
Index("ix_notifications_dedupe_key", Notification.dedupe_key)


class GoalProgressHistory(Base):
    __tablename__ = "goal_progress_history"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    current_value = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_goal_progress_history_goal_id", GoalProgressHistory.goal_id)
Index("ix_goal_progress_history_recorded_at", GoalProgressHistory.recorded_at)


class PlannerRecommendationHistory(Base):
    __tablename__ = "planner_recommendation_history"

    id = Column(Integer, primary_key=True, index=True)
    mode = Column(String(20), nullable=False)
    area = Column(String(50), default="general", nullable=False)
    recommendation_key = Column(String(180), nullable=False)
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_planner_recommendation_history_mode", PlannerRecommendationHistory.mode)
Index("ix_planner_recommendation_history_recommendation_key", PlannerRecommendationHistory.recommendation_key)
Index("ix_planner_recommendation_history_created_at", PlannerRecommendationHistory.created_at)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    area = Column(String(50), nullable=False)
    action_type = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)
    summary = Column(String(500), nullable=False)
    delta_json = Column(Text, nullable=True)
    user_context = Column(String(100), nullable=True)
    # Unikátnost hlídá výhradně ix_activity_dedupe_key (bez duplicitního column UNIQUE).
    dedupe_key = Column(String(180), nullable=True)


Index("ix_activity_area_timestamp", ActivityLog.area, ActivityLog.timestamp.desc())
Index("ix_activity_dedupe_key", ActivityLog.dedupe_key, unique=True)


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id = Column(Integer, primary_key=True, index=True)
    tool = Column(String(100), nullable=False)
    arguments = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)


Index("ix_pending_status_created", PendingAction.status, PendingAction.created_at)


class BackupLog(Base):
    __tablename__ = "backup_logs"
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")
    filename = Column(String(500), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    checksum = Column(String(128), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    retention_days = Column(Integer, nullable=False, default=30)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(256), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=True, index=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    revoked = Column(Boolean, default=False, nullable=False)




class Reminder(Base):
    """Připomínka (Roadmap 3.0 Phase D). Časy jsou naive UTC jako všude; opakování v pražském čase.

    status: scheduled (čeká) → fired (jednorázová zazněla, čeká na hotovo/odložení) → done; kdykoli cancelled.
    Opakovaná zůstává scheduled a po zaznění se due_at posune na další výskyt (recurrence + weekdays +
    local_time v Europe/Prague). snoozed_until = odložený jednorázový výskyt opakované připomínky.
    """
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    note = Column(Text, nullable=True)
    due_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="scheduled", nullable=False)
    recurrence = Column(String(20), default="none", nullable=False)
    weekdays = Column(String(20), nullable=True)
    local_time = Column(String(5), nullable=True)
    snoozed_until = Column(DateTime, nullable=True)
    last_fired_at = Column(DateTime, nullable=True)
    fire_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_reminders_status_due", Reminder.status, Reminder.due_at)


class PushSubscription(Base):
    """Odběr Web Push jednoho prohlížeče/zařízení (Phase E). Endpoint je tajemství schopnosti – nelogovat."""
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    endpoint_hash = Column(String(64), nullable=False)  # sha256(endpoint) – unikátní klíč bez logování URL
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(200), nullable=False)
    auth = Column(String(100), nullable=False)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_success_at = Column(DateTime, nullable=True)
    disabled_at = Column(DateTime, nullable=True)  # push služba řekla 404/410 → už neposílat
    failure_count = Column(Integer, default=0, nullable=False)


Index("ix_push_subscriptions_endpoint_hash", PushSubscription.endpoint_hash, unique=True)


class Delivery(Base):
    """Externí doručení jedné notifikace jedním kanálem na jeden cíl (Phase E).

    status: pending (čeká / další pokus v next_attempt_at) → sending (rozpracováno) → sent | failed | skipped.
    dedupe_key = <dedupe notifikace>|<kanál>|<cíl> (unikátní) → výskyt připomínky nejvýš jednou na cíl.
    """
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, nullable=False)
    channel = Column(String(30), nullable=False)
    target_id = Column(Integer, nullable=True)
    dedupe_key = Column(String(250), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    next_attempt_at = Column(DateTime, nullable=False)
    last_attempt_at = Column(DateTime, nullable=True)
    last_error = Column(String(120), nullable=True)  # jen kategorie chyby, nikdy obsah / tajemství
    provider_message_id = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)


Index("ix_deliveries_dedupe_key", Delivery.dedupe_key, unique=True)
Index("ix_deliveries_status_next", Delivery.status, Delivery.next_attempt_at)
