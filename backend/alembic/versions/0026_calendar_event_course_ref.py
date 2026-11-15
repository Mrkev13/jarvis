"""Moodle course reference on calendar events (MRK-76).

Additive: nullable `calendar_events.course_ref` holds the ICS `CATEGORIES` value (Moodle puts the course short name
there). It links an event to a school subject through `study_courses.short_name` → `subject_id` at read time; nothing
is matched or stored here. Existing rows stay NULL until the next sync fills them.

Revision ID: 0026_calendar_event_course_ref
Revises: 0025_finance_ledger
"""
from alembic import op
import sqlalchemy as sa

revision = '0026_calendar_event_course_ref'
down_revision = '0025_finance_ledger'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('calendar_events') as batch:
        batch.add_column(sa.Column('course_ref', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('calendar_events') as batch:
        batch.drop_column('course_ref')
