"""memory_lifecycle

MRK-84: druh, platnost a vazba na nahrazenou vzpomínku. Aditivní, bez datových operací:
- `memories.kind` NOT NULL se server_default 'fact' – existující řádky dostanou 'fact' (backfill bez UPDATE);
- `memories.expires_at` (naive UTC, nullable) – vypršená vzpomínka se nedostane do promptu ani do vyhledávání;
- `memories.supersedes_id` (nullable, FK na memories.id, ON DELETE SET NULL) – příprava pro MRK-111.
Downgrade všechny tři sloupce odebere.

Revision ID: 0030_memory_lifecycle
Revises: 0029_attendance_schedule
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_memory_lifecycle"
down_revision = "0029_attendance_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=20), nullable=False, server_default="fact"))
        batch.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("supersedes_id", sa.Integer(),
                                   sa.ForeignKey("memories.id", name="fk_memories_supersedes_id", ondelete="SET NULL"),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("supersedes_id")
        batch.drop_column("expires_at")
        batch.drop_column("kind")
