import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models as _all_models
from database import Base


class SchedulerTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

        subj = _all_models.Subject(name="TestSubj", code="", semester="", credits=0, active=True)
        self.db.add(subj)
        self.db.commit()
        self.subject_id = subj.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_01_run_hourly_job_creates_snapshots_and_notifications(self):
        from models import Assignment, FinanceTransaction, Goal, GoalProgressHistory, Notification

        goal = Goal(
            area="finance",
            title="Ušetřit 1M",
            description="",
            status="active",
            priority="medium",
            progress=0,
            tracking_type="automatic",
            target_value=1000000.0,
            source="finance_balance",
        )
        self.db.add(goal)
        self.db.commit()

        fin = FinanceTransaction(
            amount=100000.0,
            category="plat",
            description="",
            transaction_type="income",
        )
        self.db.add(fin)
        self.db.commit()

        today = date.today()
        overdue_due = today - timedelta(days=1)
        ass = Assignment(
            title="Overdue Assignment",
            description="",
            due_date=overdue_due,
            priority="high",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add(ass)
        self.db.commit()

        self.db.close()

        TestSession = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        import scheduler_service
        with patch.object(scheduler_service, "SessionLocal", TestSession):
            scheduler_service._run_hourly_job()

        verify_db = TestSession()
        try:
            history_count = verify_db.query(GoalProgressHistory).count()
            self.assertGreater(history_count, 0, "GoalProgressHistory rows should be > 0")

            notif_count = verify_db.query(Notification).count()
            self.assertGreater(notif_count, 0, "Notifications rows should be > 0")
        finally:
            verify_db.close()

    def test_02_scheduler_status_endpoint_disabled_default(self):
        import scheduler_service
        self.assertFalse(scheduler_service.SCHEDULER_ENABLED)
        self.assertEqual(scheduler_service.SCHEDULER_INTERVAL_SECONDS, 3600)
        doc = scheduler_service.SINGLE_WORKER_ASSUMPTION_DOC.lower()
        self.assertIn("single", doc)
        self.assertIn("worker", doc)

    def test_03_coalesce_and_single_worker_doc(self):
        import scheduler_service

        doc = scheduler_service.SINGLE_WORKER_ASSUMPTION_DOC.lower()
        self.assertIn("single", doc)
        self.assertIn("worker", doc)

        self.assertEqual(scheduler_service.SCHEDULER_INTERVAL_SECONDS, 3600)

        TestSession = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        with patch.object(scheduler_service, "SessionLocal", TestSession):
            result1 = scheduler_service.run_job_now()
            self.assertIsInstance(result1, dict)
            self.assertTrue(result1.get("ok"))
            self.assertIn("ran_at", result1)
            self.assertIn("doc", result1)

            result2 = scheduler_service.run_job_now()
            self.assertIsInstance(result2, dict)
            self.assertTrue(result2.get("ok"))


if __name__ == "__main__":
    unittest.main()
