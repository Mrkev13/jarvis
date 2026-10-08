"""domain_events

MRK-19: transakční outbox doménových událostí. Jen nová tabulka (append-only); stávající data se nemění.
Retence (výchozí 180 dní) maže jen tuto přenosovou historii – Aktivita a business tabulky zůstávají.

Revision ID: 0018_domain_events
Revises: 0017_habits
Create Date: 2026-10-08 00:00:18.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0018_domain_events"
down_revision = "0017_habits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=True),
        sa.Column("module_id", sa.String(length=50), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_domain_events_event_type", "domain_events", ["event_type"])
    op.create_index("ix_domain_events_module_id", "domain_events", ["module_id"])
    op.create_index("ix_domain_events_occurred_at", "domain_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_domain_events_occurred_at", table_name="domain_events")
    op.drop_index("ix_domain_events_module_id", table_name="domain_events")
    op.drop_index("ix_domain_events_event_type", table_name="domain_events")
    op.drop_table("domain_events")
