"""Moodle calendar events → school subjects (MRK-76). Deterministic, read-time only, nothing is stored or guessed.

School-owned bridge (module packages never import each other): the Calendar module only keeps the event's
`course_ref`; this file links it to the School's study courses and subjects for Termíny, Dnes, the dashboard and the
AI school context.

An event's `course_ref` (ICS CATEGORIES; Moodle puts the course short name there) must equal a study course's
`short_name` (trimmed, case-insensitive) and that course must be mapped to a subject (`StudyCourse.subject_id`,
MRK-42). Unmapped courses, events without CATEGORIES and short names shared by courses mapped to different subjects
match nothing – the event simply stays a plain calendar event.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query

import database
from models import Assignment, Exam, Subject
from modules.calendar.models import CalendarEvent, CalendarSource
from modules.calendar.occurrences import get_calendar_occurrences, local_window
from modules.school.models import StudyCourse
from time_utils import to_local, today_local
from today_types import TodayItem

DEADLINE_LIMIT = 200


def _key(value: str | None) -> str:
    return (value or '').strip().casefold()


def course_subjects(db) -> dict[str, Subject]:
    """Course short name (normalised) → its subject; a name mapped to several subjects is left out."""
    found: dict[str, set[int]] = {}
    for short_name, subject_id in (db.query(StudyCourse.short_name, StudyCourse.subject_id)
                                   .filter(StudyCourse.subject_id.isnot(None), StudyCourse.short_name.isnot(None))):
        if _key(short_name):
            found.setdefault(_key(short_name), set()).add(subject_id)
    unique = {key: next(iter(ids)) for key, ids in found.items() if len(ids) == 1}
    if not unique:
        return {}
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(set(unique.values())))}
    return {key: subjects[sid] for key, sid in unique.items() if sid in subjects}


def event_subjects(db, event_ids) -> dict[int, Subject]:
    """Calendar event id → subject for the given events (only matched ones)."""
    ids = sorted(set(event_ids))
    if not ids:
        return {}
    courses = course_subjects(db)
    if not courses:
        return {}
    # MRK-77: only the Moodle source – a Google event whose CATEGORIES happens to equal a course short name is not
    # a school deadline
    rows = (db.query(CalendarEvent.id, CalendarEvent.course_ref)
            .join(CalendarSource, CalendarSource.id == CalendarEvent.source_id)
            .filter(CalendarEvent.id.in_(ids), CalendarEvent.course_ref.isnot(None), CalendarSource.config_key == 'moodle'))
    return {event_id: courses[_key(ref)] for event_id, ref in rows if _key(ref) in courses}


def _day(o) -> date:
    return o.starts_on if o.all_day else to_local(o.starts_at).date()


def _manual_days(db, start: date, end: date) -> set[tuple[int, date]]:
    """(subject, day) already covered by a manual exam or assignment – the Moodle twin is not repeated."""
    days = {(e.subject_id, e.exam_date) for e in db.query(Exam.subject_id, Exam.exam_date)
            .filter(Exam.exam_date >= start, Exam.exam_date < end)}
    days |= {(a.subject_id, a.due_date) for a in db.query(Assignment.subject_id, Assignment.due_date)
             .filter(Assignment.due_date >= start, Assignment.due_date < end)}
    return days


def school_deadlines(db, start: date, end: date) -> list[dict]:
    """Active Moodle occurrences in local days [start, end) linked to a subject, without manual duplicates."""
    occurrences = get_calendar_occurrences(db, *local_window(start, end), limit=DEADLINE_LIMIT)
    links = event_subjects(db, (o.event_id for o in occurrences))
    if not links:
        return []
    manual = _manual_days(db, start - timedelta(days=1), end + timedelta(days=1))
    items = []
    for o in occurrences:
        subject = links.get(o.event_id)
        day = _day(o)
        if subject is None or (subject.id, day) in manual or not start <= day < end:
            continue
        items.append({'key': o.key, 'event_id': o.event_id, 'title': o.title, 'date': day.isoformat(),
                      'time': None if o.all_day else to_local(o.starts_at).strftime('%H:%M'), 'all_day': o.all_day,
                      'subject_id': subject.id, 'subject_name': subject.name, 'href': f'/calendar?event={o.event_id}'})
    return items


def today_items(db, start: date, end: date, display_from: date) -> list[TodayItem]:
    """Dnes: Moodle deadlines as school items. The ref equals the Calendar's own item (`calendar_event:<key>`), so the
    global dedupe keeps this one (School is ordered first) instead of showing the event twice."""
    out = []
    for m in school_deadlines(db, start, end):
        out.append(TodayItem(id=f"calendar_event:{m['key']}", type='calendar_event', title=m['title'],
                             subtitle=f"Moodle · {m['subject_name']}", area='school',
                             date=max(date.fromisoformat(m['date']), display_from).isoformat(), time=m['time'],
                             status='upcoming', href=m['href'], source_id=m['event_id']))
    return out


def calendar_enabled() -> bool:
    """Moodle data lives in the Calendar module: with Calendar switched off nothing of it is shown here either."""
    from module_registry import current_access  # lazy: the registry imports this file through school_integrations
    return current_access().is_available('calendar')


router = APIRouter(prefix='/school/moodle-deadlines', tags=['school'])


@router.get('')
def moodle_deadlines(days: int = Query(default=60, ge=1, le=92)):
    """Škola → Termíny: Moodle events of mapped subjects, local days [today, today + days). Empty while Calendar is
    switched off (its data stays behind its own module gate)."""
    if not calendar_enabled():
        return {'items': [], 'calendar_enabled': False}
    db = database.SessionLocal()
    try:
        today = today_local()
        return {'items': school_deadlines(db, today, today + timedelta(days=days)), 'calendar_enabled': True}
    finally:
        db.close()
