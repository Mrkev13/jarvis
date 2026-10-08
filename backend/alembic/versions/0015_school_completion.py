"""school_completion

MRK-14: dokončení úkolů a uzavření zkoušek ve Škole. Jen přidané nullable sloupce – stávající data se nemění
(starší hotové položky prostě nemají čas dokončení).

Revision ID: 0015_school_completion
Revises: 0014_wot_replays
Create Date: 2026-10-07 00:00:15.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0015_school_completion"
down_revision = "0014_wot_replays"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("exams") as batch:
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("result_type", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("result_value", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("exams") as batch:
        batch.drop_column("result_value")
        batch.drop_column("result_type")
        batch.drop_column("completed_at")
    with op.batch_alter_table("assignments") as batch:
        batch.drop_column("completed_at")
