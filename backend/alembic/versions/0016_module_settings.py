"""module_settings

MRK-18 A2: uložené volby zapnutí modulů (Nastavení → Moduly). Jen nová tabulka – data modulů se nemění.
Řádek existuje pouze pro modul, jehož stav se liší od výchozího (manifest); prostředí má přednost.

Revision ID: 0016_module_settings
Revises: 0015_school_completion
Create Date: 2026-10-08 00:00:16.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0016_module_settings"
down_revision = "0015_school_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_settings",
        sa.Column("module_id", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("module_id"),
    )


def downgrade() -> None:
    op.drop_table("module_settings")
