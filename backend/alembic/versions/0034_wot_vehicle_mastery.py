"""wot_vehicle_mastery

MRK-106: tabulka M-ek všech tanků z Wargaming API. Nová tabulka `wot_vehicle_mastery` (nejvyšší odznak mistrovství
u každého tanku) a nullable sloupec `wot_milestones.source` („api“ = první M tanku zjištěné synchronizací, čeká na
replay). Jen aditivní; downgrade tabulku a sloupec zahodí (snapshot je kopie z API, milníky zůstanou).

Revision ID: 0034_wot_vehicle_mastery
Revises: 0033_wow_collections
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_wot_vehicle_mastery"
down_revision = "0033_wow_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wot_milestones", sa.Column("source", sa.String(length=20), nullable=True))
    op.create_table(
        "wot_vehicle_mastery",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tank_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("short_name", sa.String(length=60), nullable=True),
        sa.Column("tag", sa.String(length=100), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("nation", sa.String(length=20), nullable=True),
        sa.Column("vehicle_type", sa.String(length=20), nullable=True),
        sa.Column("mark_of_mastery", sa.Integer(), nullable=False),
        sa.Column("battles", sa.Integer(), nullable=True),
        sa.Column("ace_detected_at", sa.DateTime(), nullable=True),
        sa.Column("ace_milestone_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ace_milestone_id"], ["wot_milestones.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tank_id"),
    )
    op.create_index("ix_wot_vehicle_mastery_id", "wot_vehicle_mastery", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wot_vehicle_mastery_id", table_name="wot_vehicle_mastery")
    op.drop_table("wot_vehicle_mastery")
    op.drop_column("wot_milestones", "source")
