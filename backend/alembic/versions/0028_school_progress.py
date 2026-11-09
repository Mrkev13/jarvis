"""school_progress

MRK-86: stav zápočtu, limit absencí a týdenní docházka u předmětu. Aditivní: tři nullable sloupce v `subjects`
(stávající předměty = zápočet nesplněn, bez limitu) a nová tabulka `school_attendance` (jeden záznam byl/nebyl na
předmět a týden, týden = pondělí v Europe/Prague). Downgrade sloupce i tabulku odebere.

Revision ID: 0028_school_progress
Revises: 0027_ui_preferences
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_school_progress"
down_revision = "0027_ui_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects") as batch:
        batch.add_column(sa.Column("credit_status", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("credit_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("absence_limit", sa.Integer(), nullable=True))
    op.create_table(
        "school_attendance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "week_start", name="uq_school_attendance_subject_week"),
    )
    op.create_index("ix_school_attendance_subject_id", "school_attendance", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_school_attendance_subject_id", table_name="school_attendance")
    op.drop_table("school_attendance")
    with op.batch_alter_table("subjects") as batch:
        batch.drop_column("absence_limit")
        batch.drop_column("credit_date")
        batch.drop_column("credit_status")
