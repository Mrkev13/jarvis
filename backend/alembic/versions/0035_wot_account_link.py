"""wot_account_link

MRK-105: automatické zdroje WoT z Wargaming API. Nová tabulka `wot_account_links` (propojený účet, zašifrovaný
access_token, platnost, stav) a nullable sloupce `wot_resources.source` / `updated_at` (odkud a kdy je hodnota).
Jen aditivní; downgrade tabulku i sloupce zahodí (token je jen kopie z přihlášení, hodnoty zdrojů zůstanou).

Revision ID: 0035_wot_account_link
Revises: 0034_wot_vehicle_mastery
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_wot_account_link"
down_revision = "0034_wot_vehicle_mastery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wot_resources", sa.Column("source", sa.String(length=20), nullable=True))
    op.add_column("wot_resources", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.create_table(
        "wot_account_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("token_enc", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("wot_account_links")
    op.drop_column("wot_resources", "updated_at")
    op.drop_column("wot_resources", "source")
