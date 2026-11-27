"""MRK-149: push „Byl jsi na hodině?“ po cvičení z rozvrhu – kdy ano, kdy ne, dedupe, vyřešení zápisem, payload."""
from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import delivery_service
from database import Base
from models import Notification, Subject
from module_registry import ModuleAccess
from modules.calendar import timetable
from modules.school import attendance_prompt, progress

# úterní cvičení 10:00–11:30 Praha (CET = UTC+1) → konec 10:30 UTC
LESSON = {"kind": "exercise", "weekday": 1, "start": "10:00", "end": "11:30",
          "valid_from": "2026-10-01", "valid_until": "2027-01-31"}
TUESDAY = date(2026, 11, 10)
WEEK = date(2026, 11, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Subject(name="Fyzika", code="FY", active=True))
    session.commit()
    with patch("module_registry.current_access", lambda: ModuleAccess({"calendar": True, "school": True})):
        yield session
    session.close()
    engine.dispose()


def sid(db):
    return db.query(Subject).one().id


def lesson(db, **over):
    out = timetable.create_entry(db, {**LESSON, "subject_id": sid(db), **over})
    db.commit()
    return out


def run(db, hh, mm):
    n = attendance_prompt.prompt_attendance(db, datetime(2026, 11, 10, hh, mm))
    db.commit()
    return n


def prompts(db):
    return db.query(Notification).filter_by(notification_type="attendance_prompt").all()


def test_prompt_after_the_lesson_once_per_week(db):
    lesson(db)
    assert run(db, 10, 0) == 0, "hodina ještě běží"
    assert run(db, 11, 7) == 1
    n = prompts(db)[0]
    assert (n.title, n.message, n.dedupe_key) == ("Byl jsi na hodině?", "Fyzika – cvičení 10:00–11:30",
                                                  f"attendance:{sid(db)}:{WEEK.isoformat()}")
    assert run(db, 12, 7) == 0, "dedupe na předmět a týden"
    msg = delivery_service.notification_message(n)
    assert (msg["kind"], msg["subject_id"], msg["week_start"]) == ("attendance", sid(db), "2026-11-09")
    assert "attendance_prompt" in delivery_service.deliverable_types()


def test_writing_attendance_resolves_and_recorded_week_sends_nothing(db):
    lesson(db)
    run(db, 11, 7)
    progress.set_attendance(db, sid(db), WEEK, True, today=TUESDAY)
    db.commit()
    assert prompts(db)[0].resolved is True
    db.query(Notification).delete()
    db.commit()
    assert run(db, 11, 30) == 0, "už zapsaný týden se nedoptává"


def test_cancelled_lesson_lecture_and_late_window(db):
    e = lesson(db)
    lesson(db, kind="lecture", weekday=1, start="12:00", end="13:00")
    timetable.set_exception(db, e["id"], {"date": TUESDAY.isoformat(), "action": "cancel"})
    db.commit()
    assert run(db, 11, 7) == 0, "zrušená hodina"
    assert run(db, 12, 30) == 0, "přednáška se do docházky nepočítá"
    timetable.clear_exception(db, e["id"], TUESDAY.isoformat())
    db.commit()
    assert run(db, 15, 0) == 0, "víc než 3 h po konci se už nedoptává"


def test_moved_lesson_prompts_after_its_new_end(db):
    e = lesson(db)
    timetable.set_exception(db, e["id"], {"date": TUESDAY.isoformat(), "action": "move", "new_date": "2026-11-10",
                                          "start": "14:00", "end": "15:00"})
    db.commit()
    assert run(db, 11, 7) == 0
    assert run(db, 14, 30) == 1  # 15:00 Praha = 14:00 UTC


def test_passed_credit_inactive_subject_and_calendar_off(db):
    lesson(db)
    s = db.query(Subject).one()
    s.credit_status = "passed"
    db.commit()
    assert run(db, 11, 7) == 0
    s.credit_status, s.active = None, False
    db.commit()
    assert run(db, 11, 7) == 0
    s.active = True
    db.commit()
    with patch("module_registry.current_access", lambda: ModuleAccess({"calendar": False})):
        assert run(db, 11, 7) == 0
    assert run(db, 11, 7) == 1
