"""MRK-41: ruční týdenní rozvrh školy jako opakované události Kalendáře (bez migrace, bez sítě)."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import ActivityLog, DomainEvent, Subject
from modules.calendar import integrations, service, timetable
from modules.calendar.models import CalendarEvent, CalendarSource
from modules.calendar.occurrences import get_calendar_occurrences
from today_types import TodayContext

PRAGUE = ZoneInfo("Europe/Prague")
UTC = timezone.utc
# pondělní přednáška 9:00–10:30 přes konec letního času (25. 10. 2026)
LECTURE = {"kind": "lecture", "weekday": 0, "start": "09:00", "end": "10:30", "room": "S5",
           "valid_from": "2026-10-01", "valid_until": "2026-11-30"}


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Subject(name="Matematická analýza", code="MA1", active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def subject_id(db):
    return db.query(Subject).filter_by(code="MA1").one().id


def create(db, **over):
    out = timetable.create_entry(db, {**LECTURE, "subject_id": subject_id(db), **over})
    db.commit()
    return out


def window(db, start: date, end: date):
    lo = datetime.combine(start, datetime.min.time(), tzinfo=PRAGUE)
    hi = datetime.combine(end, datetime.min.time(), tzinfo=PRAGUE)
    return [o for o in get_calendar_occurrences(db, lo, hi) if o.title == "Matematická analýza"]


def local_starts(occs):
    return [o.starts_at.astimezone(PRAGUE).strftime("%Y-%m-%d %H:%M") for o in occs]


def test_weekly_class_on_every_correct_date_across_dst(db):
    entry = create(db)
    assert (entry["weekday_label"], entry["start"], entry["end"], entry["valid_from"], entry["valid_until"]) == \
        ("pondělí", "09:00", "10:30", "2026-10-05", "2026-11-30")
    assert entry["kind_label"] == "Přednáška" and entry["room"] == "S5" and entry["subject_name"] == "Matematická analýza"
    occs = window(db, date(2026, 10, 1), date(2026, 12, 7))
    assert local_starts(occs) == [f"2026-{d} 09:00" for d in
                                  ("10-05", "10-12", "10-19", "10-26", "11-02", "11-09", "11-16", "11-23", "11-30")]
    # stejný místní čas = jiný UTC před a po konci letního času
    assert occs[2].starts_at.astimezone(UTC).hour == 7 and occs[3].starts_at.astimezone(UTC).hour == 8


def test_shows_in_day_timeline_and_today(db):
    create(db)
    day = date(2026, 10, 12)
    context = TodayContext(db, datetime(2026, 10, 12, 5), day, datetime(2026, 10, 12, 7))
    assert [i.title for i in integrations.timeline(context)] == ["Matematická analýza"]


def test_cancel_or_move_affects_only_that_occurrence(db):
    entry = create(db)
    timetable.set_exception(db, entry["id"], {"date": "2026-10-12", "action": "cancel"})
    out = timetable.set_exception(db, entry["id"], {"date": "2026-10-19", "action": "move", "new_date": "2026-10-21",
                                                    "start": "13:00", "end": "14:30"})
    db.commit()
    assert {(e["date"], e["action"]) for e in out["exceptions"]} == {("2026-10-12", "cancel"), ("2026-10-19", "move")}
    starts = local_starts(window(db, date(2026, 10, 5), date(2026, 10, 27)))
    assert starts == ["2026-10-05 09:00", "2026-10-21 13:00", "2026-10-26 09:00"], "12. zrušená, 19. → 21. ve 13:00"
    # obnovení výskytu
    timetable.clear_exception(db, entry["id"], "2026-10-12")
    db.commit()
    assert "2026-10-12 09:00" in local_starts(window(db, date(2026, 10, 5), date(2026, 10, 27)))
    with pytest.raises(timetable.TimetableError):
        timetable.set_exception(db, entry["id"], {"date": "2026-10-13", "action": "cancel"})  # úterý – hodina není


def test_ics_sync_never_touches_manual_entries(db):
    create(db)
    moodle = CalendarSource(kind="ics", name="Moodle", config_key="moodle", enabled=True, timezone="Europe/Prague")
    db.add(moodle)
    db.flush()
    empty = b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
    service.import_ics(db, moodle, empty, now=datetime(2026, 10, 9, tzinfo=UTC))
    db.commit()
    assert db.query(CalendarEvent).filter(CalendarEvent.source_missing_at.isnot(None)).count() == 0
    assert timetable.SOURCE_KEY not in service.configured_sources()
    assert len(window(db, date(2026, 10, 5), date(2026, 10, 6))) == 1


def test_subject_link_and_list_order(db):
    db.add(Subject(name="Programování", code="PRG", active=True))
    db.commit()
    prg = db.query(Subject).filter_by(code="PRG").one().id
    create(db, subject_id=prg, weekday=2, start="12:00", end="13:30", kind="exercise")
    create(db)
    entries = timetable.list_entries(db)["entries"]
    assert [(e["subject_name"], e["weekday_label"], e["kind_label"]) for e in entries] == [
        ("Matematická analýza", "pondělí", "Přednáška"), ("Programování", "středa", "Cvičení")]
    row = db.get(CalendarEvent, entries[1]["id"])
    assert row.course_ref == f"subject:{prg}"


def test_update_moves_all_occurrences_and_drops_old_exceptions(db):
    entry = create(db)
    timetable.set_exception(db, entry["id"], {"date": "2026-10-12", "action": "cancel"})
    out = timetable.update_entry(db, entry["id"], {**LECTURE, "subject_id": subject_id(db), "start": "10:00", "end": "11:30"})
    db.commit()
    assert out["start"] == "10:00" and out["exceptions"] == []
    assert local_starts(window(db, date(2026, 10, 12), date(2026, 10, 13))) == ["2026-10-12 10:00"]


def test_delete_cancels_the_series_without_hard_delete(db):
    entry = create(db)
    timetable.delete_entry(db, entry["id"])
    db.commit()
    assert window(db, date(2026, 10, 1), date(2026, 12, 7)) == []
    assert db.get(CalendarEvent, entry["id"]).status == "cancelled"
    assert timetable.list_entries(db)["entries"] == []


def test_every_change_is_audited_with_a_domain_event(db):
    entry = create(db)
    timetable.set_exception(db, entry["id"], {"date": "2026-10-12", "action": "cancel"})
    timetable.delete_entry(db, entry["id"])
    db.commit()
    types = [e.event_type for e in db.query(DomainEvent).order_by(DomainEvent.id)]
    assert types == ["calendar.event.created", "calendar.event.cancelled", "calendar.event.cancelled"]
    summaries = [a.summary for a in db.query(ActivityLog).order_by(ActivityLog.id)]
    assert summaries[0].startswith("Rozvrh: Matematická analýza (Přednáška, pondělí 09:00)")
    assert "zrušena hodina" in summaries[1]


@pytest.mark.parametrize("over,msg", [
    ({"subject_id": 9999}, "předmět"), ({"kind": "party"}, "Druh"), ({"weekday": 7}, "Den"),
    ({"start": "9:00"}, "HH:MM"), ({"end": "08:00"}, "po začátku"), ({"valid_until": "2026-09-01"}, "Platí do"),
    ({"valid_from": "2026-10-06", "valid_until": "2026-10-11"}, "žádný takový den"),
    ({"valid_until": "2028-01-01"}, "rok"), ({"valid_from": "1. 10. 2026"}, "RRRR-MM-DD"),
])
def test_validation(db, over, msg):
    with pytest.raises(timetable.TimetableError) as err:
        timetable.create_entry(db, {**LECTURE, "subject_id": subject_id(db), **over})
    assert msg in err.value.message


def test_rest_round_trip():
    from unittest.mock import patch

    import auth_service
    import bcrypt
    import database
    import main
    from fastapi.testclient import TestClient

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Subject(name="Fyzika", code="FY", active=True))
    s.commit()
    sid = s.query(Subject).one().id
    s.close()
    with patch.object(database, "SessionLocal", Session), patch.object(main, "SessionLocal", Session), \
            patch.object(auth_service, "SessionLocal", Session), patch.object(auth_service, "_failed_attempts", {}), \
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode()):
        client = TestClient(main.app)
        assert client.get("/calendar/timetable").status_code == 401
        assert client.post("/auth/login", json={"pin": "4821"}).status_code == 200
        r = client.post("/calendar/timetable", json={**LECTURE, "subject_id": sid})
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        assert client.post("/calendar/timetable", json={**LECTURE, "subject_id": sid, "kind": "x"}).status_code == 400
        assert client.post(f"/calendar/timetable/{eid}/exceptions", json={"date": "2026-10-12", "action": "cancel"}).status_code == 200
        assert client.delete(f"/calendar/timetable/{eid}/exceptions/2026-10-12").status_code == 200
        assert client.put(f"/calendar/timetable/{eid}", json={**LECTURE, "subject_id": sid, "room": "A1"}).json()["room"] == "A1"
        assert len(client.get("/calendar/timetable").json()["entries"]) == 1
        assert client.delete(f"/calendar/timetable/{eid}").json() == {"ok": True}
        assert client.delete(f"/calendar/timetable/{eid}").status_code == 404
    engine.dispose()


def test_window_math_for_first_occurrence():
    # valid_from ve čtvrtek, hodina v pondělí → první výskyt další pondělí
    assert date(2026, 10, 1).weekday() == 3
    assert date(2026, 10, 1) + timedelta(days=(0 - 3) % 7) == date(2026, 10, 5)


def move_19_to_21(db, entry):
    timetable.set_exception(db, entry["id"], {"date": "2026-10-19", "action": "move", "new_date": "2026-10-21",
                                              "start": "13:00", "end": "14:30"})
    db.commit()
    assert "2026-10-21 13:00" in local_starts(window(db, date(2026, 10, 1), date(2026, 12, 7)))


def test_delete_series_also_cancels_moved_occurrence(db):
    """Regrese (review #121): přesun → odebrání série nesmí nechat osiřelý výskyt v Kalendáři."""
    entry = create(db)
    move_19_to_21(db, entry)
    timetable.delete_entry(db, entry["id"])
    db.commit()
    assert timetable.list_entries(db)["entries"] == []
    assert window(db, date(2026, 10, 1), date(2026, 12, 7)) == []
    last = db.query(ActivityLog).order_by(ActivityLog.id.desc()).first()
    assert "odebrána" in last.summary


def test_shortening_validity_drops_orphaned_exceptions_only(db):
    """Regrese (review #121): přesun 19. 10. → zkrácení platnosti do 12. 10. → žádný osiřelý výskyt;
    výjimka výskytu, který v platnosti zůstal, se zachová."""
    entry = create(db)
    timetable.set_exception(db, entry["id"], {"date": "2026-10-12", "action": "cancel"})
    move_19_to_21(db, entry)
    out = timetable.update_entry(db, entry["id"], {**LECTURE, "subject_id": subject_id(db), "valid_until": "2026-10-12"})
    db.commit()
    assert [(e["date"], e["action"]) for e in out["exceptions"]] == [("2026-10-12", "cancel")]
    assert local_starts(window(db, date(2026, 10, 1), date(2026, 12, 7))) == ["2026-10-05 09:00"]
    # prodloužení zpět: 19. 10. je zase normální hodina podle rozvrhu (přesun byl zahozen)
    timetable.update_entry(db, entry["id"], {**LECTURE, "subject_id": subject_id(db)})
    db.commit()
    starts = local_starts(window(db, date(2026, 10, 1), date(2026, 10, 27)))
    assert starts == ["2026-10-05 09:00", "2026-10-19 09:00", "2026-10-26 09:00"]


# ---------- MRK-142: hodina ob týden ----------

def test_biweekly_class_only_in_anchor_weeks_across_dst(db, monkeypatch):
    monkeypatch.setattr(timetable, "today_local", lambda: date(2026, 10, 14))
    # výuka v týdnu od 12. 10. → 12. 10., 26. 10. (po konci letního času), 9. 11., 23. 11.; ne 5. 10. ani 19. 10.
    entry = create(db, kind="exercise", every=2, week_anchor="2026-10-14")
    assert (entry["every"], entry["valid_from"], entry["week_anchor"], entry["next_date"]) == \
        (2, "2026-10-12", "2026-10-12", "2026-10-26")
    occs = window(db, date(2026, 10, 1), date(2026, 12, 7))
    assert local_starts(occs) == [f"2026-{d} 09:00" for d in ("10-12", "10-26", "11-09", "11-23")]
    assert occs[0].starts_at.astimezone(UTC).hour == 7 and occs[1].starts_at.astimezone(UTC).hour == 8
    assert "ob týden" in db.query(ActivityLog).order_by(ActivityLog.id.desc()).first().summary
    # druhá parita: výuka příští týden (od 19. 10.) → 5. 10., 19. 10., …
    other = create(db, kind="exercise", every=2, week_anchor="2026-10-19", start="11:00", end="12:30")
    assert other["valid_from"] == "2026-10-05" and other["next_date"] == "2026-10-19"


def test_biweekly_exceptions_and_switching_rhythm(db):
    entry = create(db, every=2, week_anchor="2026-10-12")
    with pytest.raises(timetable.TimetableError):  # 19. 10. hodina není
        timetable.set_exception(db, entry["id"], {"date": "2026-10-19", "action": "cancel"})
    timetable.set_exception(db, entry["id"], {"date": "2026-10-26", "action": "cancel"})
    timetable.set_exception(db, entry["id"], {"date": "2026-11-09", "action": "move", "new_date": "2026-11-10",
                                              "start": "13:00", "end": "14:30"})
    db.commit()
    assert local_starts(window(db, date(2026, 10, 1), date(2026, 12, 7))) == \
        ["2026-10-12 09:00", "2026-11-10 13:00", "2026-11-23 09:00"]
    # ob týden → každý týden: výjimky platných výskytů zůstanou
    out = timetable.update_entry(db, entry["id"], {**LECTURE, "subject_id": subject_id(db)})
    db.commit()
    assert out["every"] == 1 and {e["date"] for e in out["exceptions"]} == {"2026-10-26", "2026-11-09"}
    # každý týden → ob týden s druhou paritou: 26. 10. ani 9. 11. do série nepatří → výjimky zmizí
    out = timetable.update_entry(db, entry["id"], {**LECTURE, "subject_id": subject_id(db), "every": 2,
                                                   "week_anchor": "2026-10-05"})
    db.commit()
    assert out["exceptions"] == [] and out["valid_from"] == "2026-10-05"
    assert local_starts(window(db, date(2026, 10, 1), date(2026, 11, 3))) == ["2026-10-05 09:00", "2026-10-19 09:00", "2026-11-02 09:00"]


@pytest.mark.parametrize("over,msg", [
    ({"every": 3}, "Rytmus"),
    ({"every": True}, "Rytmus"),
    ({"every": 2}, "tento, nebo příští"),
    ({"every": 2, "week_anchor": "zítra"}, "Týden s výukou"),
    ({"every": 2, "week_anchor": "2026-10-12", "valid_from": "2026-10-05", "valid_until": "2026-10-10"}, "žádný takový den"),
])
def test_biweekly_validation(db, over, msg):
    with pytest.raises(timetable.TimetableError) as err:
        timetable.create_entry(db, {**LECTURE, "subject_id": subject_id(db), **over})
    assert msg in err.value.message


# ---------- MRK-147: „příště“ podle skutečných výskytů ----------

def test_next_date_skips_cancelled_and_follows_moved(db, monkeypatch):
    """Reprodukce z review #124: ob týden od 12. 10., dnes 14. 10., 26. 10. zrušeno → příště 9. 11."""
    monkeypatch.setattr(timetable, "today_local", lambda: date(2026, 10, 14))
    entry = create(db, kind="exercise", every=2, week_anchor="2026-10-12")
    out = timetable.set_exception(db, entry["id"], {"date": "2026-10-26", "action": "cancel"})
    db.commit()
    assert (out["next_date"], out["next_regular_date"]) == ("2026-11-09", "2026-11-09")
    # přesun 9. 11. → 5. 11.: skutečná příští hodina je 5. 11., formulář výjimky nabídne 23. 11. (bez výjimky)
    out = timetable.set_exception(db, entry["id"], {"date": "2026-11-09", "action": "move", "new_date": "2026-11-05",
                                                    "start": "13:00", "end": "14:30"})
    db.commit()
    assert (out["next_date"], out["next_regular_date"]) == ("2026-11-05", "2026-11-23")
    # přesun dřív než dnes se nepočítá
    out = timetable.set_exception(db, entry["id"], {"date": "2026-11-09", "action": "move", "new_date": "2026-10-13",
                                                    "start": "13:00", "end": "14:30"})
    db.commit()
    assert out["next_date"] == "2026-11-23"
    listed = timetable.list_entries(db)["entries"][0]
    assert (listed["next_date"], listed["next_regular_date"]) == ("2026-11-23", "2026-11-23")


def test_next_date_weekly_unchanged_without_exceptions(db, monkeypatch):
    monkeypatch.setattr(timetable, "today_local", lambda: date(2026, 10, 14))
    entry = create(db)
    assert (entry["next_date"], entry["next_regular_date"]) == ("2026-10-19", "2026-10-19")


def test_next_date_includes_move_past_the_series_end(db, monkeypatch):
    """Regrese (review #128): poslední hodina 30. 11. přesunutá na 2. 12. (za konec platnosti) je „příště“
    i 29. 11., i 1. 12. (po konci série) – stejně jako ji ukazuje Kalendář."""
    entry = create(db)  # pondělí, platnost do 30. 11.
    timetable.set_exception(db, entry["id"], {"date": "2026-11-30", "action": "move", "new_date": "2026-12-02",
                                              "start": "09:00", "end": "10:30"})
    db.commit()
    assert "2026-12-02 09:00" in local_starts(window(db, date(2026, 11, 28), date(2026, 12, 7)))
    for today in (date(2026, 11, 29), date(2026, 12, 1)):
        monkeypatch.setattr(timetable, "today_local", lambda t=today: t)
        listed = timetable.list_entries(db)["entries"][0]
        assert (listed["next_date"], listed["next_regular_date"]) == ("2026-12-02", None), today
    monkeypatch.setattr(timetable, "today_local", lambda: date(2026, 12, 3))
    assert timetable.list_entries(db)["entries"][0]["next_date"] is None
