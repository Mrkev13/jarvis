"""Phase D: REST připomínek, lazy zazvonění přes notifikace, scheduler job a úpravy (build_update_changes)."""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import main  # noqa: E402
import reminder_service as rs  # noqa: E402
import scheduler_service  # noqa: E402
from database import Base  # noqa: E402
from models import Notification, Reminder  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0)  # neděle 14:00 Praha


class ReminderApiTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.clock = [NOW]
        self._patches = [
            patch.object(main, "SessionLocal", self.Session),
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH",
                         bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode("utf-8")),
            patch.object(rs, "utc_now", lambda: self.clock[0]),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)

    def test_endpoints_require_session(self):
        for method, path in (("get", "/reminders"), ("post", "/reminders"), ("patch", "/reminders/1"),
                             ("post", "/reminders/1/snooze"), ("post", "/reminders/1/done"),
                             ("post", "/reminders/1/cancel")):
            with self.subTest(path=path):
                kwargs = {} if method == "get" else {"json": {}}
                self.assertEqual(self.client.request(method.upper(), path, **kwargs).status_code, 401)

    def test_create_list_and_fire_through_notification_summary(self):
        self.login()
        r = self.client.post("/reminders", json={"title": "fyzio", "due_local": "2026-10-05T08:00"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["due_label"], body["due_local"]), ("po 5. 10. 2026 08:00", "2026-10-05T08:00:00+02:00"))
        self.assertEqual(self.client.get("/notifications/summary").json()["important"], 0)
        self.clock[0] = datetime(2026, 10, 5, 6, 0, 30)
        self.assertEqual(self.client.get("/notifications/summary").json()["important"], 1)
        self.client.get("/notifications/summary")  # další dotaz = žádný duplikát
        notes = self.client.get("/notifications").json()
        self.assertEqual([n["title"] for n in notes if n["notification_type"] == "reminder"], ["⏰ fyzio"])
        [item] = self.client.get("/reminders").json()
        self.assertEqual((item["status"], item["state"]), ("fired", "due"))

    def test_validation_errors_are_400(self):
        self.login()
        for payload in ({"title": "x"}, {"title": "x", "due_local": "2026-10-01T08:00"},
                        {"title": "x", "recurrence": "weekly", "time_local": "19:00"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/reminders", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/reminders/999/done").status_code, 404)

    def test_snooze_done_cancel_and_update(self):
        self.login()
        rid = self.client.post("/reminders", json={"title": "rotoped", "in_minutes": 120}).json()["id"]
        snoozed = self.client.post(f"/reminders/{rid}/snooze", json={"minutes": 60}).json()
        self.assertEqual(snoozed["due_at"], (NOW + timedelta(hours=1)).isoformat() + "Z")
        updated = self.client.patch(f"/reminders/{rid}", json={"title": "rotoped 30 min"}).json()
        self.assertEqual(updated["title"], "rotoped 30 min")
        self.assertEqual(self.client.post(f"/reminders/{rid}/done").json()["status"], "done")
        self.assertEqual(self.client.post(f"/reminders/{rid}/cancel").status_code, 400)  # už hotová
        weekly = self.client.post("/reminders", json={"title": "WoT plán", "recurrence": "weekly",
                                                      "weekdays": "ne", "time_local": "19:00"}).json()
        self.assertEqual(weekly["recurrence_label"], "každý týden (ne) v 19:00")
        self.assertEqual(self.client.post(f"/reminders/{weekly['id']}/cancel").json()["status"], "cancelled")
        statuses = {i["title"]: i["status"] for i in self.client.get("/reminders?status=all").json()}
        self.assertEqual(statuses, {"rotoped 30 min": "done", "WoT plán": "cancelled"})
        self.assertEqual(self.client.get("/reminders").json(), [])

    def test_scheduler_status_reports_reminder_job(self):
        self.login()
        body = self.client.get("/scheduler/status").json()
        self.assertIn("reminders_enabled", body)
        self.assertGreaterEqual(body["reminders_interval_seconds"], 15)


class SchedulerJobTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self):
        self.engine.dispose()

    def test_job_fires_due_reminders(self):
        db = self.Session()
        rs.create_from_spec(db, rs.build_spec("fyzio", in_minutes=1, now=datetime(2020, 1, 1)))
        db.commit()
        db.close()
        with patch.object(scheduler_service, "SessionLocal", self.Session):
            scheduler_service._run_reminders_job()
            scheduler_service._run_reminders_job()
        db = self.Session()
        try:
            self.assertEqual(db.query(Notification).filter_by(notification_type="reminder").count(), 1)
            self.assertEqual(db.query(Reminder).one().status, "fired")
        finally:
            db.close()

    def test_job_never_raises(self):
        bad_session = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))  # bez tabulek
        with patch.object(scheduler_service, "SessionLocal", bad_session):
            scheduler_service._run_reminders_job()  # nesmí vyhodit výjimku


class UpdateChangesTestCase(unittest.TestCase):
    def _r(self, **kw):
        base = dict(id=1, title="fyzio", note=None, due_at=datetime(2026, 10, 5, 6, 0), status="scheduled",
                    recurrence="none", weekdays=None, local_time=None, snoozed_until=None)
        base.update(kw)
        return Reminder(**base)

    def test_shift_one_time_by_an_hour(self):
        self.assertEqual(rs.build_update_changes(self._r(), shift_minutes=60, now=NOW),
                         {"due_at": datetime(2026, 10, 5, 7, 0)})

    def test_new_local_time_and_title(self):
        changes = rs.build_update_changes(self._r(), title="fyzio!", due_local="2026-10-06T09:15", now=NOW)
        self.assertEqual(changes, {"title": "fyzio!", "due_at": datetime(2026, 10, 6, 7, 15)})

    def test_recurring_time_change_recomputes_next(self):
        r = self._r(recurrence="weekly", weekdays="6", local_time="19:00", due_at=datetime(2026, 10, 4, 17, 0))
        changes = rs.build_update_changes(r, time_local="20:00", now=NOW)
        self.assertEqual(changes["due_at"], datetime(2026, 10, 4, 18, 0))

    def test_invalid_updates(self):
        recurring = self._r(recurrence="daily", local_time="08:00")
        cases = [
            (self._r(), {}),  # nic
            (self._r(), {"shift_minutes": -5000}),  # do minulosti
            (self._r(), {"due_local": "2026-10-06T09:00", "shift_minutes": 5}),
            (recurring, {"shift_minutes": 60}),
            (recurring, {"due_local": "2026-10-06T09:00"}),
            (self._r(status="done"), {"title": "x"}),
        ]
        for r, kw in cases:
            with self.subTest(kw=kw), self.assertRaises(rs.ReminderError):
                rs.build_update_changes(r, now=NOW, **kw)


if __name__ == "__main__":
    unittest.main()
