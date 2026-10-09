"""habits

MRK-21 (Platform 2.0 D): Návyky – tabulky `habits` a `habit_entries`. Jen nové tabulky, nic existujícího se nemění.
Historie se nemaže kaskádou (FK RESTRICT); stav „missed" se odvozuje při čtení, sloupec ho jen dovoluje.

Revision ID: 0017_habits
Revises: 0016_module_settings
Create Date: 2026-10-08 00:00:17.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0017_habits"
down_revision = "0016_module_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("tracked_since", sa.Date(), nullable=True),
        sa.CheckConstraint("kind IN ('check', 'count', 'duration')", name="ck_habits_kind"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_habits_id"), "habits", ["id"], unique=False)
    op.create_table(
        "habit_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("state IN ('done', 'skipped', 'missed')", name="ck_habit_entries_state"),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("habit_id", "date", name="uq_habit_entries_habit_date"),
    )
    op.create_index(op.f("ix_habit_entries_id"), "habit_entries", ["id"], unique=False)
    op.create_index(op.f("ix_habit_entries_habit_id"), "habit_entries", ["habit_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_habit_entries_habit_id"), table_name="habit_entries")
    op.drop_index(op.f("ix_habit_entries_id"), table_name="habit_entries")
    op.drop_table("habit_entries")
    op.drop_index(op.f("ix_habits_id"), table_name="habits")
    op.drop_table("habits")
