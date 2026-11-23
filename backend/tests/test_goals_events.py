"""MRK-135: doménová událost goals.goal.completed – ruční úprava (POST /goal) i automatický cíl (přepočet zdrojů)."""
import os
import sys
import unittest
from datetime import date
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
import goal_history_service as ghs  # noqa: E402
import main  # noqa: E402
from database import Base  # noqa: E402
from domain_events import declared_types  # noqa: E402
from goals_events import GOAL_COMPLETED, goal_reached  # noqa: E402
from models import ActivityLog, DomainEvent, Goal, WorkSession  # noqa: E402


class GoalReachedTestCase(unittest.TestCase):
    def test_transition_only(self):
        self.assertTrue(goal_reached(50, "active", 100, "active"))
        self.assertTrue(goal_reached(40, "active", 40, "completed"))
        self.assertFalse(goal_reached(100, "active", 100, "active"), "opakované uložení splněného cíle")
        self.assertFalse(goal_reached(100, "completed", 50, "active"))
        self.assertFalse(goal_reached(40, "active", 40, "cancelled"))
        self.assertFalse(goal_reached(0, None, 99, "active"))

    def test_declared_for_goals_module(self):
        self.assertEqual(declared_types()[GOAL_COMPLETED], "goals")


class GoalCompletedEventTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._patches = [
            patch.object(main, "SessionLocal", self.Session),
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def events(self):
        db = self.Session()
        try:
            return [(e.event_type, dict(e.payload)) for e in db.query(DomainEvent).filter_by(event_type=GOAL_COMPLETED)]
        finally:
            db.close()

    def test_manual_goal_reaching_100_emits_once_with_activity(self):
        body = {"area": "personal", "title": "Přečíst 12 knih", "progress": 50}
        gid = self.client.post("/goal", json=body).json()["id"]
        self.assertEqual(self.events(), [])
        self.client.post("/goal", json={**body, "id": gid, "progress": 100})
        self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 50})])
        self.client.post("/goal", json={**body, "id": gid, "progress": 100, "description": "upraveno"})
        self.assertEqual(len(self.events()), 1, "opakované uložení splněného cíle nic nevyšle")
        db = self.Session()
        try:
            acts = [a.summary for a in db.query(ActivityLog).filter_by(area="goals", action_type="complete")]
        finally:
            db.close()
        self.assertEqual(acts, ["Cíl 'Přečíst 12 knih' splněn"])

    def test_status_completed_counts_as_done(self):
        gid = self.client.post("/goal", json={"area": "personal", "title": "Kurz", "progress": 30}).json()["id"]
        self.client.post("/goal", json={"id": gid, "area": "personal", "title": "Kurz", "progress": 30, "status": "completed"})
        self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 30})])

    def test_work_session_endpoint_completes_automatic_goal(self):
        """Codex review #100: skutečný producent zdroje (POST /work/session) – 5 h, cíl 10 h (50 %), +6 h → událost."""
        today = date.today().isoformat()
        with patch.object(ghs, "today_local", lambda: date.today()):
            self.assertEqual(self.client.post("/work/session", json={"date": today, "hours": 5, "hourly_rate": 200}).status_code, 200)
            gid = self.client.post("/goal", json={"area": "work", "title": "10 h práce", "tracking_type": "automatic",
                                                   "source": "work_month_hours", "target_value": 10}).json()["id"]
            self.assertEqual(self.events(), [])
            self.assertEqual(self.client.post("/work/session", json={"date": today, "hours": 6, "hourly_rate": 200}).status_code, 200)
            self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 50})])
            self.client.post("/work/session", json={"date": today, "hours": 1, "hourly_rate": 200})
            db = self.Session()
            try:
                ghs.refresh_automatic_goals(db, {"work_month_hours"})
                db.commit()
            finally:
                db.close()
        self.assertEqual(len(self.events()), 1, "nad 100 % ani další přepočet nic nezopakuje")

    def test_goal_edit_rolls_back_when_the_event_fails(self):
        """Codex review #100: změna cíle, snapshot a událost jsou jedna transakce – chyba události vrátí i 100 %."""
        import goals_events
        gid = self.client.post("/goal", json={"area": "personal", "title": "Atomický", "progress": 50}).json()["id"]

        def boom(*_a, **_k):
            raise RuntimeError("event store down")

        with patch.object(goals_events, "emit_goal_completed", boom), self.assertRaises(RuntimeError):
            self.client.post("/goal", json={"id": gid, "area": "personal", "title": "Atomický", "progress": 100})
        db = self.Session()
        try:
            self.assertEqual(db.get(Goal, gid).progress, 50, "úprava se vrátila spolu s událostí")
        finally:
            db.close()
        self.assertEqual(self.events(), [])
        self.client.post("/goal", json={"id": gid, "area": "personal", "title": "Atomický", "progress": 100})
        self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 50})])

    def test_automatic_goal_heals_after_a_failed_snapshot(self):
        """Automatický cíl se počítá živě a porovnává s posledním snapshotem: když zápis snapshotu po změně zdroje
        selže, událost doplní další snapshot (hodinový job) – nic se neztratí."""
        today = date.today().isoformat()
        with patch.object(ghs, "today_local", lambda: date.today()):
            self.client.post("/work/session", json={"date": today, "hours": 5, "hourly_rate": 200})
            gid = self.client.post("/goal", json={"area": "work", "title": "10 h", "tracking_type": "automatic",
                                                   "source": "work_month_hours", "target_value": 10}).json()["id"]
            with patch.object(main, "ensure_goal_progress_snapshot", side_effect=RuntimeError("snapshot down")), \
                    self.assertRaises(RuntimeError):
                self.client.post("/work/session", json={"date": today, "hours": 6, "hourly_rate": 200})
            self.assertEqual(self.events(), [])
            db = self.Session()
            try:
                ghs.ensure_goal_progress_snapshot_for_all_active_automatic_goals(db)
                db.commit()
            finally:
                db.close()
        self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 50})])

    def test_status_completed_and_100_at_once_emits_once(self):
        gid = self.client.post("/goal", json={"area": "personal", "title": "Maraton", "progress": 60}).json()["id"]
        self.client.post("/goal", json={"id": gid, "area": "personal", "title": "Maraton", "progress": 100, "status": "completed"})
        self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 60})])

    def test_automatic_goal_crossing_100_on_refresh(self):
        today = date(2026, 11, 23)
        db = self.Session()
        try:
            db.add(WorkSession(date=today, hours=5, hourly_rate=200, project="x"))
            g = Goal(area="work", title="10 h práce", status="active", priority="medium", tracking_type="automatic",
                     source="work_month_hours", target_value=10)
            db.add(g)
            db.commit()
            ghs.ensure_goal_progress_snapshot(db, g)  # 50 %
            db.commit()
            db.add(WorkSession(date=today, hours=6, hourly_rate=200, project="x"))
            with patch.object(ghs, "today_local", lambda: today):
                ghs.refresh_automatic_goals(db, {"work_month_hours"}, user_context="system")
                db.commit()
                ghs.refresh_automatic_goals(db, {"work_month_hours"}, user_context="system")  # už splněný
                db.commit()
            gid = g.id
        finally:
            db.close()
        self.assertEqual(self.events(), [(GOAL_COMPLETED, {"goal_id": gid, "previous_progress": 50})])


if __name__ == "__main__":
    unittest.main()
