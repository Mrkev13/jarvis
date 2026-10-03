"""Roadmap 4B: text pro uživatele – česká data a dny místo ISO a anglických slov."""
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

import notifications_service as ns  # noqa: E402
import planner_service as ps  # noqa: E402
from database import Base  # noqa: E402
from models import Assignment, Subject  # noqa: E402
from text_utils import days_left_cz, format_date_cz, plural_cz  # noqa: E402


class TextUtilsTestCase(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(format_date_cz(date(2026, 10, 2)), "2. 10. 2026")
        self.assertEqual([days_left_cz(n) for n in (0, 1, 3, 5)], ["dnes", "zítra", "zbývají 3 dny", "zbývá 5 dní"])
        self.assertEqual(plural_cz(2, "den", "dny", "dní"), "dny")


class PresentationTextTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        s = Subject(name="M")
        self.db.add(s)
        self.db.flush()
        self.db.add_all([Assignment(title="Sada", subject_id=s.id, status="todo", due_date=date(2026, 10, 2)),
                         Assignment(title="Esej", subject_id=s.id, status="todo", due_date=date(2026, 10, 6))])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_planner_reasons_use_czech_dates_and_words(self):
        actions = ps._deadline_actions_for_assignments("daily", self.db, date(2026, 10, 3))
        text = " ".join(f"{a.title} {a.reason}" for a in actions)
        self.assertIn("Dokončit úkol po termínu: Sada", text)
        self.assertIn("Termín byl 2. 10. 2026 (po termínu).", text)
        self.assertIn("Termín 6. 10. 2026 (zbývají 3 dny).", text)
        self.assertNotIn("2026-10", text)
        self.assertNotIn("overdue", text.lower())

    def test_notification_texts_use_czech_dates_and_words(self):
        overdue = ns._deadline_candidates_for_assignment(self.db.query(Assignment).filter_by(title="Sada").one(),
                                                         date(2026, 10, 3))
        soon = ns._deadline_candidates_for_assignment(self.db.query(Assignment).filter_by(title="Esej").one(),
                                                      date(2026, 10, 3))
        self.assertEqual((overdue.title, overdue.message), ("Po termínu: Sada", "Úkol měl termín 2. 10. 2026 a je po termínu."))
        self.assertEqual((soon.title, soon.message), ("Termín: Esej", "Termín úkolu je 6. 10. 2026 (zbývají 3 dny)."))
        self.assertEqual(overdue.dedupe_key, "assignment_overdue:1", "dedupe klíč beze změny")


if __name__ == "__main__":
    unittest.main()
