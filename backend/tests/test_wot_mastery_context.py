"""MRK-94: Jarvis knows the WoT M-ka (odznak Mistr) – a deterministic summary in the WoT AI context, and the words
people use for them („M-ek", „Mko", „Mistr", „ocenění") route the question to WoT. No LLM."""
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

from context_service import classify_areas  # noqa: E402
from database import Base  # noqa: E402
from models import WotMilestone  # noqa: E402
from module_contracts import ContextRequest  # noqa: E402
from wot_integrations import context_wot  # noqa: E402


class WotMasteryContextTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def context(self):
        return "\n".join(context_wot(ContextRequest(self.db, date(2026, 10, 27), datetime(2026, 10, 27, 20))))

    def add(self, tank, mastery, played_on=None):
        self.db.add(WotMilestone(milestone_type="mastery", tank=tank, mastery=mastery, played_on=played_on))

    def test_summary_ranks_tanks_by_ace_count_including_repeats(self):
        for day in (1, 9, 20):
            self.add("Kranvagn", "ace", date(2026, 10, day))
        self.add("Škoda T 56", "ace", date(2026, 10, 25))
        self.add("Progetto 65", "ace")
        self.add("IS-7", "first", date(2026, 10, 26))
        self.add("T-62A", None)          # memorable battle without a badge
        self.db.commit()
        text = self.context()
        self.assertIn("WoT M-ka (odznak Mistr): celkem 5 na 3 tancích; podle počtu: Kranvagn 3×; "
                      "Progetto 65 1×; Škoda T 56 1×", text)
        self.assertIn("WoT poslední M-ko: Škoda T 56 2026-10-25", text)
        self.assertIn("WoT ostatní odznaky zvládnutí: I. třída 1×", text)

    def test_no_aces_says_so(self):
        self.add("IS-7", "first")
        self.db.commit()
        self.assertIn("WoT M-ka (odznak Mistr): žádná zapsaná.", self.context())

    def test_the_words_for_m_ka_route_to_wot(self):
        for question in ("Jaký tank má nejvíce Mek", "M-ek takhle lepší?", "Kolik mám Mko?", "kolik mám M-ka",
                         "ve wot ocenění", "na čem mám nejvíc Mistrů", "odznak zvládnutí"):
            self.assertIn("wot", classify_areas(question), question)
        for question in ("ahoj", "mám ekonomiku zítra", "smekám čepici"):
            self.assertNotIn("wot", classify_areas(question), question)


if __name__ == "__main__":
    unittest.main()
