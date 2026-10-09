"""Calendar source presence (MRK-40): events absent from a complete feed snapshot.

Adds nullable `calendar_events.source_missing_at` (NULL = present in its source). Additive only: no row is changed,
deleted or hidden by the upgrade; downgrade drops the column.

Revision ID: 0020_calendar_source_presence
Revises: 0019_calendar
"""
from alembic import op
import sqlalchemy as sa

revision = '0020_calendar_source_presence'
down_revision = '0019_calendar'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('calendar_events') as batch:
        batch.add_column(sa.Column('source_missing_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('calendar_events') as batch:
        batch.drop_column('source_missing_at')
