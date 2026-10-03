"""Regrese (Phase F live, 2026-10-03): reálná AI poznámka „Přidány dvě nové zkoušky (activity:117, activity:116)."
Interní odkazy snímku slouží k uzemnění a odkazům, ale do textu pro uživatele nepatří."""
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
from briefing_snapshot import build_snapshot  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Exam, Subject  # noqa: E402
from time_utils import local_to_utc  # noqa: E402

NOW = local_to_utc(datetime(2026, 10, 3, 11, 50))


class StripRefsTestCase(unittest.TestCase):
    def test_live_note_loses_raw_refs(self):
        self.assertEqual(bs._strip_refs("Přidány dvě nové zkoušky (activity:117, activity:116)."),
                         "Přidány dvě nové zkoušky.")

    def test_every_ref_kind_and_bracket_form_is_removed(self):
        for raw, expected in (
            ("Odevzdej úkol assignment:12 dnes.", "Odevzdej úkol dnes."),
            ("Zkouška [exam:2] je dnes.", "Zkouška je dnes."),
            ("Fyzio (reminder:5) v 18:00.", "Fyzio v 18:00."),
            ("Cíl goal:1, upozornění notification:9 a finance:2026-10.", "Cíl, upozornění a."),
            ("Viz activity:117; activity:116", "Viz"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(bs._strip_refs(raw), expected)

    def test_human_text_is_preserved(self):
        for text in ("Dnes máte zkoušku z angličtiny v 10:30.", "Cíl 150 000 Kč je na 10 %.",
                     "Poměr 3:1 a čas 07:00 zůstávají.", "Úkol (důležitý) je dnes."):
            with self.subTest(text=text):
                self.assertEqual(bs._strip_refs(text), text)


class GroundRefsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        db = sessionmaker(bind=self.engine)()
        s = Subject(name="English in IT")
        db.add(s)
        db.flush()
        self.exam = Exam(title="Test", subject_id=s.id, status="upcoming", exam_date=date(2026, 10, 3), exam_type="test")
        db.add(self.exam)
        db.add(ActivityLog(timestamp=NOW, area="school", action_type="create", summary="Zkouška přidána: Test"))
        db.commit()
        self.snap = build_snapshot(db, NOW)
        db.close()

    def tearDown(self):
        self.engine.dispose()

    def test_visible_text_has_no_refs_but_structured_refs_remain(self):
        ref = self.snap.sections["today"][0].ref
        act = self.snap.sections["changes"][0].ref
        data = {
            "summary": f"Dnes máte zkoušku ({ref}).",
            "priorities": [{"ref": ref, "title": f"Test {ref}", "why": f"Termín je dnes [{ref}]."}],
            "watch": [], "upcoming": [],
            "note": f"Přidána nová zkouška ({act}).",
        }
        content, _ = bs.ground(data, self.snap)
        visible = " ".join([content["summary"], content["note"] or "", content["priorities"][0]["text"],
                            content["priorities"][0]["why"]])
        for kind in ("exam:", "activity:", "assignment:", "reminder:"):
            self.assertNotIn(kind, visible)
        self.assertEqual(content["summary"], "Dnes máte zkoušku.")
        self.assertEqual(content["note"], "Přidána nová zkouška.")
        self.assertEqual(content["priorities"][0]["text"], "Test")
        self.assertEqual(content["priorities"][0]["why"], "Termín je dnes.")
        self.assertEqual(content["priorities"][0]["ref"], ref)  # interně zůstává pro odkaz/uzemnění


class StoredBriefingDisplayTestCase(unittest.TestCase):
    def test_already_saved_briefing_is_shown_without_refs(self):
        stored = {"summary": "Dnes máte zkoušku (exam:2).", "note": "Přidány dvě nové zkoušky (activity:117, activity:116).",
                  "priorities": [{"ref": "exam:2", "text": "Test [exam:2]", "why": "Dnes."}],
                  "watch": [{"ref": "goal:1", "text": "Úspora goal:1"}], "upcoming": [], "quiet": False}
        shown = bs._clean_visible(stored)
        self.assertEqual(shown["note"], "Přidány dvě nové zkoušky.")
        self.assertEqual(shown["summary"], "Dnes máte zkoušku.")
        self.assertEqual(shown["priorities"][0]["text"], "Test")
        self.assertEqual(shown["watch"][0]["text"], "Úspora")
        self.assertEqual(shown["priorities"][0]["ref"], "exam:2")


if __name__ == "__main__":
    unittest.main()
