import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Assignment, Exam, FinanceTransaction, Goal, GoalProgressHistory, Notification, Subject, WorkSession
from goal_history_service import record_goal_progress_snapshot
from notifications_service import (
    generate_notifications,
    list_notifications,
    mark_all_read,
    mark_read,
    notifications_summary,
    resolve,
)


class NotificationsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

        subj = Subject(name="Test", code="", semester="", credits=0, active=True)
        self.db.add(subj)
        self.db.commit()
        self.subject_id = subj.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_deadline_14_7_3(self):
        today = date(2026, 9, 11)
        a14 = Assignment(
            title="A14",
            description="",
            due_date=today + timedelta(days=14),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        a7 = Assignment(
            title="A7",
            description="",
            due_date=today + timedelta(days=7),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        a3 = Assignment(
            title="A3",
            description="",
            due_date=today + timedelta(days=3),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add_all([a14, a7, a3])
        self.db.commit()

        generate_notifications(self.db, today=today)
        self.db.commit()

        now_dt = datetime.combine(today, datetime.min.time()).replace(hour=9)
        items = list_notifications(self.db, now=now_dt)
        by_title = {it["title"]: it for it in items}
        self.assertEqual(by_title["Deadline: A14"]["severity"], "info")
        self.assertEqual(by_title["Deadline: A7"]["severity"], "warning")
        self.assertEqual(by_title["Deadline: A3"]["severity"], "important")

    def test_overdue(self):
        today = date(2026, 9, 11)
        a = Assignment(
            title="Over",
            description="",
            due_date=today - timedelta(days=1),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add(a)
        self.db.commit()

        generate_notifications(self.db, today=today)
        self.db.commit()

        now_dt = datetime.combine(today, datetime.min.time()).replace(hour=9)
        items = list_notifications(self.db, now=now_dt)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["notification_type"], "overdue")
        self.assertEqual(items[0]["severity"], "important")

    def test_notification_deduplication(self):
        today = date(2026, 9, 11)
        a = Assignment(
            title="Dedup",
            description="",
            due_date=today + timedelta(days=7),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add(a)
        self.db.commit()

        generate_notifications(self.db, today=today)
        self.db.commit()
        generate_notifications(self.db, today=today)
        self.db.commit()

        rows = self.db.query(Notification).filter(Notification.resolved == False).all()
        self.assertEqual(len(rows), 1)

    def test_read_unread_and_read_all(self):
        n1 = Notification(
            area="school",
            title="T1",
            message="M1",
            severity="info",
            read=False,
            created_at=datetime.utcnow(),
            expires_at=None,
            notification_type="deadline",
            source_type="assignment",
            source_id=1,
            dedupe_key="k1",
            last_triggered_at=datetime.utcnow(),
            resolved=False,
            action_url="/school",
        )
        n2 = Notification(
            area="school",
            title="T2",
            message="M2",
            severity="warning",
            read=False,
            created_at=datetime.utcnow(),
            expires_at=None,
            notification_type="deadline",
            source_type="assignment",
            source_id=2,
            dedupe_key="k2",
            last_triggered_at=datetime.utcnow(),
            resolved=False,
            action_url="/school",
        )
        self.db.add_all([n1, n2])
        self.db.commit()

        self.assertTrue(mark_read(self.db, n1.id))
        self.db.commit()
        s = notifications_summary(self.db)
        self.assertEqual(s["unread"], 1)

        count = mark_all_read(self.db)
        self.db.commit()
        self.assertEqual(count, 1)
        s2 = notifications_summary(self.db)
        self.assertEqual(s2["unread"], 0)

    def test_resolve(self):
        n = Notification(
            area="school",
            title="T",
            message="M",
            severity="info",
            read=False,
            created_at=datetime.utcnow(),
            expires_at=None,
            notification_type="deadline",
            source_type="assignment",
            source_id=1,
            dedupe_key="k",
            last_triggered_at=datetime.utcnow(),
            resolved=False,
            action_url="/school",
        )
        self.db.add(n)
        self.db.commit()
        self.assertTrue(resolve(self.db, n.id))
        self.db.commit()
        items = list_notifications(self.db)
        self.assertEqual(items, [])

    def test_high_and_medium_stagnation(self):
        today = date(2026, 9, 11)
        g1 = Goal(area="work", title="G1", description="", status="active", priority="high", progress=0, tracking_type="manual")
        g2 = Goal(area="work", title="G2", description="", status="active", priority="medium", progress=0, tracking_type="manual")
        self.db.add_all([g1, g2])
        self.db.commit()

        record_goal_progress_snapshot(self.db, g1.id, 10, None, recorded_at=datetime(2026, 9, 1))
        record_goal_progress_snapshot(self.db, g1.id, 10, None, recorded_at=datetime(2026, 9, 3))
        record_goal_progress_snapshot(self.db, g2.id, 10, None, recorded_at=datetime(2026, 8, 20))
        record_goal_progress_snapshot(self.db, g2.id, 10, None, recorded_at=datetime(2026, 8, 28))
        self.db.commit()

        generate_notifications(self.db, today=today)
        self.db.commit()
        items = list_notifications(self.db, include_resolved=True)
        keys = {it["dedupe_key"] for it in items}
        self.assertIn(f"goal_stagnation:{g1.id}", keys)
        self.assertIn(f"goal_stagnation:{g2.id}", keys)

    def test_work_behind_schedule(self):
        today = date(2026, 9, 18)
        g = Goal(
            area="work",
            title="Work 100h",
            description="",
            status="active",
            priority="medium",
            progress=0,
            tracking_type="automatic",
            target_value=100.0,
            source="work_month_hours",
        )
        self.db.add(g)
        self.db.commit()

        ws = WorkSession(date=today, hours=30.0, project="", description="", hourly_rate=0.0)
        self.db.add(ws)
        self.db.commit()

        record_goal_progress_snapshot(self.db, g.id, 10, 10.0, recorded_at=datetime(2026, 9, 1))
        record_goal_progress_snapshot(self.db, g.id, 10, 10.0, recorded_at=datetime(2026, 9, 2))
        self.db.commit()

        generate_notifications(self.db, today=today)
        self.db.commit()
        items = list_notifications(self.db, include_resolved=True)
        keys = {it["dedupe_key"] for it in items}
        self.assertIn(f"work_behind:{g.id}", keys)

    def test_finance_goal_stagnation(self):
        today = date(2026, 9, 11)
        g = Goal(
            area="finance",
            title="Save",
            description="",
            status="active",
            priority="high",
            progress=0,
            tracking_type="automatic",
            target_value=100000.0,
            source="finance_balance",
        )
        self.db.add(g)
        self.db.commit()

        record_goal_progress_snapshot(self.db, g.id, 10, 100.0, recorded_at=datetime(2026, 8, 20))
        record_goal_progress_snapshot(self.db, g.id, 10, 100.0, recorded_at=datetime(2026, 8, 25))
        self.db.commit()

        generate_notifications(self.db, today=today)
        self.db.commit()

        items = list_notifications(self.db, include_resolved=True)
        keys = {it["dedupe_key"] for it in items}
        self.assertIn(f"finance_goal_stagnation:{g.id}", keys)

    def test_expired_notification(self):
        n = Notification(
            area="school",
            title="Expired",
            message="M",
            severity="info",
            read=False,
            created_at=datetime.utcnow() - timedelta(days=10),
            expires_at=datetime.utcnow() - timedelta(days=1),
            notification_type="deadline",
            source_type="assignment",
            source_id=1,
            dedupe_key="expired",
            last_triggered_at=datetime.utcnow() - timedelta(days=10),
            resolved=False,
            action_url="/school",
        )
        self.db.add(n)
        self.db.commit()
        generate_notifications(self.db, today=date(2026, 9, 11))
        self.db.commit()
        self.assertTrue(self.db.query(Notification).filter(Notification.dedupe_key == "expired").first().resolved)


if __name__ == "__main__":
    unittest.main()
