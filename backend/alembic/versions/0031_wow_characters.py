"""wow_characters

MRK-127: World of Warcraft – sledované postavy se snapshotem z Blizzard API. Jen nová tabulka, nic existujícího se
nemění. Downgrade tabulku odebere (data jsou jen kopie z API + cílové levely).

Revision ID: 0031_wow_characters
Revises: 0030_memory_lifecycle
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_wow_characters"
down_revision = "0030_memory_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wow_characters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=24), nullable=False),
        sa.Column("name_key", sa.String(length=24), nullable=False),
        sa.Column("realm_slug", sa.String(length=64), nullable=False),
        sa.Column("realm_name", sa.String(length=64), nullable=True),
        sa.Column("target_level", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("class_name", sa.String(length=40), nullable=True),
        sa.Column("race_name", sa.String(length=40), nullable=True),
        sa.Column("faction", sa.String(length=20), nullable=True),
        sa.Column("active_spec", sa.String(length=40), nullable=True),
        sa.Column("item_level", sa.Integer(), nullable=True),
        sa.Column("professions_json", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("sync_status", sa.String(length=20), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("sync_status IN ('pending', 'ok', 'not_found', 'error')", name="ck_wow_characters_sync_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("realm_slug", "name_key", name="uq_wow_characters_realm_name"),
    )
    op.create_index(op.f("ix_wow_characters_id"), "wow_characters", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_wow_characters_id"), table_name="wow_characters")
    op.drop_table("wow_characters")
