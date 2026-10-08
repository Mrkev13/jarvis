"""Regrese: hotové úkoly (done/completed/hotovo/…) se dál objevovaly v plánovači, deadline upozorněních
a v dashboardu (tam jen „completed"/„done"). Všechny pohledy teď používají read_queries.ASSIGNMENT_DONE_STATUSES
(a pro zkoušky EXAM_OPEN_STATUSES)."""
import os
import sys
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import briefing_snapshot  # noqa: E402
import school_integrations  # noqa: E402
import main  # noqa: E402
import mutation_service  # noqa: E402
import notifications_service as ns  # noqa: E402
import planner_service as ps  # noqa: E402
from database import Base  # noqa: E402
from models import Assignment, Exam, Notification, Subject  # noqa: E402
from read_queries import ASSIGNMENT_DONE_STATUSES  # noqa: E402

TODAY = date(2026, 10, 3)
DONE_SPELLINGS = ("done", "completed", "hotovo", "closed", "finished", "Done", " HOTOVO ")


class AssignmentStatusConsistencyTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.subject = Subject(name="Matematika")
        self.db.add(self.subject)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add(self, title, status, due):
        a = Assignment(title=title, subject_id=self.subject.id, status=status, due_date=due)
        self.db.add(a)
        self.db.commit()
        return a

    def test_single_canonical_definition(self):
        self.assertIs(briefing_snapshot._DONE, ASSIGNMENT_DONE_STATUSES)
        self.assertIs(school_integrations.ASSIGNMENT_DONE_STATUSES, ASSIGNMENT_DONE_STATUSES)  # AI kontext (MRK-20)
        self.assertIs(mutation_service._ASSIGNMENT_DONE, ASSIGNMENT_DONE_STATUSES)

    def test_planner_skips_every_done_spelling_but_keeps_open(self):
        for i, st in enumerate(DONE_SPELLINGS):
            self.add(f"hotový {i}", st, date(2026, 10, 1))  # po termínu
        self.add("otevřený", "todo", date(2026, 10, 1))
        self.add("rozpracovaný", "in_progress", date(2026, 10, 4))
        titles = " | ".join(a.title for a in ps._deadline_actions_for_assignments("daily", self.db, TODAY))
        self.assertNotIn("hotový", titles)
        self.assertIn("otevřený", titles)
        self.assertIn("rozpracovaný", titles)

    def test_deadline_notification_resolved_when_done_and_back_when_reopened(self):
        a = self.add("Esej", "todo", date(2026, 10, 1))
        ns.generate_notifications(self.db, today=TODAY)
        self.db.commit()
        open_notes = lambda: self.db.query(Notification).filter_by(source_type="assignment", resolved=False).count()
        self.assertEqual(open_notes(), 1)
        a.status = "hotovo"
        self.db.commit()
        ns.generate_notifications(self.db, today=TODAY)
        self.db.commit()
        self.assertEqual(open_notes(), 0, "zastaralé upozornění se vyřeší")
        self.assertIsNone(ns._deadline_candidates_for_assignment(a, TODAY))
        a.status = "todo"  # znovu otevřený úkol je zase způsobilý
        self.db.commit()
        ns.generate_notifications(self.db, today=TODAY)
        self.db.commit()
        self.assertEqual(open_notes(), 1)

    def test_dashboard_upcoming_uses_canonical_statuses(self):
        for i, st in enumerate(DONE_SPELLINGS):
            self.add(f"hotový {i}", st, date(2026, 10, 5))
        self.add("otevřený", "todo", date(2026, 10, 5))
        for title, st in (("složená", "passed"), ("neúspěšná", "failed"), ("nadcházející", "upcoming")):
            self.db.add(Exam(title=title, subject_id=self.subject.id, status=st, exam_date=date(2026, 10, 6), exam_type="test"))
        self.db.commit()
        titles = [e["title"] for e in main._get_upcoming(self.db, limit=50, today=TODAY)]
        self.assertEqual(sorted(titles), ["nadcházející", "otevřený"], titles)


if __name__ == "__main__":
    unittest.main()
