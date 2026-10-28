"""UI preferences shared across devices (MRK-78): the Control Center layout.

Additive: new table `ui_preferences` (allowlisted key → validated JSON). No existing row changes; downgrade drops the
table (the browser keeps its local copy of the layout, so nothing the user sees is lost).

Revision ID: 0027_ui_preferences
Revises: 0026_calendar_event_course_ref
"""
from alembic import op
import sqlalchemy as sa

revision = '0027_ui_preferences'
down_revision = '0026_calendar_event_course_ref'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ui_preferences',
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade():
    op.drop_table('ui_preferences')
