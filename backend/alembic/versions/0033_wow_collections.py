"""wow_collections

MRK-128: WoW sbírky – denní snapshot počtů (mounti, pets, achievementy) a seznam „chci získat“. Dvě nové tabulky,
nic existujícího se nemění; downgrade je zahodí (snapshoty jsou kopie z API, seznam přání je jediná ruční data).

Revision ID: 0033_wow_collections
Revises: 0032_wow_character_media
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_wow_collections"
down_revision = "0032_wow_character_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wow_collection_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("mounts", sa.Integer(), nullable=True),
        sa.Column("pets", sa.Integer(), nullable=True),
        sa.Column("achievements", sa.Integer(), nullable=True),
        sa.Column("achievement_points", sa.Integer(), nullable=True),
        sa.Column("source_character_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", name="uq_wow_collection_snapshots_day"),
    )
    op.create_index(op.f("ix_wow_collection_snapshots_id"), "wow_collection_snapshots", ["id"], unique=False)
    op.create_table(
        "wow_wishes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=120), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('mount', 'pet', 'achievement')", name="ck_wow_wishes_kind"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name_key", name="uq_wow_wishes_kind_name"),
    )
    op.create_index(op.f("ix_wow_wishes_id"), "wow_wishes", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_wow_wishes_id"), table_name="wow_wishes")
    op.drop_table("wow_wishes")
    op.drop_index(op.f("ix_wow_collection_snapshots_id"), table_name="wow_collection_snapshots")
    op.drop_table("wow_collection_snapshots")
