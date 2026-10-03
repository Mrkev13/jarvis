"""daily_briefings

Denní přehled (Roadmap 3.0 Phase F): tabulka `daily_briefings`, jeden řádek na pražský den (unikátní
`briefing_date`). Jen nová tabulka.

Revision ID: 0011_daily_briefings
Revises: 0010_push_delivery
Create Date: 2026-10-06 00:00:11.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0011_daily_briefings"
down_revision = "0010_push_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("error_category", sa.String(length=60), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("source_refs", sa.Text(), nullable=True),
        sa.Column("snapshot_tokens", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("grounding_removed", sa.Integer(), nullable=False),
        sa.Column("regenerated_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("first_generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_briefings_id", "daily_briefings", ["id"], unique=False)
    op.create_index("ix_daily_briefings_date", "daily_briefings", ["briefing_date"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_daily_briefings_date", table_name="daily_briefings")
    op.drop_index("ix_daily_briefings_id", table_name="daily_briefings")
    op.drop_table("daily_briefings")
