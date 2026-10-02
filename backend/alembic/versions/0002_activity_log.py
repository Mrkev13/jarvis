"""activity_log

Revision ID: 0002_activity_log
Revises: 0001_initial_baseline
Create Date: 2026-09-26 00:00:02.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0002_activity_log"
down_revision = "0001_initial_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("area", sa.String(length=50), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("delta_json", sa.Text(), nullable=True),
        sa.Column("user_context", sa.String(length=100), nullable=True),
        sa.Column("dedupe_key", sa.String(length=180), nullable=True),
    )
    op.create_index("ix_activity_logs_id", "activity_logs", ["id"], unique=False)
    op.create_index(
        "ix_activity_area_timestamp",
        "activity_logs",
        ["area", sa.text("timestamp DESC")],
        unique=False,
    )
    op.create_index(
        "ix_activity_dedupe_key",
        "activity_logs",
        ["dedupe_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_activity_dedupe_key", table_name="activity_logs")
    op.drop_index("ix_activity_area_timestamp", table_name="activity_logs")
    op.drop_index("ix_activity_logs_id", table_name="activity_logs")
    op.drop_table("activity_logs")
