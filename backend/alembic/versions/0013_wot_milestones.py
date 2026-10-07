"""wot_milestones

Game Enrichment B: průběh a splnění grindů, historie splněných grindů, milníky WoT („Mko") se screenshoty.
Jen přidané sloupce a nové tabulky; žádná existující data se nemění (kromě doplnění xp_start u aktivních grindů,
aby šel ukázat průběh od teď).

Revision ID: 0013_wot_milestones
Revises: 0012_weekly_reviews
Create Date: 2026-10-07 00:00:13.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0013_wot_milestones"
down_revision = "0012_weekly_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wot_grinds") as batch:
        batch.add_column(sa.Column("xp_start", sa.Float(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
    # Průběh u stávajících aktivních grindů začíná teď (původní hodnota není známá – nic se nevymýšlí).
    op.execute("UPDATE wot_grinds SET xp_start = xp_remaining WHERE xp_start IS NULL AND (status IS NULL OR status <> 'completed')")

    op.create_table(
        "wot_grind_completions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grind_id", sa.Integer(), nullable=True),
        sa.Column("tank", sa.String(length=100), nullable=False),
        sa.Column("xp_start", sa.Float(), nullable=True),
        sa.Column("xp_remaining_before", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["grind_id"], ["wot_grinds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wot_grind_completions_id", "wot_grind_completions", ["id"], unique=False)
    op.create_index("ix_wot_grind_completions_grind_id", "wot_grind_completions", ["grind_id"], unique=False)
    op.create_index("ix_wot_grind_completions_completed_at", "wot_grind_completions", ["completed_at"], unique=False)

    op.create_table(
        "wot_milestones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("milestone_type", sa.String(length=30), nullable=False),
        sa.Column("mastery", sa.String(length=20), nullable=True),
        sa.Column("tank", sa.String(length=100), nullable=False),
        sa.Column("map_name", sa.String(length=100), nullable=True),
        sa.Column("played_on", sa.Date(), nullable=True),
        sa.Column("damage", sa.Integer(), nullable=True),
        sa.Column("assist", sa.Integer(), nullable=True),
        sa.Column("kills", sa.Integer(), nullable=True),
        sa.Column("base_xp", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wot_milestones_id", "wot_milestones", ["id"], unique=False)

    op.create_table(
        "wot_milestone_screenshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("milestone_id", sa.Integer(), nullable=False),
        sa.Column("stored_name", sa.String(length=80), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("caption", sa.String(length=300), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["milestone_id"], ["wot_milestones.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_name"),
    )
    op.create_index("ix_wot_milestone_screenshots_id", "wot_milestone_screenshots", ["id"], unique=False)
    op.create_index("ix_wot_milestone_screenshots_milestone_id", "wot_milestone_screenshots", ["milestone_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wot_milestone_screenshots_milestone_id", table_name="wot_milestone_screenshots")
    op.drop_index("ix_wot_milestone_screenshots_id", table_name="wot_milestone_screenshots")
    op.drop_table("wot_milestone_screenshots")
    op.drop_index("ix_wot_milestones_id", table_name="wot_milestones")
    op.drop_table("wot_milestones")
    op.drop_index("ix_wot_grind_completions_completed_at", table_name="wot_grind_completions")
    op.drop_index("ix_wot_grind_completions_grind_id", table_name="wot_grind_completions")
    op.drop_index("ix_wot_grind_completions_id", table_name="wot_grind_completions")
    op.drop_table("wot_grind_completions")
    with op.batch_alter_table("wot_grinds") as batch:
        batch.drop_column("started_at")
        batch.drop_column("xp_start")
