"""pending_actions

Revision ID: 0003_pending_actions
Revises: 0002_activity_log
Create Date: 2026-09-26 00:00:03.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0003_pending_actions"
down_revision = "0002_activity_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("arguments", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_pending_actions_id", "pending_actions", ["id"], unique=False)
    op.create_index(
        "ix_pending_status_created",
        "pending_actions",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pending_status_created", table_name="pending_actions")
    op.drop_index("ix_pending_actions_id", table_name="pending_actions")
    op.drop_table("pending_actions")
