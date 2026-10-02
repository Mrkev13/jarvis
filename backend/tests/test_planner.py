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
from models import Assignment, Goal, PlannerRecommendationHistory, Subject
from goal_history_service import record_goal_progress_snapshot
from planner_service import generate_plan


class PlannerTestCase(unittest.TestCase):
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

    def test_daily_planner_overdue_first(self):
        today = date(2026, 9, 11)
        a = Assignment(
            title="Overdue HW",
            description="",
            due_date=today - timedelta(days=1),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add(a)
        self.db.commit()

        plan = generate_plan(self.db, mode="daily", today=today)
        self.db.commit()
        self.assertEqual(plan["mode"], "daily")
        self.assertTrue(len(plan["actions"]) >= 1)
        self.assertIn("overdue", plan["actions"][0]["title"].lower())

    def test_weekly_planner_deadline_14(self):
        today = date(2026, 9, 11)
        a = Assignment(
            title="Week HW",
            description="",
            due_date=today + timedelta(days=14),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add(a)
        self.db.commit()

        plan = generate_plan(self.db, mode="weekly", today=today)
        self.db.commit()
        titles = [x["title"] for x in plan["actions"]]
        self.assertTrue(any("Week HW" in t for t in titles))

    def test_goal_review(self):
        today = date(2026, 9, 11)
        g = Goal(area="work", title="G", description="", status="active", priority="high", progress=0, tracking_type="manual")
        self.db.add(g)
        self.db.commit()

        record_goal_progress_snapshot(self.db, g.id, 10, None, recorded_at=datetime(2026, 9, 1))
        record_goal_progress_snapshot(self.db, g.id, 10, None, recorded_at=datetime(2026, 9, 2))
        self.db.commit()

        review = generate_plan(self.db, mode="goal_review", today=today)
        self.db.commit()
        self.assertEqual(review["mode"], "goal_review")
        self.assertEqual(len(review["goals"]), 1)
        self.assertIn("days_since_last_positive", review["goals"][0])

    def test_planner_recommendation_history_dedupe(self):
        today = date(2026, 9, 11)
        a = Assignment(
            title="Repeat HW",
            description="",
            due_date=today + timedelta(days=3),
            priority="medium",
            status="todo",
            subject_id=self.subject_id,
        )
        self.db.add(a)
        self.db.commit()

        plan1 = generate_plan(self.db, mode="daily", today=today)
        self.db.commit()
        count1 = self.db.query(PlannerRecommendationHistory).count()
        self.assertGreater(count1, 0)

        plan2 = generate_plan(self.db, mode="daily", today=today)
        self.db.commit()
        count2 = self.db.query(PlannerRecommendationHistory).count()
        self.assertEqual(count2, count1)

        reasons = " ".join(a["reason"] for a in plan2["actions"])
        self.assertIn("Stále platí:", reasons)


if __name__ == "__main__":
    unittest.main()
