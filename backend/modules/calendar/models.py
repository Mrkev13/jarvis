"""Durable calendar identity; aware UTC instants plus date-only all-day boundaries."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import TypeDecorator

from database import Base


def now_utc():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Postgres timestamptz; SQLite stores UTC and restores its missing timezone on read."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError('Calendar timestamps must be timezone-aware')
        utc = value.astimezone(timezone.utc)
        return utc.replace(tzinfo=None) if dialect.name == 'sqlite' else utc

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CalendarSource(Base):
    __tablename__ = 'calendar_sources'
    __table_args__ = (CheckConstraint("kind = 'ics'", name='ck_calendar_sources_kind'),)
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False, default='ics')
    name = Column(String(120), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    # An allowlisted configuration alias, never a URL, token or arbitrary env key.
    config_key = Column(String(20), unique=True, nullable=True)
    timezone = Column(String(80), nullable=False, default='Europe/Prague')
    created_at = Column(UTCDateTime(), nullable=False, default=now_utc)


class CalendarEvent(Base):
    __tablename__ = 'calendar_events'
    __table_args__ = (
        UniqueConstraint('source_id', 'external_uid', 'recurrence_id', name='uq_calendar_event_source_identity'),
        CheckConstraint("status IN ('active', 'cancelled')", name='ck_calendar_events_status'),
        CheckConstraint('ends_at >= starts_at', name='ck_calendar_events_interval'),
        CheckConstraint('(all_day = false AND starts_on IS NULL AND ends_on IS NULL) OR '
                        '(all_day = true AND starts_on IS NOT NULL AND ends_on > starts_on)',
                        name='ck_calendar_events_all_day'),
    )
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('calendar_sources.id', ondelete='RESTRICT'), nullable=False, index=True)
    external_uid = Column(String(512), nullable=False)
    recurrence_id = Column(String(100), nullable=False, default='')  # empty master identity, never SQL NULL
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(500), nullable=True)
    starts_at = Column(UTCDateTime(), nullable=False, index=True)
    ends_at = Column(UTCDateTime(), nullable=False)
    all_day = Column(Boolean, nullable=False, default=False)
    starts_on = Column(Date, nullable=True)
    ends_on = Column(Date, nullable=True)  # ICS exclusive end
    timezone = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default='active')
    rrule = Column(Text, nullable=True)
    recurrence_metadata = Column(Text, nullable=True)  # RDATE/EXDATE preserved, not expanded
    sequence = Column(Integer, nullable=False, default=0)
    source_updated_at = Column(UTCDateTime(), nullable=True)
    imported_at = Column(UTCDateTime(), nullable=False, default=now_utc)
    created_at = Column(UTCDateTime(), nullable=False, default=now_utc)
    updated_at = Column(UTCDateTime(), nullable=False, default=now_utc)
    cancelled_at = Column(UTCDateTime(), nullable=True)
