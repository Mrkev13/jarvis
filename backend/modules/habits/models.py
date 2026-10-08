"""Modely Návyků (MRK-21). Registrují se do společné `Base` (models.py je importuje), migrace 0017.

Historie je trvalá: záznam dne (`HabitEntry`) se nikdy nemaže kaskádou – archivace návyku jen nastaví
`archived_at`, cizí klíč je RESTRICT. Změna stavu dne se loguje do Aktivity s deltou (stopa původní hodnoty).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base

HABIT_KINDS = ("check", "count", "duration")
ENTRY_STATES = ("done", "skipped", "missed")


class Habit(Base):
    __tablename__ = "habits"
    __table_args__ = (CheckConstraint("kind IN ('check', 'count', 'duration')", name="ck_habits_kind"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    kind = Column(String(20), nullable=False, default="check")
    target_value = Column(Float, nullable=True)   # např. 2 (l), 20 (min) – jen orientační cíl
    unit = Column(String(20), nullable=True)      # „l", „min", „x"
    active = Column(Boolean, nullable=False, default=True)  # False = archivovaný (spolu s archived_at)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    archived_at = Column(DateTime, nullable=True)
    # Pražský den, od kterého se odvozuje „missed" (po obnovení z archivu = den obnovení; None = den založení).
    # Dny archivace se tak nikdy nepočítají jako vynechané; uložené záznamy platí vždy.
    tracked_since = Column(Date, nullable=True)

    entries = relationship("HabitEntry", back_populates="habit", passive_deletes="all", order_by="HabitEntry.date")


class HabitEntry(Base):
    """Stav návyku v jeden pražský den. Unikátní (návyk, den); chybějící záznam minulého dne = „missed" (odvozeno)."""
    __tablename__ = "habit_entries"
    __table_args__ = (
        UniqueConstraint("habit_id", "date", name="uq_habit_entries_habit_date"),
        CheckConstraint("state IN ('done', 'skipped', 'missed')", name="ck_habit_entries_state"),
    )

    id = Column(Integer, primary_key=True, index=True)
    habit_id = Column(Integer, ForeignKey("habits.id", ondelete="RESTRICT"), nullable=False, index=True)
    date = Column(Date, nullable=False)                 # pražský kalendářní den
    state = Column(String(20), nullable=False)
    value = Column(Float, nullable=True)                # počet (count)
    duration_minutes = Column(Integer, nullable=True)   # délka (duration)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    habit = relationship("Habit", back_populates="entries")
