"""auth_sessions

Revision ID: 0006_auth_sessions
Revises: 0005_backup_log
Create Date: 2026-09-26 00:00:06.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0006_auth_sessions"
down_revision = "0005_backup_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("token_hash", sa.String(length=256), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("revoked", sa.Boolean(), default=False, nullable=True),
    )
    op.create_index("ix_auth_sessions_id", "auth_sessions", ["id"], unique=False)
    op.create_index(
        "ix_auth_token_hash",
        "auth_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_auth_expires_at",
        "auth_sessions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
