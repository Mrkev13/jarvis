"""wot_replays

Game Enrichment C: knihovna replayů WoT. Jen nová tabulka (soubor na disku v MEDIA_DIR/wot-replays, metadata zde);
žádná existující data se nemění.

Revision ID: 0014_wot_replays
Revises: 0013_wot_milestones
Create Date: 2026-10-07 00:00:14.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0014_wot_replays"
down_revision = "0013_wot_milestones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wot_replays",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("stored_filename", sa.String(length=80), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("played_at", sa.DateTime(), nullable=True),
        sa.Column("tank_name", sa.String(length=100), nullable=True),
        sa.Column("tank_tag", sa.String(length=100), nullable=True),
        sa.Column("map_name", sa.String(length=100), nullable=True),
        sa.Column("damage", sa.Integer(), nullable=True),
        sa.Column("assist", sa.Integer(), nullable=True),
        sa.Column("kills", sa.Integer(), nullable=True),
        sa.Column("base_xp", sa.Integer(), nullable=True),
        sa.Column("mastery", sa.String(length=20), nullable=True),
        sa.Column("battle_result", sa.String(length=10), nullable=True),
        sa.Column("game_version", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("parser_status", sa.String(length=20), nullable=False),
        sa.Column("parser_version", sa.String(length=20), nullable=True),
        sa.Column("parser_warnings", sa.Text(), nullable=True),
        sa.Column("linked_milestone_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["linked_milestone_id"], ["wot_milestones.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index("ix_wot_replays_id", "wot_replays", ["id"], unique=False)
    op.create_index("ix_wot_replays_uploaded_at", "wot_replays", ["uploaded_at"], unique=False)
    op.create_index("ix_wot_replays_played_at", "wot_replays", ["played_at"], unique=False)
    op.create_index("ix_wot_replays_linked_milestone_id", "wot_replays", ["linked_milestone_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wot_replays_linked_milestone_id", table_name="wot_replays")
    op.drop_index("ix_wot_replays_played_at", table_name="wot_replays")
    op.drop_index("ix_wot_replays_uploaded_at", table_name="wot_replays")
    op.drop_index("ix_wot_replays_id", table_name="wot_replays")
    op.drop_table("wot_replays")
