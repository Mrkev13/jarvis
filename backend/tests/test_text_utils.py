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
from models import ActivityLog, Assignment, Memory, Subject  # noqa: E402
from text_utils import (  # noqa: E402
    days_left_cz, finance_summary_cz, format_czk_cz, format_date_cz, format_hours_cz, format_num_cz,
    memory_count_cz, plural_cz,
)


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


class NumberAndCountTextTestCase(unittest.TestCase):
    """Roadmap 4B.1: desetinná čárka, správná množná čísla, žádné „memory" v textu pro uživatele."""

    def test_czech_numbers(self):
        nb = "\u00a0"
        self.assertEqual(format_num_cz(0.5), "0,5")
        self.assertEqual(format_num_cz(8), "8")
        self.assertEqual(format_num_cz(1250.75), f"1{nb}250,75")
        self.assertEqual(format_num_cz(12.345, 1), "12,3")
        self.assertEqual(format_num_cz(-0.0001), "0")
        self.assertEqual(format_num_cz(None), "–")
        self.assertEqual(format_hours_cz(0.5), f"0,5{nb}h")

    def test_money_and_finance_summary(self):
        nb = "\u00a0"
        self.assertEqual(format_czk_cz(2437.5), f"2{nb}437,50{nb}Kč")
        self.assertEqual(format_czk_cz(4875), f"4{nb}875{nb}Kč")
        self.assertEqual(finance_summary_cz("expense", 189.9, "food", "Oběd"), f"Výdaj 189,90{nb}Kč · food (Oběd)")
        self.assertEqual(finance_summary_cz("income", 2437.5, "work"), f"Příjem 2{nb}437,50{nb}Kč · Práce")
        self.assertEqual(finance_summary_cz("expense", 50, ""), f"Výdaj 50{nb}Kč")

    def test_memory_count_plurals(self):
        self.assertEqual(memory_count_cz(1), "Zohledněna 1 poznámka z paměti")
        self.assertEqual(memory_count_cz(3), "Zohledněny 3 poznámky z paměti")
        self.assertEqual(memory_count_cz(6), "Zohledněno 6 poznámek z paměti")

    def test_weekly_plan_summary_has_no_raw_memory_word(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        db.add(Memory(area="school", category="plan", content="Učit se ráno", importance=8, active=True))
        db.commit()
        summary = ps.generate_plan(db, "weekly", date(2026, 10, 3))["summary"]
        db.close()
        self.assertIn("Zohledněna 1 poznámka z paměti.", summary)
        self.assertNotIn("memory", summary.lower())
        self.assertNotIn("relevantních položek", summary)


class ActivityTextTestCase(unittest.TestCase):
    """Souhrny v Aktivitě: „Práce 0,5 h", „Poznámka v paměti trvale smazána" (ne „-0.5 h", „Pamatka … (hard)")."""

    def setUp(self):
        from unittest import mock

        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.patch = mock.patch("main.SessionLocal", self.Session)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()

    def _summaries(self):
        db = self.Session()
        try:
            return [r.summary for r in db.query(ActivityLog).order_by(ActivityLog.id).all()]
        finally:
            db.close()

    def test_work_session_summaries(self):
        import main
        from models import WorkSession

        main.add_work_session(main.WorkSessionRequest(date=date(2026, 10, 3), hours=0.5, project="ABC",
                                                      hourly_rate=0, sync_to_finance=False))
        main.add_work_session(main.WorkSessionRequest(date=date(2026, 10, 3), hours=6.5, project="XYZ",
                                                      description="Workshop", hourly_rate=375, sync_to_finance=True))
        db = self.Session()
        item_id = db.query(WorkSession).filter_by(project="ABC").one().id
        db.close()
        main.delete_work_session(item_id)
        nb = "\u00a0"
        self.assertEqual(self._summaries(), [
            f"Práce 0,5{nb}h – ABC",
            f"Práce 6,5{nb}h – XYZ (Workshop)",  # MRK-60: žádný „Zapsáno z Práce" do Finance
            f"Smazáno: práce 0,5{nb}h – ABC",
        ])

    def test_memory_hard_delete_summary(self):
        import main

        db = self.Session()
        db.add(Memory(area="school", category="plan", content="Učit se ráno", importance=5, active=True))
        db.commit()
        mid = db.query(Memory).one().id
        db.close()
        main.hard_delete_memory(mid)
        self.assertEqual(self._summaries(), ["Poznámka v paměti trvale smazána: Učit se ráno"])


class PlannerChatTextTestCase(unittest.TestCase):
    """Regrese 4C: textová odpověď chatu na „Co mám dnes dělat?" ukazovala interní klíč „[school]"."""

    def test_action_line_uses_czech_area_label(self):
        from text_utils import area_label_cz, planner_action_line

        line = planner_action_line(1, {"area": "school", "title": "Připravit se na zkoušku: test"})
        self.assertEqual(line, "1. Připravit se na zkoušku: test (Škola)")
        self.assertNotIn("[", line)
        self.assertEqual(planner_action_line(2, {"area": "", "title": "Bez oblasti"}), "2. Bez oblasti")
        self.assertEqual(area_label_cz("WOT"), "World of Tanks")
        self.assertEqual(area_label_cz("zahrada"), "Zahrada")

    def test_area_labels_match_frontend(self):
        import re
        from pathlib import Path
        from text_utils import AREA_LABELS_CZ

        src = (Path(__file__).resolve().parents[2] / "frontend" / "lib" / "areas.ts").read_text(encoding="utf-8")
        frontend = dict(re.findall(r'^\s+([a-z_]+):\s+\{[^}]*label: "([^"]+)"', src, re.M))
        self.assertEqual(AREA_LABELS_CZ, frontend)
