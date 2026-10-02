"""conversation_summary

Průběžné shrnutí dlouhých konverzací (Roadmap 3.0 A4): `conversations.summary` drží shrnutí starší
historie a `conversations.summarized_until_message_id` ID poslední zprávy, která je v něm zahrnutá
(inkrementální posun – stejné zprávy se neshrnují znovu). Oba sloupce nullable, bez backfillu.

Revision ID: 0008_conversation_summary
Revises: 0007_reconcile_schema_drift
Create Date: 2026-10-03 00:00:08.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0008_conversation_summary"
down_revision = "0007_reconcile_schema_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("summarized_until_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("summarized_until_message_id")
        batch.drop_column("summary")
