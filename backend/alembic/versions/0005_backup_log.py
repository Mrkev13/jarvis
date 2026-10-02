"""backup_log

Revision ID: 0005_backup_log
Revises: 0004_goals_sources
Create Date: 2026-09-26 00:00:05.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0005_backup_log"
down_revision = "0004_goals_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retention_days", sa.Integer(), default=30, nullable=True),
    )
    op.create_index("ix_backup_logs_id", "backup_logs", ["id"], unique=False)
    op.create_index(
        "ix_backup_started_at",
        "backup_logs",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_backup_started_at", table_name="backup_logs")
    op.drop_index("ix_backup_logs_id", table_name="backup_logs")
    op.drop_table("backup_logs")
