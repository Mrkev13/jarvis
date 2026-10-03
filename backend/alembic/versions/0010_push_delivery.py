"""push_delivery

Externí doručení připomínek (Roadmap 3.0 Phase E): `push_subscriptions` (Web Push odběry prohlížečů) a
`deliveries` (stav doručení notifikace kanálem na cíl, unikátní dedupe klíč). Jen nové tabulky.

Revision ID: 0010_push_delivery
Revises: 0009_reminders
Create Date: 2026-10-05 00:00:10.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0010_push_delivery"
down_revision = "0009_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_push_subscriptions_id", "push_subscriptions", ["id"], unique=False)
    op.create_index("ix_push_subscriptions_endpoint_hash", "push_subscriptions", ["endpoint_hash"], unique=True)
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=250), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deliveries_id", "deliveries", ["id"], unique=False)
    op.create_index("ix_deliveries_dedupe_key", "deliveries", ["dedupe_key"], unique=True)
    op.create_index("ix_deliveries_status_next", "deliveries", ["status", "next_attempt_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_deliveries_status_next", table_name="deliveries")
    op.drop_index("ix_deliveries_dedupe_key", table_name="deliveries")
    op.drop_index("ix_deliveries_id", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("ix_push_subscriptions_endpoint_hash", table_name="push_subscriptions")
    op.drop_index("ix_push_subscriptions_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
