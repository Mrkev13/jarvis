"""Roadmap 4D: globální vyhledávání – normalizace, řazení, limity, auth a žádné interní údaje."""
import os
import sys
import unittest
from datetime import date, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import main  # noqa: E402
import search_service as ss  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    Assignment, AuthSession, Conversation, Exam, FinanceTransaction, Goal, Memory, Message, MffCharacter,
    PendingAction, PushSubscription, Reminder, Subject, WorkSession, WotGrind,
)


class NormalizeAndScoreTestCase(unittest.TestCase):
    def test_czech_normalization(self):
        self.assertEqual(ss.normalize("  Zkouška  FYZIKA "), "zkouska fyzika")
        self.assertEqual(ss.normalize("Připomínka"), "pripominka")
        self.assertEqual(ss.normalize("Práce"), "prace")
        self.assertEqual(ss.normalize(None), "")

    def test_ranking_order(self):
        q = "luna"
        exact = ss.score_text(q, "Luna")
        prefix = ss.score_text(q, "Luna Snow")
        word = ss.score_text(q, "Captain Luna")
        sub = ss.score_text(q, "Lunatic")  # začátek slova i titulku → prefix
        inner = ss.score_text(q, "Kalunas")
        extra = ss.score_text(q, "Postava", "luna snow")
        self.assertGreater(exact, prefix)
        self.assertEqual(sub, prefix)
        self.assertGreater(prefix, word)
        self.assertGreater(word, inner)
        self.assertGreater(inner, extra)
        self.assertGreater(extra, 0)
        self.assertEqual(ss.score_text(q, "Thor"), 0)
        self.assertGreater(ss.score_text("snow luna", "Luna Snow"), 0, "slova v jiném pořadí")


class SearchTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        db = self.Session()
        fyz = Subject(name="Fyzika", code="FYZ1", semester="ZS 2026", credits=5)
        db.add(fyz)
        db.flush()
        db.add_all([
            Exam(title="test", subject_id=fyz.id, exam_type="test", exam_date=date(2026, 10, 3)),
            Exam(title="Zkouška fyzika", subject_id=fyz.id, exam_type="exam", exam_date=date(2026, 10, 15)),
            Assignment(title="Laboratorní protokol", subject_id=fyz.id, due_date=date(2026, 10, 16)),
            Reminder(title="Zalít květiny", due_at=datetime(2026, 10, 12, 6, 0), status="scheduled"),
            Reminder(title="Zalít kaktus", due_at=datetime(2026, 10, 1, 6, 0), status="done"),
            WorkSession(date=date(2026, 10, 2), hours=6.5, project="Klient XYZ", description="Workshop", hourly_rate=375),
            FinanceTransaction(amount=189.9, category="food", description="Oběd", transaction_type="expense", created_at=datetime(2026, 10, 2, 10)),
            FinanceTransaction(amount=2437.5, category="work", description="", transaction_type="income", created_at=datetime(2026, 10, 2, 11)),
            Goal(area="finance", title="Rezerva na tři měsíce", progress=40),
            Memory(area="school", category="plan", content="Zkoušku z fyziky dát v prvním termínu.", active=True),
            Memory(area="general", category="context", content="Tajná stará poznámka", active=False),
            WotGrind(tank="TVP T 50/51", xp_remaining=52000, priority="high"),
            MffCharacter(name="Luna Snow", tier="T4", level=80, status="built", uniform="Neon"),
            # interní data – nesmí se nikdy objevit ve výsledcích
            Conversation(title="Tajná konverzace"),
            PendingAction(tool="add_work_session", arguments='{"project": "Tajný"}', status="pending"),
            PushSubscription(endpoint_hash="x" * 64, endpoint="https://push.example/Tajny-endpoint", p256dh="k", auth="a"),
            AuthSession(token_hash="tajny-token-hash", expires_at=datetime(2030, 1, 1)),
        ])
        db.flush()
        db.add(Message(conversation_id=1, role="user", content="Tajná zpráva"))
        db.commit()
        db.close()

    def tearDown(self):
        self.engine.dispose()

    def _search(self, q, **kw):
        db = self.Session()
        try:
            return ss.search(db, q, **kw)
        finally:
            db.close()

    def test_representative_module_results(self):
        cases = {
            "test": ("exam", "/school?exam=1", "school"),
            "luna": ("mff_character", "/mff?character=1", "mff"),
            "tvp": ("wot_grind", "/wot?grind=1", "wot"),
            "zalit kvetiny": ("reminder", "/reminders?reminder=1", "reminders"),
            "klient": ("work_session", "/work?session=1", "work"),
            "obed": ("transaction", "/finance?transaction=1", "finance"),
            "rezerva": ("goal", "/goals?goal=1", "goals"),
            "fyziky": ("memory", "/memory?memory=1", "memory"),
            "fyzika": ("subject", "/school?subject=1", "school"),
        }
        for q, (typ, href, area) in cases.items():
            top = self._search(q)["results"][0]
            self.assertEqual((top["type"], top["href"], top["area"]), (typ, href, area), q)
            self.assertEqual(set(top), {"id", "type", "title", "subtitle", "area", "href", "score"})

    def test_subtitles_are_czech(self):
        exam = self._search("test")["results"][0]
        self.assertEqual(exam["subtitle"], "Test · Fyzika · 3. 10. 2026")
        income = [r for r in self._search("prace")["results"] if r["type"] == "transaction"][0]
        self.assertIn("Práce", income["title"])  # systémová kategorie „work" česky
        memory = self._search("fyziky")["results"][0]
        self.assertEqual(memory["subtitle"], "Paměť · Plán · Škola")

    def test_inactive_and_done_records_are_not_indexed(self):
        self.assertEqual([r for r in self._search("tajna")["results"]], [])
        self.assertEqual([r["title"] for r in self._search("kaktus")["results"]], [])

    def test_no_internal_data_leaks(self):
        for q in ("tajn", "endpoint", "token", "push.example", "add_work_session", "konverzace"):
            results = self._search(q)["results"]
            self.assertTrue(all(r["type"] in {"subject", "assignment", "exam", "reminder", "work_session", "transaction", "goal", "memory", "wot_grind", "mff_character"} for r in results))
            self.assertFalse(any("Tajn" in r["title"] or "endpoint" in r["title"] for r in results), (q, results))

    def test_limits(self):
        db = self.Session()
        db.add_all([Goal(area="work", title=f"Projekt {i}") for i in range(20)])
        db.add_all([Memory(area="work", category="context", content=f"Projekt poznámka {i}") for i in range(20)])
        db.commit()
        db.close()
        out = self._search("projekt")
        self.assertEqual(out["total"], 40)
        by_type = {}
        for r in out["results"]:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        self.assertEqual(by_type, {"goal": ss.PER_TYPE, "memory": ss.PER_TYPE})
        self.assertEqual(len(self._search("projekt", limit=3)["results"]), 3)
        self.assertEqual(self._search("p")["results"], [], "krátký dotaz")
        self.assertEqual(self._search("")["results"], [])
        self.assertLessEqual(len(self._search("x" * 500)["query"]), ss.MAX_QUERY)


class SearchAuthTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self._orig = (auth_service.SessionLocal, main.SessionLocal, auth_service.AUTH_PIN_HASH, auth_service._failed_attempts)
        auth_service.SessionLocal = Session
        main.SessionLocal = Session
        auth_service._failed_attempts = {}
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()
        db = Session()
        db.add(MffCharacter(name="Luna Snow", tier="T4"))
        db.commit()
        db.close()
        self.client = TestClient(main.app)

    def tearDown(self):
        auth_service.SessionLocal, main.SessionLocal, auth_service.AUTH_PIN_HASH, auth_service._failed_attempts = self._orig
        self.engine.dispose()

    def test_requires_session(self):
        self.assertEqual(self.client.get("/search", params={"q": "luna"}).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)
        r = self.client.get("/search", params={"q": "luna"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["title"], "Luna Snow")


if __name__ == "__main__":
    unittest.main()
