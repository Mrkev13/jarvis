"""Study materials (MRK-42): Moodle courses and their discovered files.

Two new tables, nothing existing is touched. `study_courses.subject_id` is a manual, nullable mapping to
`subjects` (SET NULL on subject deletion). Downgrade drops both tables (stored binaries in MEDIA_DIR stay on disk).

Revision ID: 0021_study_materials
Revises: 0020_calendar_source_presence
"""
from alembic import op
import sqlalchemy as sa

revision = '0021_study_materials'
down_revision = '0020_calendar_source_presence'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('study_courses',
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
        sa.CheckConstraint("source = 'moodle'", name='ck_study_courses_source'))
    op.create_index('ix_study_courses_subject_id', 'study_courses', ['subject_id'])
    op.create_table('study_materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(512), nullable=False),
        sa.Column('module_external_id', sa.String(32), nullable=False),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('section_name', sa.String(300), nullable=True),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('material_type', sa.String(10), nullable=False),
        sa.Column('mime_type', sa.String(120), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('source_modified_at', sa.DateTime(), nullable=True),
        sa.Column('download_status', sa.String(20), nullable=False),
        sa.Column('stored_name', sa.String(80), nullable=True),
        sa.Column('checksum', sa.String(64), nullable=True),
        sa.Column('stored_size', sa.BigInteger(), nullable=True),
        sa.Column('extraction_status', sa.String(20), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('extracted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('source_missing_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['course_id'], ['study_courses.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('course_id', 'external_id', name='uq_study_materials_course_identity'),
        sa.CheckConstraint("material_type IN ('pdf', 'pptx', 'docx', 'txt', 'other')", name='ck_study_materials_type'),
        sa.CheckConstraint("download_status IN ('stored', 'metadata_only', 'too_large', 'unsupported', 'rejected', 'failed')",
                           name='ck_study_materials_download_status'),
        sa.CheckConstraint("extraction_status IS NULL OR extraction_status IN ('ok', 'empty', 'truncated', 'failed', 'unsupported')",
                           name='ck_study_materials_extraction_status'))
    op.create_index('ix_study_materials_course_id', 'study_materials', ['course_id'])


def downgrade():
    op.drop_index('ix_study_materials_course_id', table_name='study_materials')
    op.drop_table('study_materials')
    op.drop_index('ix_study_courses_subject_id', table_name='study_courses')
    op.drop_table('study_courses')
