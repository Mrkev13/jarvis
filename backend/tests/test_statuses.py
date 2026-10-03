"""Roadmap 3.5: kanonické stavy (statuses.py) – jedna definice pro všechny pohledy."""
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import briefing_snapshot  # noqa: E402
import context_service  # noqa: E402
import read_queries  # noqa: E402
import reminder_service  # noqa: E402
import statuses  # noqa: E402
import weekly_snapshot  # noqa: E402
from database import Base  # noqa: E402
from goal_history_service import compute_automatic_goal_current_value_with_ok  # noqa: E402
from models import Assignment, Exam, Subject  # noqa: E402


class CanonicalStatusesTestCase(unittest.TestCase):
    def test_predicates_normalize(self):
        self.assertTrue(statuses.is_assignment_done(" Finished "))
        self.assertTrue(statuses.is_assignment_done("HOTOVO"))
        self.assertFalse(statuses.is_assignment_done("todo"))
        self.assertTrue(statuses.is_exam_open(None))
        self.assertFalse(statuses.is_exam_open("passed"))
        self.assertTrue(statuses.is_goal_inactive("Paused"))
        self.assertFalse(statuses.is_goal_inactive("active"))

    def test_modules_share_the_canonical_sets(self):
        self.assertIs(read_queries.ASSIGNMENT_DONE_STATUSES, statuses.ASSIGNMENT_DONE_STATUSES)
        self.assertIs(read_queries.EXAM_OPEN_STATUSES, statuses.EXAM_OPEN_STATUSES)
        self.assertIs(briefing_snapshot._EXAM_OPEN, statuses.EXAM_OPEN_STATUSES)
        self.assertIs(briefing_snapshot._GOAL_INACTIVE, statuses.GOAL_INACTIVE_STATUSES)
        self.assertIs(context_service._EXAM_OPEN_STATUSES, statuses.EXAM_OPEN_STATUSES)
        self.assertIs(context_service._INACTIVE_GOAL_STATUSES, statuses.GOAL_INACTIVE_STATUSES)
        self.assertIs(weekly_snapshot._GOAL_INACTIVE, statuses.GOAL_INACTIVE_STATUSES)
        self.assertEqual(reminder_service.ACTIVE_STATUSES,
                         (reminder_service.STATUS_SCHEDULED, reminder_service.STATUS_FIRED))


class AutomaticGoalStatusTestCase(unittest.TestCase):
    """Automatické cíle počítaly „finished" jako otevřený úkol (vlastní seznam bez „finished")."""

    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        s = Subject(name="Matematika")
        self.db.add(s)
        self.db.flush()
        for st in ("finished", " Done ", "todo", "hotovo"):
            self.db.add(Assignment(title=f"Úkol {st}", subject_id=s.id, status=st))
        for st in ("passed", "failed", "upcoming"):
            self.db.add(Exam(title=f"Zkouška {st}", subject_id=s.id, status=st))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_finished_counts_as_completed_everywhere(self):
        done, ok = compute_automatic_goal_current_value_with_ok(self.db, "school_completed_assignments")
        self.assertEqual((done, ok), (3.0, True))
        open_, _ = compute_automatic_goal_current_value_with_ok(self.db, "school_open_assignments")
        self.assertEqual(open_, 1.0)
        passed, _ = compute_automatic_goal_current_value_with_ok(self.db, "school_exams_passed")
        self.assertEqual(passed, 1.0)


if __name__ == "__main__":
    unittest.main()
