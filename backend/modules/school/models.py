"""Study materials (MRK-42): Moodle courses and the files discovered in them.

Times are naive UTC (`time_utils.utc_now()`), like the rest of the School data. The stored binary is the
authoritative copy; `extracted_text` is derived from it and may be rebuilt. Rows are never deleted by a sync:
an identity absent from a complete course snapshot gets `source_missing_at`, and the same row is restored when it
reappears. No upstream URL, token or private link is stored anywhere.
"""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from database import Base
from time_utils import utc_now

MATERIAL_TYPES = ('pdf', 'pptx', 'docx', 'txt', 'other')
# stored = binary in local storage; the rest are metadata-only outcomes (never an executable or unknown blob)
DOWNLOAD_STATUSES = ('stored', 'metadata_only', 'too_large', 'unsupported', 'rejected', 'failed')
EXTRACTION_STATUSES = ('ok', 'empty', 'truncated', 'failed', 'unsupported')


class StudyCourse(Base):
    __tablename__ = 'study_courses'
    __table_args__ = (
        UniqueConstraint('source', 'external_id', name='uq_study_courses_source_identity'),
        # 'moodle' = Web Services sync (MRK-42); 'moodle_export' = official course ZIP export (MRK-56) – its folder
        # numbers are not Moodle API ids, so the two sources never share an identity
        CheckConstraint("source IN ('moodle', 'moodle_export')", name='ck_study_courses_source'),
    )
    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False, default='moodle')
    external_id = Column(String(64), nullable=False)  # Moodle course id / export folder number (stable), never a URL
    name = Column(String(300), nullable=False)
    short_name = Column(String(100), nullable=True)
    # Manual mapping only (MRK-42): a sync never sets or changes it; NULL = unmatched.
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class StudyMaterial(Base):
    __tablename__ = 'study_materials'
    __table_args__ = (
        UniqueConstraint('course_id', 'external_id', name='uq_study_materials_course_identity'),
        CheckConstraint("material_type IN ('pdf', 'pptx', 'docx', 'txt', 'other')", name='ck_study_materials_type'),
        CheckConstraint("download_status IN ('stored', 'metadata_only', 'too_large', 'unsupported', 'rejected', 'failed')",
                        name='ck_study_materials_download_status'),
        CheckConstraint("extraction_status IS NULL OR extraction_status IN ('ok', 'empty', 'truncated', 'failed', 'unsupported')",
                        name='ck_study_materials_extraction_status'),
    )
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey('study_courses.id', ondelete='RESTRICT'), nullable=False, index=True)
    # "<course module id>:<file path><file name>" (or its sha256 when too long) – stable across renames of the activity
    external_id = Column(String(512), nullable=False)
    module_external_id = Column(String(32), nullable=False)
    title = Column(String(300), nullable=False)
    section_name = Column(String(300), nullable=True)
    file_name = Column(String(255), nullable=False)  # display only; never used as a filesystem path
    material_type = Column(String(10), nullable=False)
    mime_type = Column(String(120), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)  # as reported by the source
    source_modified_at = Column(DateTime, nullable=True)
    download_status = Column(String(20), nullable=False, default='metadata_only')
    stored_name = Column(String(80), nullable=True)  # content-addressed "<sha256>.<ext>" in MEDIA_DIR/study-materials
    checksum = Column(String(64), nullable=True)  # sha256 of the stored binary
    stored_size = Column(BigInteger, nullable=True)
    extraction_status = Column(String(20), nullable=True)
    extracted_text = Column(Text, nullable=True)  # derived, bounded; never sent to an LLM as a whole
    extracted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    # NULL = present in the latest complete snapshot of its course; set (never deleted) when it disappears
    source_missing_at = Column(DateTime, nullable=True)


class SchoolAttendance(Base):
    """MRK-86: ruční docházka po týdnech – jeden záznam byl/nebyl na předmět a týden (pondělí, Europe/Prague).
    Chybějící řádek = týden nezapsán (nepočítá se ani jako účast, ani jako absence)."""
    __tablename__ = 'school_attendance'
    __table_args__ = (UniqueConstraint('subject_id', 'week_start', name='uq_school_attendance_subject_week'),)
    id = Column(Integer, primary_key=True)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False, index=True)
    week_start = Column(Date, nullable=False)
    present = Column(Boolean, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
