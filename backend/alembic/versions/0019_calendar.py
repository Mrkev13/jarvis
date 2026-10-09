"""Calendar sources and durable imported events (MRK-30/MRK-31).

Revision ID: 0019_calendar
Revises: 0018_domain_events
"""
from alembic import op
import sqlalchemy as sa

revision = '0019_calendar'
down_revision = '0018_domain_events'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('calendar_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config_key', sa.String(20), nullable=True),
        sa.Column('timezone', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('config_key'),
        sa.CheckConstraint("kind = 'ics'", name='ck_calendar_sources_kind'))
    op.create_table('calendar_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('external_uid', sa.String(512), nullable=False),
        sa.Column('recurrence_id', sa.String(100), nullable=False),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('location', sa.String(500), nullable=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('all_day', sa.Boolean(), nullable=False),
        sa.Column('starts_on', sa.Date(), nullable=True),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('timezone', sa.String(80), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('rrule', sa.Text(), nullable=True),
        sa.Column('recurrence_metadata', sa.Text(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['source_id'], ['calendar_sources.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('source_id', 'external_uid', 'recurrence_id', name='uq_calendar_event_source_identity'),
        sa.CheckConstraint("status IN ('active', 'cancelled')", name='ck_calendar_events_status'),
        sa.CheckConstraint('ends_at >= starts_at', name='ck_calendar_events_interval'),
        sa.CheckConstraint('(all_day = false AND starts_on IS NULL AND ends_on IS NULL) OR '
                           '(all_day = true AND starts_on IS NOT NULL AND ends_on > starts_on)',
                           name='ck_calendar_events_all_day'))
    op.create_index('ix_calendar_events_source_id', 'calendar_events', ['source_id'])
    op.create_index('ix_calendar_events_starts_at', 'calendar_events', ['starts_at'])


def downgrade():
    op.drop_index('ix_calendar_events_starts_at', table_name='calendar_events')
    op.drop_index('ix_calendar_events_source_id', table_name='calendar_events')
    op.drop_table('calendar_events')
    op.drop_table('calendar_sources')
