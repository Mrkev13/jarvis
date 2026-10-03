"""Phase D: připomínky – pražský čas, DST, opakování, idempotentní zpracování, výpadky, izolace chyb.

Čas se vždy injektuje (`now=`), žádné čekání v reálném čase.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import reminder_service as rs  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Notification, Reminder  # noqa: E402

# 2026-10-04 12:00 UTC = neděle 14:00 SELČ (UTC+2)
NOW = datetime(2026, 10, 4, 12, 0)


class TimeTestCase(unittest.TestCase):
    def test_local_datetime_is_prague(self):
        self.assertEqual(rs.parse_local_datetime("2026-10-05T08:00"), datetime(2026, 10, 5, 6, 0))  # SELČ
        self.assertEqual(rs.parse_local_datetime("2026-12-05 08:00"), datetime(2026, 12, 5, 7, 0))  # SEČ
        with self.assertRaises(rs.ReminderError):
            rs.parse_local_datetime("zítra v 8")

    def test_one_time_spec(self):
        spec = rs.build_spec("fyzio", due_local="2026-10-05T08:00", now=NOW)
        self.assertEqual((spec.due_at, spec.recurrence), (datetime(2026, 10, 5, 6, 0), "none"))

    def test_relative_spec_is_fixed_at_creation(self):
        spec = rs.build_spec("rotoped", in_minutes=120, now=NOW)
        self.assertEqual(spec.due_at, NOW + timedelta(hours=2))

    def test_invalid_specs(self):
        cases = [
            dict(title="", due_local="2026-10-05T08:00"),
            dict(title="x"),  # chybí čas
            dict(title="x", due_local="2026-10-05T08:00", in_minutes=5),  # obojí
            dict(title="x", due_local="2026-10-04T13:00"),  # minulost (13:00 < 14:00 místního)
            dict(title="x", in_minutes=-5),
            dict(title="x", recurrence="monthly", time_local="08:00"),
            dict(title="x", recurrence="weekly", time_local="08:00"),  # bez dnů
            dict(title="x", recurrence="daily", time_local="25:00"),
        ]
        for kw in cases:
            with self.subTest(kw=kw), self.assertRaises(rs.ReminderError):
                rs.build_spec(now=NOW, **kw)

    def test_weekly_sunday_keeps_wall_clock_across_dst(self):
        spec = rs.build_spec("WoT plán", recurrence="weekly", weekdays="ne", time_local="19:00", now=NOW)
        self.assertEqual(spec.weekdays, "6")
        self.assertEqual(spec.due_at, datetime(2026, 10, 4, 17, 0))  # dnes 19:00 SELČ
        after_dst = rs.next_occurrence("weekly", "6", "19:00", datetime(2026, 10, 18, 17, 0))
        self.assertEqual(after_dst, datetime(2026, 10, 25, 18, 0))  # 25. 10. už SEČ → 19:00 = 18:00 UTC
        before_spring = rs.next_occurrence("weekly", "6", "19:00", datetime(2026, 3, 22, 18, 0))
        self.assertEqual(before_spring, datetime(2026, 3, 29, 17, 0))  # 29. 3. už SELČ

    def test_dst_gap_and_ambiguous_hour(self):
        # Jarní posun 29. 3. 2026: 02:30 neexistuje → posun o mezeru (03:30 SELČ = 01:30 UTC).
        self.assertEqual(rs.next_occurrence("daily", None, "02:30", datetime(2026, 3, 28, 12, 0)),
                         datetime(2026, 3, 29, 1, 30))
        # Podzimní posun 25. 10. 2026: 02:30 je dvakrát → první výskyt (SELČ, 00:30 UTC).
        self.assertEqual(rs.next_occurrence("daily", None, "02:30", datetime(2026, 10, 24, 12, 0)),
                         datetime(2026, 10, 25, 0, 30))
        # Den po posunu zase normálně.
        self.assertEqual(rs.next_occurrence("daily", None, "02:30", datetime(2026, 10, 25, 3, 0)),
                         datetime(2026, 10, 26, 1, 30))

    def test_weekday_parsing(self):
        self.assertEqual(rs.parse_weekdays("po, st, pá"), "0,2,4")
        self.assertEqual(rs.parse_weekdays([6, 0]), "0,6")
        self.assertEqual(rs.parse_weekdays("Čt"), "3")
        with self.assertRaises(rs.ReminderError):
            rs.parse_weekdays("xx")

    def test_prague_labels(self):
        self.assertEqual(rs.format_local(datetime(2026, 10, 5, 6, 0)), "po 5. 10. 2026 08:00")
        self.assertEqual(rs.format_local(datetime(2026, 12, 5, 7, 0)), "so 5. 12. 2026 08:00")


class LifecycleTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def create(self, **kw):
        kw.setdefault("now", NOW)
        r = rs.create_from_spec(self.db, rs.build_spec(**kw))
        self.db.commit()
        return r.id

    def fresh(self):
        """Nová session = jako po restartu procesu (nic z paměti, jen DB)."""
        self.db.close()
        self.db = self.Session()
        return self.db

    def notes(self, rid=None):
        q = self.fresh().query(Notification).filter(Notification.notification_type == "reminder")
        if rid is not None:
            q = q.filter(Notification.source_id == rid)
        return q.order_by(Notification.id).all()

    def get(self, rid):
        return self.fresh().get(Reminder, rid)

    def test_one_time_fires_once_and_survives_restart(self):
        rid = self.create(title="fyzio", due_local="2026-10-05T08:00")
        self.assertEqual(rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 5, 59))["fired"], 0)
        stats = rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 6, 0))
        self.assertEqual(stats, {"checked": 1, "fired": 1, "failed": 0})
        for _ in range(3):  # opakované zpracování / restart
            self.assertEqual(rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 6, 5))["fired"], 0)
        [n] = self.notes(rid)
        self.assertEqual((n.title, n.severity, n.area, n.resolved), ("⏰ fyzio", "important", "reminders", False))
        self.assertIn("po 5. 10. 2026 08:00", n.message)
        self.assertNotIn("Zpožděno", n.message)
        r = self.get(rid)
        self.assertEqual((r.status, r.fire_count), ("fired", 1))

    def test_pending_reminders_survive_restart(self):
        rid = self.create(title="fyzio", due_local="2026-10-05T08:00")
        self.assertEqual(self.get(rid).status, "scheduled")  # nová session, data jen z DB
        self.assertEqual(rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 7, 0))["fired"], 1)

    def test_overdue_after_downtime_fires_once_with_explicit_delay(self):
        rid = self.create(title="fyzio", due_local="2026-10-05T08:00")
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 9, 30))  # 3,5 h po termínu
        [n] = self.notes(rid)
        self.assertIn("Zpožděno", n.message)

    def test_recurring_after_downtime_fires_once_and_schedules_future(self):
        rid = self.create(title="léky", recurrence="daily", time_local="08:00")
        self.assertEqual(self.get(rid).due_at, datetime(2026, 10, 5, 6, 0))
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 8, 12, 0))  # 4 výskyty zmeškány
        self.assertEqual(len(self.notes(rid)), 1)
        r = self.get(rid)
        self.assertEqual((r.status, r.due_at), ("scheduled", datetime(2026, 10, 9, 6, 0)))

    def test_weekly_recurring_fires_each_week(self):
        rid = self.create(title="WoT plán", recurrence="weekly", weekdays="ne", time_local="19:00")
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 4, 17, 0))
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 4, 17, 1))
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 11, 17, 0))
        self.assertEqual(len(self.notes(rid)), 2)
        self.assertEqual(self.get(rid).due_at, datetime(2026, 10, 18, 17, 0))

    def test_snooze_one_time(self):
        rid = self.create(title="rotoped", in_minutes=60)
        rs.process_due_reminders(self.fresh(), now=NOW + timedelta(minutes=61))
        db = self.fresh()
        r = db.get(Reminder, rid)
        until = rs.snooze_target(r, minutes=30, now=NOW + timedelta(minutes=62))
        rs.snooze(db, r, until)
        db.commit()
        r = self.get(rid)
        self.assertEqual((r.status, r.due_at), ("scheduled", until))
        self.assertTrue(all(n.resolved for n in self.notes(rid)))
        rs.process_due_reminders(self.fresh(), now=until)
        self.assertEqual(len(self.notes(rid)), 2)
        self.assertEqual(self.get(rid).status, "fired")

    def test_snooze_recurring_adds_one_extra_occurrence(self):
        rid = self.create(title="léky", recurrence="daily", time_local="08:00")
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 6, 0))
        db = self.fresh()
        r = db.get(Reminder, rid)
        rs.snooze(db, r, datetime(2026, 10, 5, 7, 0))
        db.commit()
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 7, 0))
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 7, 30))
        r = self.get(rid)
        self.assertEqual(len(self.notes(rid)), 2)
        self.assertIsNone(r.snoozed_until)
        self.assertEqual(r.due_at, datetime(2026, 10, 6, 6, 0), "série běží dál")

    def test_snooze_rejects_past_and_missing_values(self):
        rid = self.create(title="x", in_minutes=10)
        r = self.fresh().get(Reminder, rid)
        for kw in ({}, {"minutes": 5, "until_local": "2026-10-05T08:00"}, {"minutes": 0},
                   {"until_local": "2026-10-04T10:00"}):
            with self.subTest(kw=kw), self.assertRaises(rs.ReminderError):
                rs.snooze_target(r, now=NOW, **kw)

    def test_complete_one_time_and_recurring(self):
        once = self.create(title="fyzio", in_minutes=5)
        daily = self.create(title="léky", recurrence="daily", time_local="08:00")
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 5, 6, 0))
        db = self.fresh()
        rs.complete(db, db.get(Reminder, once))
        rs.complete(db, db.get(Reminder, daily))
        db.commit()
        self.assertEqual(self.get(once).status, "done")
        self.assertEqual(self.get(daily).status, "scheduled")
        self.assertTrue(all(n.resolved for n in self.notes()))
        with self.assertRaises(rs.ReminderError):
            db = self.fresh()
            rs.complete(db, db.get(Reminder, once))

    def test_cancel_never_fires(self):
        rid = self.create(title="fyzio", due_local="2026-10-05T08:00")
        db = self.fresh()
        rs.cancel(db, db.get(Reminder, rid))
        db.commit()
        rs.process_due_reminders(self.fresh(), now=datetime(2026, 10, 6, 0, 0))
        self.assertEqual(self.notes(rid), [])
        self.assertEqual(self.get(rid).status, "cancelled")

    def test_update_due_rearms_fired_reminder(self):
        rid = self.create(title="fyzio", in_minutes=5)
        rs.process_due_reminders(self.fresh(), now=NOW + timedelta(minutes=5))
        db = self.fresh()
        rs.update(db, db.get(Reminder, rid), {"due_at": NOW + timedelta(hours=3), "title": "fyzio 2"})
        db.commit()
        r = self.get(rid)
        self.assertEqual((r.status, r.title, r.due_at), ("scheduled", "fyzio 2", NOW + timedelta(hours=3)))

    def test_failure_in_one_reminder_does_not_block_or_duplicate_others(self):
        a = self.create(title="A", in_minutes=1)
        b = self.create(title="B", in_minutes=2)
        c = self.create(title="C", in_minutes=3)
        original = rs._notify

        def flaky(db, r, occurrence, key, now):
            if r.title == "B":
                raise RuntimeError("DB výpadek")
            return original(db, r, occurrence, key, now)

        with patch.object(rs, "_notify", flaky):
            stats = rs.process_due_reminders(self.fresh(), now=NOW + timedelta(minutes=10))
        self.assertEqual(stats, {"checked": 3, "fired": 2, "failed": 1})
        self.assertEqual({n.source_id for n in self.notes()}, {a, c})
        self.assertEqual(self.get(b).status, "scheduled", "chyba se vrátila zpět – připomínka se neztratí")
        stats = rs.process_due_reminders(self.fresh(), now=NOW + timedelta(minutes=11))
        self.assertEqual(stats["fired"], 1)
        self.assertEqual(sorted(n.source_id for n in self.notes()), sorted([a, b, c]))

    def test_two_concurrent_processors_claim_each_occurrence_once(self):
        rid = self.create(title="fyzio", in_minutes=5)
        later = NOW + timedelta(minutes=6)
        db1, db2 = self.Session(), self.Session()
        try:
            self.assertEqual(rs._fire_one(db1, rid, later), 1)
            db1.commit()
            self.assertEqual(rs._fire_one(db2, rid, later), 0)
            db2.commit()
        finally:
            db1.close()
            db2.close()
        self.assertEqual(len(self.notes(rid)), 1)

    def test_existing_notification_generation_does_not_resolve_reminders(self):
        from notifications_service import generate_notifications
        rid = self.create(title="fyzio", in_minutes=5)
        rs.process_due_reminders(self.fresh(), now=NOW + timedelta(minutes=6))
        db = self.fresh()
        generate_notifications(db)
        db.commit()
        self.assertFalse(self.notes(rid)[0].resolved)

    def test_list_and_serialize(self):
        due = self.create(title="fyzio", in_minutes=5)
        later = self.create(title="WoT plán", recurrence="weekly", weekdays="ne", time_local="19:00")
        rs.process_due_reminders(self.fresh(), now=NOW + timedelta(minutes=6))
        items = rs.list_reminders(self.fresh(), now=NOW + timedelta(minutes=6))
        self.assertEqual([i["id"] for i in items], [due, later])
        self.assertEqual(items[0]["state"], "due")
        self.assertEqual(items[1]["recurrence_label"], "každý týden (ne) v 19:00")
        self.assertEqual(items[1]["due_local"], "2026-10-04T19:00:00+02:00")
        self.assertTrue(self.fresh().query(ActivityLog).filter_by(area="reminders").count() >= 2)


if __name__ == "__main__":
    unittest.main()
