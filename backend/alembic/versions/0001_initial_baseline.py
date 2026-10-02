"""baseline_existing_schema

Revision ID: 0001_initial_baseline
Revises: 
Create Date: 2026-09-26 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wot_resources",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("resource", sa.String(length=100), unique=True, nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
    )
    op.create_index("ix_wot_resources_id", "wot_resources", ["id"], unique=False)

    op.create_table(
        "wot_grinds",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tank", sa.String(length=100), unique=True, nullable=False),
        sa.Column("xp_remaining", sa.Float(), default=0, nullable=True),
        sa.Column("priority", sa.String(length=20), default="medium", nullable=True),
        sa.Column("status", sa.String(length=20), default="active", nullable=True),
    )
    op.create_index("ix_wot_grinds_id", "wot_grinds", ["id"], unique=False)

    op.create_table(
        "finance_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), default="", nullable=True),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_finance_transactions_id", "finance_transactions", ["id"], unique=False)

    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=50), default="", nullable=True),
        sa.Column("semester", sa.String(length=50), default="", nullable=True),
        sa.Column("credits", sa.Integer(), default=0, nullable=True),
        sa.Column("active", sa.Boolean(), default=True, nullable=True),
    )
    op.create_index("ix_subjects_id", "subjects", ["id"], unique=False)

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), default="", nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=20), default="medium", nullable=True),
        sa.Column("status", sa.String(length=20), default="todo", nullable=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
    )
    op.create_index("ix_assignments_id", "assignments", ["id"], unique=False)

    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("exam_type", sa.String(length=50), default="exam", nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), default="upcoming", nullable=True),
        sa.Column("notes", sa.String(length=1000), default="", nullable=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
    )
    op.create_index("ix_exams_id", "exams", ["id"], unique=False)

    op.create_table(
        "work_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Float(), nullable=False),
        sa.Column("project", sa.String(length=150), default="", nullable=True),
        sa.Column("description", sa.String(length=500), default="", nullable=True),
        sa.Column("hourly_rate", sa.Float(), default=0, nullable=True),
        sa.Column("finance_transaction_id", sa.Integer(), sa.ForeignKey("finance_transactions.id"), nullable=True),
        sa.Column("sync_to_finance", sa.Boolean(), default=True, nullable=True),
    )
    op.create_index("ix_work_sessions_id", "work_sessions", ["id"], unique=False)

    op.create_table(
        "mff_characters",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=100), unique=True, nullable=False),
        sa.Column("tier", sa.String(length=20), default="T3", nullable=True),
        sa.Column("level", sa.Integer(), default=80, nullable=True),
        sa.Column("uniform", sa.String(length=150), default="", nullable=True),
        sa.Column("ctp", sa.String(length=100), default="", nullable=True),
        sa.Column("artifact", sa.String(length=100), default="", nullable=True),
        sa.Column("priority", sa.String(length=20), default="medium", nullable=True),
        sa.Column("status", sa.String(length=30), default="built", nullable=True),
        sa.Column("notes", sa.String(length=1000), default="", nullable=True),
        sa.Column("role", sa.String(length=150), default="", nullable=True),
        sa.Column("team", sa.String(length=255), default="", nullable=True),
        sa.Column("uru_state", sa.String(length=60), default="", nullable=True),
        sa.Column("iso8_set", sa.String(length=100), default="", nullable=True),
        sa.Column("build_completeness", sa.Integer(), default=0, nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("roles", sa.Text(), default="[]", nullable=True),
        sa.Column("team_supports", sa.String(length=255), default="", nullable=True),
        sa.Column("uru_slots_total", sa.Integer(), default=20, nullable=True),
        sa.Column("uru_slots_filled", sa.Integer(), default=0, nullable=True),
        sa.Column("odin_blessings_count", sa.Integer(), default=0, nullable=True),
    )
    op.create_index("ix_mff_characters_id", "mff_characters", ["id"], unique=False)
    op.create_index("ix_mff_characters_tier", "mff_characters", ["tier"], unique=False)
    op.create_index("ix_mff_characters_priority", "mff_characters", ["priority"], unique=False)
    op.create_index("ix_mff_characters_status", "mff_characters", ["status"], unique=False)
    op.create_index("ix_mff_characters_build_completeness", "mff_characters", ["build_completeness"], unique=False)

    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("area", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), default="", nullable=True),
        sa.Column("status", sa.String(length=50), default="active", nullable=True),
        sa.Column("priority", sa.String(length=20), default="medium", nullable=True),
        sa.Column("progress", sa.Integer(), default=0, nullable=True),
        sa.Column("tracking_type", sa.String(length=50), default="manual", nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_goals_id", "goals", ["id"], unique=False)

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("area", sa.String(length=50), default="general", nullable=True),
        sa.Column("category", sa.String(length=50), default="context", nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), default=5, nullable=True),
        sa.Column("active", sa.Boolean(), default=True, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_memories_id", "memories", ["id"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=255), default="Nový chat", nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("area", sa.String(length=50), default="general", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), default="info", nullable=False),
        sa.Column("read", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=150), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=False),
        sa.Column("resolved", sa.Boolean(), default=False, nullable=False),
        sa.Column("action_url", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_notifications_id", "notifications", ["id"], unique=False)
    op.create_index("ix_notifications_read", "notifications", ["read"], unique=False)
    op.create_index("ix_notifications_resolved", "notifications", ["resolved"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_dedupe_key", "notifications", ["dedupe_key"], unique=False)

    op.create_table(
        "goal_progress_history",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "goal_id",
            sa.Integer(),
            sa.ForeignKey("goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), default=0, nullable=False),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_goal_progress_history_id", "goal_progress_history", ["id"], unique=False)
    op.create_index("ix_goal_progress_history_goal_id", "goal_progress_history", ["goal_id"], unique=False)
    op.create_index("ix_goal_progress_history_recorded_at", "goal_progress_history", ["recorded_at"], unique=False)

    op.create_table(
        "planner_recommendation_history",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("area", sa.String(length=50), default="general", nullable=False),
        sa.Column("recommendation_key", sa.String(length=180), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_planner_recommendation_history_id", "planner_recommendation_history", ["id"], unique=False)
    op.create_index("ix_planner_recommendation_history_mode", "planner_recommendation_history", ["mode"], unique=False)
    op.create_index("ix_planner_recommendation_history_recommendation_key", "planner_recommendation_history", ["recommendation_key"], unique=False)
    op.create_index("ix_planner_recommendation_history_created_at", "planner_recommendation_history", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("planner_recommendation_history")
    op.drop_table("goal_progress_history")
    op.drop_table("notifications")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("memories")
    op.drop_table("goals")
    op.drop_table("mff_characters")
    op.drop_table("work_sessions")
    op.drop_table("exams")
    op.drop_table("assignments")
    op.drop_table("subjects")
    op.drop_table("finance_transactions")
    op.drop_table("wot_grinds")
    op.drop_table("wot_resources")
