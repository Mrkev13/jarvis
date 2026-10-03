"""reminders

Připomínky (Roadmap 3.0 Phase D): nová tabulka `reminders`, existující data se nemění.
Časy naive UTC (jako ostatní tabulky); opakování se počítá v Europe/Prague z `local_time` + `weekdays`.

Revision ID: 0009_reminders
Revises: 0008_conversation_summary
Create Date: 2026-10-04 00:00:09.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0009_reminders"
down_revision = "0008_conversation_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("recurrence", sa.String(length=20), nullable=False),
        sa.Column("weekdays", sa.String(length=20), nullable=True),
        sa.Column("local_time", sa.String(length=5), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("fire_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminders_id", "reminders", ["id"], unique=False)
    op.create_index("ix_reminders_status_due", "reminders", ["status", "due_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reminders_status_due", table_name="reminders")
    op.drop_index("ix_reminders_id", table_name="reminders")
    op.drop_table("reminders")
