"""Regrese (Phase F live, 2026-10-03): zkouška se stavem „passed" s termínem dnes.

Denní přehled (stejně jako CURRENT STATE a AI read tooly) bere jen otevřené zkoušky (upcoming/scheduled/prázdný
stav), ale dashboard plánovač a deadline upozornění stav ignorovaly → „Připravit se na zkoušku" a „Deadline:"
u už složené zkoušky, zatímco přehled hlásil klidný den. Teď všechny pohledy používají stejnou definici.
"""
import json
import os
import sys
import unittest
from datetime import date, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import briefing_service as bs  # noqa: E402
import notifications_service as ns  # noqa: E402
import planner_service as ps  # noqa: E402
from briefing_snapshot import build_snapshot  # noqa: E402
from database import Base  # noqa: E402
from models import DailyBriefing, Exam, Notification, Subject  # noqa: E402
from time_utils import local_to_utc  # noqa: E402

TODAY = date(2026, 10, 3)
NOW = local_to_utc(datetime(2026, 10, 3, 11, 0))


class ExamStatusConsistencyTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.subject = Subject(name="Foundations of Law")
        self.db.add(self.subject)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def exam(self, title, day, status="upcoming"):
        e = Exam(title=title, subject_id=self.subject.id, status=status, exam_date=day, exam_type="test")
        self.db.add(e)
        self.db.commit()
        return e

    # --- dashboard plánovač ---
    def test_planner_skips_passed_and_failed_exams(self):
        self.exam("složená", TODAY, "passed")
        self.exam("neúspěšná", TODAY, "failed")
        self.exam("otevřená", TODAY, "upcoming")
        titles = [a.title for a in ps._deadline_actions_for_exams("daily", self.db, TODAY)]
        self.assertEqual(len(titles), 1, titles)
        self.assertIn("otevřená", titles[0])

    # --- deadline upozornění ---
    def test_deadline_notification_only_for_open_exam_and_stale_one_resolved(self):
        passed = self.exam("zkouska", TODAY, "upcoming")
        ns.generate_notifications(self.db, today=TODAY)
        self.db.commit()
        open_notes = self.db.query(Notification).filter_by(source_type="exam", resolved=False).all()
        self.assertEqual(len(open_notes), 1)
        passed.status = "passed"  # zkouška se označí jako složená
        self.db.commit()
        ns.generate_notifications(self.db, today=TODAY)
        self.db.commit()
        self.assertEqual(self.db.query(Notification).filter_by(source_type="exam", resolved=False).count(), 0)
        self.assertIsNone(ns._deadline_candidates_for_exam(passed, TODAY))

    # --- Denní přehled: otevřená zkouška dnes ---
    def test_open_exam_today_is_in_briefing_today_and_day_is_not_quiet(self):
        self.exam("zkouska", TODAY)
        snap = build_snapshot(self.db, NOW)
        self.assertEqual([i.label for i in snap.sections["today"]], ["zkouska (Foundations of Law)"])
        self.assertFalse(snap.is_quiet)
        calls = []

        def fake_llm(messages, max_tokens):
            calls.append(messages)
            ref = snap.sections["today"][0].ref
            return json.dumps({"summary": "Dnes máš zkoušku.", "priorities": [{"ref": ref, "title": "Zkouška",
                                                                                "why": ""}],
                               "watch": [], "upcoming": [], "note": None}), {"model": "fake"}

        row = bs.generate(self.db, trigger="manual", now=NOW, llm=fake_llm)
        self.assertEqual(len(calls), 1, "klidný den (deterministická zkratka) nesmí proběhnout")
        self.assertNotEqual(row.model, "deterministic")
        self.assertFalse(json.loads(row.content)["quiet"])
        self.assertEqual(self.db.query(DailyBriefing).count(), 1)

    def test_tomorrow_soon_yesterday_and_no_duplicates(self):
        self.exam("včera", date(2026, 10, 2))
        self.exam("dnes", TODAY)
        self.exam("zítra", date(2026, 10, 4))
        snap = build_snapshot(self.db, NOW)
        today = [i.label.split(" (")[0] for i in snap.sections["today"]]
        soon = [i.label.split(" (")[0] for i in snap.sections["soon"]]
        self.assertEqual(today, ["dnes"])
        self.assertEqual(soon, ["zítra"])
        self.assertNotIn("včera", today + soon)  # proběhlá zkouška do přehledu nepatří
        refs = [i.ref for s in ("today", "soon", "overdue") for i in snap.sections[s]]
        self.assertEqual(len(refs), len(set(refs)))

    def test_passed_exam_today_keeps_briefing_quiet(self):
        self.exam("zkouska", TODAY, "passed")
        self.assertTrue(build_snapshot(self.db, NOW).is_quiet)


if __name__ == "__main__":
    unittest.main()
