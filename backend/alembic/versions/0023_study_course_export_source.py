"""Study courses may also come from an official Moodle course ZIP export (MRK-56).

Only the CHECK constraint on `study_courses.source` changes: `'moodle'` (Web Services, MRK-42) or `'moodle_export'`
(„Stáhnout obsah kurzu" ZIP). Export identities live under their own source because the export's folder numbers are
not Moodle API ids. No data changes; downgrade refuses while export rows exist rather than deleting them.

Revision ID: 0023_study_course_export_source
Revises: 0022_fitness
"""
from alembic import op
import sqlalchemy as sa

revision = '0023_study_course_export_source'
down_revision = '0022_fitness'
branch_labels = None
depends_on = None

OLD_CHECK = "source = 'moodle'"
NEW_CHECK = "source IN ('moodle', 'moodle_export')"


def _courses(check: str) -> sa.Table:
    """Exact current table shape for SQLite batch recreation (constraints/indexes are not reliably reflected)."""
    return sa.Table(
        'study_courses', sa.MetaData(),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('external_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('short_name', sa.String(100), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('source', 'external_id', name='uq_study_courses_source_identity'),
        sa.CheckConstraint(check, name='ck_study_courses_source'),
        sa.Index('ix_study_courses_subject_id', 'subject_id'),
    )


def upgrade():
    with op.batch_alter_table('study_courses', copy_from=_courses(OLD_CHECK)) as batch:
        batch.drop_constraint('ck_study_courses_source', type_='check')
        batch.create_check_constraint('ck_study_courses_source', NEW_CHECK)


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM study_courses WHERE source <> 'moodle'")).scalar():
        raise RuntimeError('study_courses contains ZIP-export courses; remove them deliberately before downgrading')
    with op.batch_alter_table('study_courses', copy_from=_courses(NEW_CHECK)) as batch:
        batch.drop_constraint('ck_study_courses_source', type_='check')
        batch.create_check_constraint('ck_study_courses_source', OLD_CHECK)
