"""Off-machine (restic → Backblaze B2) backup attempts: backup / check / prune history for /health (MRK-57).

Additive only. No FK to backup_logs: local retention deletes old BackupLog rows, the off-site history stays.
Never stores credentials, repository URLs, paths or raw tool output - only allowlisted outcome codes.
"""
from alembic import op
import sqlalchemy as sa

revision = '0024_offsite_backup_runs'
down_revision = '0023_study_course_export_source'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('offsite_backup_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(10), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('outcome', sa.String(40), nullable=True),
        sa.Column('source_backup_id', sa.Integer(), nullable=True),
        sa.Column('source_run', sa.String(64), nullable=True),
        sa.Column('snapshot_id', sa.String(64), nullable=True),
        sa.Column('files_new', sa.Integer(), nullable=True),
        sa.Column('bytes_added', sa.BigInteger(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.CheckConstraint("operation IN ('backup', 'check', 'prune')", name='ck_offsite_backup_runs_operation'),
        sa.CheckConstraint("status IN ('running', 'success', 'failed')", name='ck_offsite_backup_runs_status'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_offsite_backup_runs_operation_started', 'offsite_backup_runs', ['operation', 'started_at'])
    op.create_index('ix_offsite_backup_runs_source_backup_id', 'offsite_backup_runs', ['source_backup_id'])


def downgrade():
    op.drop_index('ix_offsite_backup_runs_source_backup_id', table_name='offsite_backup_runs')
    op.drop_index('ix_offsite_backup_runs_operation_started', table_name='offsite_backup_runs')
    op.drop_table('offsite_backup_runs')
