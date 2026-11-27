"""wot_stats_snapshots

MRK-153: statistiky WoT po bitvách. Nové tabulky `wot_tank_snapshots` (kumulativní statistiky tanku v čase, řádek
jen při změně) a `wot_account_snapshots` (osobní hodnocení / zdroje v čase). Jen aditivní; downgrade tabulky zahodí
(jde o historii kopií z Wargaming API, aktuální stav se nemění).

Revision ID: 0036_wot_stats_snapshots
Revises: 0035_wot_account_link
"""
from alembic import op
import sqlalchemy as sa

revision = "0036_wot_stats_snapshots"
down_revision = "0035_wot_account_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wot_tank_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tank_id", sa.Integer(), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("battles", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=True),
        sa.Column("damage", sa.BigInteger(), nullable=True),
        sa.Column("frags", sa.Integer(), nullable=True),
        sa.Column("xp", sa.BigInteger(), nullable=True),
        sa.Column("survived", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wot_tank_snapshots_tank_taken", "wot_tank_snapshots", ["tank_id", "taken_at"], unique=False)
    op.create_index("ix_wot_tank_snapshots_taken", "wot_tank_snapshots", ["taken_at"], unique=False)
    op.create_table(
        "wot_account_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("global_rating", sa.Integer(), nullable=True),
        sa.Column("battles", sa.Integer(), nullable=True),
        sa.Column("credits", sa.BigInteger(), nullable=True),
        sa.Column("gold", sa.BigInteger(), nullable=True),
        sa.Column("free_xp", sa.BigInteger(), nullable=True),
        sa.Column("bonds", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wot_account_snapshots_kind_taken", "wot_account_snapshots", ["kind", "taken_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wot_account_snapshots_kind_taken", table_name="wot_account_snapshots")
    op.drop_table("wot_account_snapshots")
    op.drop_index("ix_wot_tank_snapshots_taken", table_name="wot_tank_snapshots")
    op.drop_index("ix_wot_tank_snapshots_tank_taken", table_name="wot_tank_snapshots")
    op.drop_table("wot_tank_snapshots")
