"""weekly_reviews

Týdenní přehled (Roadmap 3.0 Phase G): tabulka `weekly_reviews`, jeden řádek na pražský kalendářní týden
(unikátní `week_start` = pondělí). Jen nová tabulka.

Revision ID: 0012_weekly_reviews
Revises: 0011_daily_briefings
Create Date: 2026-10-12 00:00:12.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0012_weekly_reviews"
down_revision = "0011_daily_briefings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("error_category", sa.String(length=60), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot_tokens", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("grounding_fixes", sa.Integer(), nullable=False),
        sa.Column("regenerated_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("first_generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_weekly_reviews_id", "weekly_reviews", ["id"], unique=False)
    op.create_index("ix_weekly_reviews_week_start", "weekly_reviews", ["week_start"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_weekly_reviews_week_start", table_name="weekly_reviews")
    op.drop_index("ix_weekly_reviews_id", table_name="weekly_reviews")
    op.drop_table("weekly_reviews")
