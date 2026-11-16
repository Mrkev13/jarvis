"""MRK-84: správnost vyhledávání a paměti.

- paměť se hledá v celém textu (dřív jen v prvních 79 znacích titulku);
- vyhledávání načte nanejvýš ROW_LIMIT řádků na zdroj, s deterministickým pořadím; u studijních materiálů jen úryvek
  textu ze SQL, nikdy celý extrahovaný dokument;
- druh vzpomínky (fact / temporary / decision) a platnost: vypršená vzpomínka se nedostane do promptu, planneru,
  read toolu ani do vyhledávání;
- přesná duplicita aktivní vzpomínky se neuloží znovu.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import core_integrations  # noqa: E402
import memory_service  # noqa: E402
import planner_service  # noqa: E402
import search_service as ss  # noqa: E402
import tools  # noqa: E402
from context_service import build_current_context  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Memory  # noqa: E402
from modules.school.models import StudyCourse, StudyMaterial  # noqa: E402

NOW = datetime(2026, 11, 15, 12, 0)
LONG = ("Poznámka k diplomové práci, kterou je potřeba dodělat před konzultací s vedoucím v prosinci, "
        "a hlavně nezapomenout na kapitolu o kvantovém tunelování.")


class MemoryLifecycleTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._patches = [patch.object(tools, "SessionLocal", self.Session),
                         patch.object(memory_service, "utc_now", lambda: NOW)]
        for p in self._patches:
            p.start()
        self.statements: list[str] = []
        event.listen(self.engine, "before_cursor_execute", self._capture)

    def tearDown(self):
        event.remove(self.engine, "before_cursor_execute", self._capture)
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _capture(self, conn, cursor, statement, *args):
        self.statements.append(" ".join(statement.split()))

    def add(self, **kw):
        db = self.Session()
        m = Memory(**{"area": "school", "category": "plan", "importance": 5, "active": True, **kw})
        db.add(m)
        db.commit()
        mid = m.id
        db.close()
        return mid

    def search(self, q):
        db = self.Session()
        try:
            return [r for r in ss.search(db, q)["results"] if r["type"] == "memory"]
        finally:
            db.close()

    # ---------- vyhledávání ----------

    def test_keyword_after_the_80th_character_is_found(self):
        mid = self.add(content=LONG)
        self.assertGreater(LONG.index("tunelování"), 80)
        hits = self.search("tunelovani")
        self.assertEqual([r["id"] for r in hits], [f"memory:{mid}"])
        self.assertTrue(hits[0]["title"].endswith("…"), "titulek zůstává zkrácený, hledá se v celém textu")

    def test_memory_search_is_bounded_and_ordered(self):
        for i in range(8):
            self.add(content=f"Poznámka číslo {i} o fyzice", updated_at=NOW - timedelta(days=i))
        with patch.object(core_integrations, "ROW_LIMIT", 3):
            db = self.Session()
            try:
                self.statements.clear()
                rows = list(core_integrations.search_memories(db, "fyzice"))
            finally:
                db.close()
        self.assertEqual(len(rows), 3, "nanejvýš ROW_LIMIT řádků")
        self.assertEqual([r[2] for r in rows], [f"Poznámka číslo {i} o fyzice" for i in range(3)], "nejnovější první")
        sql = next(s for s in self.statements if "FROM memories" in s)
        self.assertIn("ORDER BY", sql)
        self.assertIn("LIMIT", sql)

    def test_study_material_search_never_loads_the_full_text(self):
        db = self.Session()
        course = StudyCourse(source="moodle", external_id="1", name="Fyzika I", short_name="FYZ1")
        db.add(course)
        db.flush()
        db.add(StudyMaterial(course_id=course.id, external_id="1:/a.pdf", module_external_id="1", title="Skripta",
                             file_name="a.pdf", material_type="pdf", download_status="stored",
                             extracted_text="úvod " + "výplň " * 2000 + "schovanéslovo"))
        db.add(StudyMaterial(course_id=course.id, external_id="1:/b.pdf", module_external_id="1", title="Cvičení",
                             file_name="b.pdf", material_type="pdf", download_status="stored",
                             extracted_text="zadání: kvantové tunelování"))
        db.commit()
        db.close()
        self.statements.clear()
        db = self.Session()
        try:
            found = [r for r in ss.search(db, "tunelovani")["results"] if r["type"] == "study_material"]
            deep = [r for r in ss.search(db, "schovaneslovo")["results"] if r["type"] == "study_material"]
        finally:
            db.close()
        self.assertEqual([r["title"] for r in found], ["Cvičení"], "úryvek se prohledává")
        self.assertEqual(deep, [], "text za hranicí úryvku se nenačítá ani neprohledává")
        material_sql = [s for s in self.statements if "FROM study_materials" in s]
        self.assertTrue(material_sql)
        for s in material_sql:
            self.assertIn("substr(study_materials.extracted_text", s)
            self.assertNotIn("study_materials.extracted_text AS study_materials_extracted_text", s)
            self.assertIn("LIMIT", s)
        self.assertFalse([s for s in self.statements if "FROM study_courses" in s and "IN (" not in s],
                         "kurzy jen pro nalezené materiály")

    # ---------- druh a platnost ----------

    def test_expired_memory_is_used_nowhere(self):
        self.add(content="Tento týden je výjimečně konzultace ve středu.", kind="temporary",
                 expires_at=NOW - timedelta(hours=1), importance=10)
        self.add(content="Příští týden je konzultace výjimečně v pátek.", kind="temporary",
                 expires_at=NOW + timedelta(days=3), importance=10)
        db = self.Session()
        try:
            ctx = build_current_context(db, "kdy je konzultace", now_utc=NOW)
            planner = planner_service._relevant_memories(db)
        finally:
            db.close()
        self.assertNotIn("ve středu", ctx.text)
        self.assertIn("v pátek", ctx.text)
        self.assertEqual([m["content"] for m in planner], ["Příští týden je konzultace výjimečně v pátek."])
        self.assertEqual([m["content"] for m in tools.get_memories()], ["Příští týden je konzultace výjimečně v pátek."])
        self.assertEqual([r["title"] for r in self.search("konzultace")],
                         ["Příští týden je konzultace výjimečně v pátek."])

    def test_kind_validation_and_defaults(self):
        saved = tools.save_memory(content="Fakt bez druhu")
        self.assertEqual((saved["kind"], saved["expires_at"]), ("fact", None))
        with self.assertRaises(memory_service.MemoryError):
            tools.save_memory(content="Dočasná bez data", kind="temporary")
        with self.assertRaises(memory_service.MemoryError):
            tools.save_memory(content="Neznámý druh", kind="rumour")
        saved = tools.save_memory(content="Do pátku", kind="temporary", expires_at=NOW + timedelta(days=2))
        self.assertEqual(saved["kind"], "temporary")
        decision = tools.save_memory(content="Rozhodnuto: zkouška v lednu", kind="Decision")
        self.assertEqual(decision["kind"], "decision")

    def test_existing_rows_default_to_fact(self):
        mid = self.add(content="Stará vzpomínka")
        db = self.Session()
        try:
            self.assertEqual(db.get(Memory, mid).kind, "fact")
        finally:
            db.close()

    # ---------- duplicity ----------

    def test_exact_duplicate_is_not_saved_again(self):
        first = tools.save_memory(content="Preferuju  krátké odpovědi.")
        again = tools.save_memory(content="  preferuju krátké ODPOVĚDI. ", area="general")
        self.assertTrue(again["deduplicated"])
        self.assertEqual(again["id"], first["id"])
        db = self.Session()
        try:
            self.assertEqual(db.query(Memory).count(), 1)
            self.assertEqual(db.query(ActivityLog).filter_by(entity_type="Memory").count(), 1, "duplicita = bez zápisu")
        finally:
            db.close()

    def test_inactive_or_different_text_is_not_a_duplicate(self):
        self.add(content="Stará vypnutá věc", active=False)
        self.assertNotIn("deduplicated", tools.save_memory(content="Stará vypnutá věc"))
        self.assertNotIn("deduplicated", tools.save_memory(content="Stará vypnutá věc!"))


if __name__ == "__main__":
    unittest.main()
