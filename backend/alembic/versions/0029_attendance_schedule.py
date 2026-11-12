"""attendance_schedule

MRK-112: rytmus výuky předmětu pro docházku. Aditivní: dva nullable sloupce v `subjects` – `attendance_every`
(NULL / 1 = každý týden, 2 = každý druhý týden) a `attendance_anchor` (pondělí týdne s výukou, jen u 2). Stávající
předměty = každý týden, nic se nepřepočítává. Downgrade oba sloupce odebere.

Revision ID: 0029_attendance_schedule
Revises: 0028_school_progress
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_attendance_schedule"
down_revision = "0028_school_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subjects") as batch:
        batch.add_column(sa.Column("attendance_every", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("attendance_anchor", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects") as batch:
        batch.drop_column("attendance_anchor")
        batch.drop_column("attendance_every")
