from datetime import datetime
import json as _json
import re

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, TypeDecorator, UniqueConstraint
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
    """Účetní řádek Finance. MRK-61: nové sloupce (účet, datum zaúčtování, `amount_minor` + měna, kategorie, void…)
    jsou zdrojem pravdy; `amount` (Float) a `category` (text) jsou legacy zrcadlo, které drží
    `modules/finance/legacy_compat.py`, dokud je nečte nikdo starý (pozdější migrace je odstraní)."""
    __tablename__ = "finance_transactions"
    __table_args__ = (
        CheckConstraint("source IN ('manual', 'work_sync', 'import')", name="ck_finance_transactions_source"),
        CheckConstraint("direction IN ('in', 'out')", name="ck_finance_transactions_direction"),
        CheckConstraint("(direction = 'in' AND amount_minor >= 0) OR (direction = 'out' AND amount_minor <= 0)",
                        name="ck_finance_transactions_sign"),
        CheckConstraint("length(currency) = 3", name="ck_finance_transactions_currency"),
        UniqueConstraint("account_id", "txn_key", name="uq_finance_transactions_account_txn_key"),
        Index("ix_finance_transactions_account_booked", "account_id", "booked_on"),
        Index("ix_finance_transactions_booked_on", "booked_on"),
        Index("ix_finance_transactions_category_booked", "effective_category_id", "booked_on"),
        Index("ix_finance_transactions_fingerprint", "fingerprint"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # --- legacy (zrcadlo; nové čtení přes amount_minor / effective_category_id) ---
    amount = Column(Float, nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(String(255), default="")  # očištěný popis (bez čísel účtů)
    transaction_type = Column(String(20), nullable=False)  # income / expense
    created_at = Column(DateTime, default=datetime.utcnow)
    # --- identita a zdroj ---
    account_id = Column(Integer, ForeignKey("finance_accounts.id", ondelete="RESTRICT"), nullable=False)
    import_id = Column(Integer, ForeignKey("finance_imports.id", ondelete="RESTRICT"))
    source = Column(String(20), nullable=False)  # manual / work_sync / import
    # --- datum a částka ---
    booked_on = Column(Date, nullable=False)  # pražský den zaúčtování
    value_on = Column(Date)
    amount_minor = Column(BigInteger, nullable=False)  # haléře se znaménkem: minus = odchozí
    currency = Column(String(3), nullable=False)
    direction = Column(String(3), nullable=False)  # in / out
    # --- protistrana ---
    counterparty_name = Column(String(200))
    counterparty_account_masked = Column(String(40))
    counterparty_account_hash = Column(String(64))
    vs = Column(String(10))
    ks = Column(String(10))
    ss = Column(String(10))
    # --- deduplikace a metadata (MRK-62) ---
    txn_key = Column(String(128))
    fingerprint = Column(String(64))
    extra = Column(Text)  # JSON, jen allowlist polí adaptéru
    # --- kategorie ---
    system_category_id = Column(Integer, ForeignKey("finance_categories.id", ondelete="RESTRICT"))
    category_source = Column(String(20))  # legacy / manual / rule / none
    override_category_id = Column(Integer, ForeignKey("finance_categories.id", ondelete="RESTRICT"))
    effective_category_id = Column(Integer, ForeignKey("finance_categories.id", ondelete="RESTRICT"))
    # --- vazby a stavy ---
    transfer_link_id = Column(Integer, ForeignKey("finance_transactions.id", ondelete="RESTRICT"))
    review_flag = Column(Boolean, nullable=False, default=False)
    voided_at = Column(DateTime)  # MRK-61: místo DELETE; zrušený řádek se nepočítá, nehledá ani nenabízí
    void_reason = Column(String(200))
    search_text = Column(String(600))


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
    # Game Enrichment B: výchozí zbývající XP (základ pro průběh v %) a začátek grindu (pro délku).
    # NULL u grindů založených před 0013 → průběh se ukáže od momentu migrace / neznámá délka.
    xp_start = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)


class WotGrindCompletion(Base):
    """Splněný grind (Game Enrichment B) – trvalá historie, nezávislá na řádku grindu (ten se dá smazat / znovu
    založit). Zdroj pravdy pro budoucí událost `wot_grind_completed` (gamifikace ji jen čte)."""
    __tablename__ = "wot_grind_completions"

    id = Column(Integer, primary_key=True, index=True)
    grind_id = Column(Integer, ForeignKey("wot_grinds.id", ondelete="SET NULL"), nullable=True, index=True)
    tank = Column(String(100), nullable=False)
    xp_start = Column(Float, nullable=True)
    xp_remaining_before = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=False, index=True)
    source = Column(String(30), nullable=False, default="manual")


class WotMilestone(Base):
    """Herní milník WoT (Game Enrichment B) – zatím hlavně „Mko" (Ace Tanker). `milestone_type` nechává místo pro
    další druhy později; žádná obecná abstrakce."""
    __tablename__ = "wot_milestones"

    id = Column(Integer, primary_key=True, index=True)
    milestone_type = Column(String(30), nullable=False, default="mastery")
    mastery = Column(String(20), nullable=True)
    tank = Column(String(100), nullable=False)
    map_name = Column(String(100), nullable=True)
    played_on = Column(Date, nullable=True)
    damage = Column(Integer, nullable=True)
    assist = Column(Integer, nullable=True)
    kills = Column(Integer, nullable=True)
    base_xp = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    favorite = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    screenshots = relationship("WotMilestoneScreenshot", back_populates="milestone", cascade="all, delete-orphan",
                               order_by="WotMilestoneScreenshot.position")
    # Game Enrichment C: replaye odkazující na milník (bez kaskády – smazání milníku replay jen odpojí)
    replays = relationship("WotReplay", back_populates="milestone", passive_deletes=True)


class WotMilestoneScreenshot(Base):
    """Screenshot k milníku: metadata v DB, soubor v MEDIA_DIR pod serverovým názvem (nikdy původní název)."""
    __tablename__ = "wot_milestone_screenshots"

    id = Column(Integer, primary_key=True, index=True)
    milestone_id = Column(Integer, ForeignKey("wot_milestones.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_name = Column(String(80), nullable=False, unique=True)
    original_name = Column(String(255), nullable=True)
    content_type = Column(String(40), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    caption = Column(String(300), nullable=True)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    milestone = relationship("WotMilestone", back_populates="screenshots")


class WotReplay(Base):
    """Replay WoT v knihovně (Game Enrichment C): originální .wotreplay v MEDIA_DIR/wot-replays pod serverovým názvem,
    metadata v DB (z deterministického parseru hlavičky a/nebo ručně). Duplicitu hlídá SHA-256 obsahu.
    Volitelně propojený s jedním milníkem (Mko) – smazání jedné strany druhou nerozbije."""
    __tablename__ = "wot_replays"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=True)
    stored_filename = Column(String(80), nullable=False, unique=True)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, unique=True)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    played_at = Column(DateTime, nullable=True, index=True)
    tank_name = Column(String(100), nullable=True)
    tank_tag = Column(String(100), nullable=True)
    map_name = Column(String(100), nullable=True)
    damage = Column(Integer, nullable=True)
    assist = Column(Integer, nullable=True)
    kills = Column(Integer, nullable=True)
    base_xp = Column(Integer, nullable=True)
    mastery = Column(String(20), nullable=True)
    battle_result = Column(String(10), nullable=True)
    game_version = Column(String(40), nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(JsonAsText, nullable=True)
    favorite = Column(Boolean, nullable=False, default=False)
    parser_status = Column(String(20), nullable=False, default="unsupported")
    parser_version = Column(String(20), nullable=True)
    parser_warnings = Column(JsonAsText, nullable=True)
    linked_milestone_id = Column(Integer, ForeignKey("wot_milestones.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    milestone = relationship("WotMilestone", back_populates="replays")


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), default="")
    semester = Column(String(50), default="")
    credits = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    # MRK-86: stav zápočtu (NULL = nesplněn), jeho datum a volitelný limit povolených absencí
    credit_status = Column(String(20), nullable=True)  # pending | passed | failed
    credit_date = Column(Date, nullable=True)
    absence_limit = Column(Integer, nullable=True)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1000), default="")
    due_date = Column(Date, nullable=True)
    priority = Column(String(20), default="medium")
    status = Column(String(20), default="todo")
    # MRK-14: kdy byl úkol splněn (null = otevřený nebo starší data bez času)
    completed_at = Column(DateTime, nullable=True)

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
    # MRK-14: uzavření zkoušky a volitelný výsledek (žádná klasifikační kniha – jedna hodnota a její druh)
    completed_at = Column(DateTime, nullable=True)
    result_type = Column(String(20), nullable=True)  # percent | points | grade | pass_fail
    result_value = Column(String(40), nullable=True)

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
    sync_to_finance = Column(Boolean, default=False)  # MRK-60: jen historie; práce už Finance nezapisuje


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


class OffsiteBackupRun(Base):
    """MRK-57: one off-machine operation (restic backup of a verified local run, repository check or prune).
    Only allowlisted outcome codes - never credentials, repository URL, paths or raw tool output."""
    __tablename__ = "offsite_backup_runs"
    __table_args__ = (
        CheckConstraint("operation IN ('backup', 'check', 'prune')", name="ck_offsite_backup_runs_operation"),
        CheckConstraint("status IN ('running', 'success', 'failed')", name="ck_offsite_backup_runs_status"),
        Index("ix_offsite_backup_runs_operation_started", "operation", "started_at"),
        Index("ix_offsite_backup_runs_source_backup_id", "source_backup_id"),
    )
    id = Column(Integer, primary_key=True)
    operation = Column(String(10), nullable=False)
    status = Column(String(10), nullable=False)
    outcome = Column(String(40), nullable=True)
    source_backup_id = Column(Integer, nullable=True)  # BackupLog.id; no FK - local retention deletes old logs
    source_run = Column(String(64), nullable=True)  # local run id (timestamp), not a path
    snapshot_id = Column(String(64), nullable=True)
    files_new = Column(Integer, nullable=True)
    bytes_added = Column(BigInteger, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)


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


class DailyBriefing(Base):
    """Denní přehled (Roadmap 3.0 Phase F) – jeden řádek na pražský kalendářní den.

    status: generating → ready | failed. Přegenerování přepíše obsah stejného řádku (regenerated_count).
    Neukládá se prompt ani celý zdrojový snímek: jen hash, odkazy na zdroje (pro „co je nového") a výsledek.
    """
    __tablename__ = "daily_briefings"

    id = Column(Integer, primary_key=True, index=True)
    briefing_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False)
    trigger = Column(String(20), nullable=False)  # scheduler | catchup | manual
    attempts = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime, nullable=True)
    error_category = Column(String(60), nullable=True)
    content = Column(Text, nullable=True)  # validovaný JSON přehledu
    source_hash = Column(String(64), nullable=True)
    source_refs = Column(Text, nullable=True)  # JSON seznam „typ:id" ze snímku
    snapshot_tokens = Column(Integer, nullable=True)
    model = Column(String(100), nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    grounding_removed = Column(Integer, default=0, nullable=False)
    regenerated_count = Column(Integer, default=0, nullable=False)
    generated_at = Column(DateTime, nullable=True)
    first_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_daily_briefings_date", DailyBriefing.briefing_date, unique=True)


class WeeklyReview(Base):
    """Týdenní přehled (Roadmap 3.0 Phase G) – jeden řádek na pražský kalendářní týden (pondělí = week_start).

    `period_end` = okamžik (UTC), do kterého snímek data zahrnul (neděle 19:00 nebo konec týdne při catch-upu).
    status: generating → ready | failed. Přegenerování přepíše obsah stejného řádku (regenerated_count).
    Neukládá se prompt ani celý snímek – jen hash snímku a validovaný výsledek.
    """
    __tablename__ = "weekly_reviews"

    id = Column(Integer, primary_key=True, index=True)
    week_start = Column(Date, nullable=False)
    period_end = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False)
    trigger = Column(String(20), nullable=False)  # scheduler | catchup | retry | manual
    attempts = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime, nullable=True)
    error_category = Column(String(60), nullable=True)
    content = Column(Text, nullable=True)  # validovaný JSON přehledu
    snapshot_hash = Column(String(64), nullable=True)
    snapshot_tokens = Column(Integer, nullable=True)
    model = Column(String(100), nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    grounding_fixes = Column(Integer, default=0, nullable=False)
    regenerated_count = Column(Integer, default=0, nullable=False)
    generated_at = Column(DateTime, nullable=True)
    first_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


Index("ix_weekly_reviews_week_start", WeeklyReview.week_start, unique=True)


class ModuleSetting(Base):
    """MRK-18 A2: uložená volba zapnutí modulu (Nastavení). Jen explicitní odchylky od výchozího stavu –
    řádek = override; návrat na výchozí hodnotu řádek maže. Proměnná prostředí má vždy přednost."""
    __tablename__ = "module_settings"

    module_id = Column(String(50), primary_key=True)
    enabled = Column(Boolean, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class UiPreference(Base):
    """MRK-78: nastavení vzhledu sdílená mezi zařízeními (rozložení Řídicího centra). Klíč z allowlistu
    (`ui_preferences.KEYS`), hodnota = ověřený JSON bez osobních dat (jen id widgetů, pořadí, velikosti)."""
    __tablename__ = "ui_preferences"

    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------- modely modulů v balíčcích modules/<id>/ (Platform 2.0) ----------
# Jeden řádek na modul: registrace tabulek do Base pro Alembic, create_all v testech a kontrolu driftu schématu.
from modules.habits.models import Habit, HabitEntry  # noqa: E402

from modules.calendar.models import CalendarSource, CalendarEvent  # noqa: E402

from modules.school.models import SchoolAttendance, StudyCourse, StudyMaterial  # noqa: E402
from modules.fitness.models import Exercise, WorkoutSession, WorkoutSet, RehabExercise, RehabSession, RehabEntry  # noqa: E402
from modules.finance.models import (  # noqa: E402
    FinanceAccount, FinanceCategory, FinanceImport, FinanceImportIssue, FinanceRule, FinanceTransactionRevision,
)
from modules.finance.legacy_compat import install_legacy_compat  # noqa: E402

install_legacy_compat(FinanceTransaction)

MODULE_MODELS = (Habit, HabitEntry, CalendarSource, CalendarEvent, StudyCourse, StudyMaterial, SchoolAttendance, Exercise, WorkoutSession, WorkoutSet, RehabExercise, RehabSession, RehabEntry,
                 FinanceAccount, FinanceCategory, FinanceImport, FinanceImportIssue, FinanceRule, FinanceTransactionRevision)


class DomainEvent(Base):
    """MRK-19: doménová událost (transakční outbox). Zapisuje se VE STEJNÉ transakci jako business změna
    (`domain_events.append_domain_event`). Append-only; aplikace řádky nemění. Konečná přenosová historie
    (retence 180 dní) – trvalá historie zůstává v Aktivitě a business tabulkách (docs/domain-events.md)."""
    __tablename__ = "domain_events"
    __table_args__ = {"sqlite_autoincrement": True}  # id se po retenci nikdy nepoužije znovu (dedupe event:<id>)

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False, index=True)
    aggregate_type = Column(String(50), nullable=False)
    aggregate_id = Column(String(64), nullable=True)
    module_id = Column(String(50), nullable=True, index=True)  # None = jádro (system.*)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
