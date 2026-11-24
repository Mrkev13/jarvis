"""MRK-83: regresní sada spolehlivosti AI chatu – scénáře 1–10 z auditu Hub 2.0 (MRK-69, příloha A, B1).

Celá cesta `/chat` → `ask_ai` → skutečné OpenAI SDK proti `FakeGroq` (httpx.MockTransport): žádná síť, žádný reálný
Groq. Každý test = jeden scénář auditu (číslo v názvu).
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
TESTS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
for p in (BACKEND_DIR, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import context_service as cs  # noqa: E402
import main  # noqa: E402
import mutation_service  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from fakes import FakeGroq, completion, groq_error  # noqa: E402
from models import Goal, PendingAction, WorkSession  # noqa: E402

SCHOOL_TOOLS = {"add_school_subject", "add_school_assignment", "add_school_exam", "get_school_subjects",
                "get_school_assignments", "get_school_exams"}


def tool_completion(*calls):
    """Odpověď modelu s tool calls: calls = (name, args[, id])."""
    body = completion(None, finish="tool_calls")
    body["choices"][0]["message"]["tool_calls"] = [
        {"id": c[2] if len(c) > 2 else f"call_{i}", "type": "function",
         "function": {"name": c[0], "arguments": json.dumps(c[1], ensure_ascii=False)}}
        for i, c in enumerate(calls)]
    return 200, body


def ok(text="Hotovo."):
    return 200, completion(text)


WORK = {"date_value": "2026-11-20", "hours": 2, "project": "Klient XYZ", "hourly_rate": 375, "description": "Workshop"}


class ChatReliabilityBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.sleeps = []
        self._patches = [
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(main, "SessionLocal", self.Session),
            patch.object(mutation_service, "SessionLocal", self.Session),
            patch.object(ai, "_build_context_safely", lambda db, message: None),
            patch("time.sleep", lambda s: self.sleeps.append(s)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def chat(self, text, *responses):
        self.fake = FakeGroq(*responses)
        with patch.object(ai, "client", self.fake.client()):
            res = main.chat(main.ChatRequest(messages=[main.ChatMessage(role="user", content=text)]))
        if isinstance(res, dict):
            return 200, res
        return res.status_code, json.loads(res.body)

    def tools_of(self, request_index=0):
        return {t["function"]["name"] for t in self.fake.requests[request_index].get("tools") or []}

    def pending_rows(self):
        db = self.Session()
        try:
            return [(p.tool, p.status) for p in db.query(PendingAction).order_by(PendingAction.id)]
        finally:
            db.close()


class ScenariosTestCase(ChatReliabilityBase):
    def test_01_provider_outage_retries_then_503_readable(self):
        status, body = self.chat("ahoj", *[groq_error(500, "upstream down")] * 3)
        self.assertEqual(status, 503)
        self.assertTrue(body["answer"].startswith("⚠️"))
        self.assertEqual(len(self.fake.requests), 3, "3 pokusy (AI_LLM_MAX_ATTEMPTS), pak čitelná chyba")
        self.assertEqual(body["pending_actions"], [])

    def test_02a_rate_limit_waits_and_succeeds(self):
        status, body = self.chat("ahoj", groq_error(429, "Rate limit reached on tokens per minute (TPM). Please try again in 1.5s."),
                                 ok("Ahoj!"))
        self.assertEqual((status, body["answer"]), (200, "Ahoj!"))
        self.assertEqual(len(self.fake.requests), 2)
        self.assertTrue(self.sleeps, "čekání před dalším pokusem")

    def test_02b_daily_limit_is_429_without_retry(self):
        status, body = self.chat("ahoj", groq_error(
            429, "Rate limit reached for model `m` on tokens per day (TPD): Limit 200000, Used 199900, Requested 900."))
        self.assertEqual(status, 429)
        self.assertIn("později", body["answer"])
        self.assertEqual(len(self.fake.requests), 1, "denní limit se neopakuje")

    def test_03_error_in_second_round_keeps_the_proposal(self):
        status, body = self.chat("zapiš práci 2 h pro Klient XYZ", tool_completion(("add_work_session", WORK)),
                                 *[groq_error(500, "down")] * 3)
        self.assertEqual(status, 503)
        self.assertEqual([a["tool"] for a in body["pending_actions"]], ["add_work_session"])
        self.assertIn("Návrh změny z tohoto dotazu je připravený níže", body["answer"])
        self.assertEqual(self.pending_rows(), [("add_work_session", "pending")], "návrh v DB, potvrditelný")

    def test_04_max_tool_rounds_ends_with_readable_answer(self):
        rounds = [tool_completion(("get_wot_grinds", {}, f"r{i}")) for i in range(10)]
        status, body = self.chat("kolik mi chybí na grind ve WoT?", *rounds)
        self.assertEqual(status, 200)
        self.assertIn("Nepodařilo se dokončit", body["answer"])
        self.assertEqual(len(self.fake.requests), 10)

    def test_05_two_proposals_in_one_turn_confirm_in_any_order(self):
        second = {**WORK, "hours": 3, "description": "Druhý"}
        status, body = self.chat("zapiš práci 2 h a 3 h pro Klient XYZ",
                                 tool_completion(("add_work_session", WORK, "a"), ("add_work_session", second, "b")),
                                 ok("Připraveno."))
        self.assertEqual(status, 200)
        ids = [a["id"] for a in body["pending_actions"]]
        self.assertEqual(len(ids), 2)
        for action_id in reversed(ids):
            self.assertTrue(ai.execute_confirm_action(action_id)["ok"])
        db = self.Session()
        try:
            self.assertEqual(sorted(w.hours for w in db.query(WorkSession)), [2, 3])
        finally:
            db.close()

    def test_06_test_in_finance_request_offers_no_school_tools(self):
        self.chat("přidej výdaj 100 Kč za smoke test", ok("Připraveno."))
        self.assertFalse(self.tools_of() & SCHOOL_TOOLS, self.tools_of())
        self.assertEqual(cs.classify_areas("přidej výdaj 100 Kč za smoke test", implied=False), frozenset({"finance"}))
        self.assertIn("school", cs.classify_areas("kdy mám test z matiky?"), "samotné „test“ dál znamená školu")
        self.assertIn("school", cs.classify_areas("jaký mám nejbližší termín?"))

    def test_07a_read_tool_outside_route_is_refused(self):
        with patch.object(tools, "get_school_subjects", side_effect=AssertionError("nesmí se provést")):
            self.chat("kolik mám kreditů ve WoT?", tool_completion(("get_school_subjects", {})), ok("Nevím."))
        tool_msg = next(m for m in self.fake.requests[1]["messages"] if m["role"] == "tool")
        self.assertEqual(json.loads(tool_msg["content"]), {"error": "tool_not_routed"})

    def test_07b_read_tool_of_disabled_module_is_refused(self):
        import module_registry

        class NoWot:
            def allows_context_area(self, area):
                return area != "wot"

        with patch.object(module_registry, "current_access", lambda: NoWot()):
            msgs, _ = ai._run_tool_calls(self.Session(), [type("C", (), {
                "id": "x", "function": type("F", (), {"name": "get_wot_grinds", "arguments": "{}"})()})()])
        self.assertEqual(json.loads(msgs[0]["content"]), {"error": "module_unavailable"})

    def test_08_upsert_goal_partial_edit_keeps_other_fields(self):
        db = self.Session()
        try:
            db.add(Goal(title="Naběhat 100 km", area="health", description="Jaro", target_value=100, progress=20,
                        priority="high", status="active", tracking_type="manual"))
            db.commit()
            gid = db.query(Goal).one().id
        finally:
            db.close()
        # Úpravu cíle routing posílá přes modify_records; upsert_goal s id je druhá cesta – stejná příprava jako v chatu
        db = self.Session()
        try:
            pending = ai.prepare_write_action(db, "upsert_goal", {"area": "health", "title": "Naběhat 100 km", "id": gid,
                                                                  "progress": 60, "description": ""})
        finally:
            db.close()
        result = ai.execute_confirm_action(pending["id"])
        self.assertTrue(result["ok"], result)
        db = self.Session()
        try:
            g = db.get(Goal, gid)
            self.assertEqual((g.title, g.target_value, g.progress, g.description, g.priority),
                             ("Naběhat 100 km", 100, 60, "Jaro", "high"), "prázdný popis = nezmíněno, ne smazat")
        finally:
            db.close()

    def test_09_finance_goal_never_reaches_the_prompt(self):
        db = self.Session()
        try:
            db.add(Goal(title="Tajná úspora 777777", area="finance", target_value=777777, progress=1,
                        status="active", tracking_type="manual"))
            db.commit()
        finally:
            db.close()
        self.chat("jaké mám cíle?", tool_completion(("get_goals", {})), ok("Tady."))
        sent = json.dumps(self.fake.requests, ensure_ascii=False)
        self.assertNotIn("777777", sent)
        self.assertNotIn("Tajná úspora", sent)

    def test_10_proposal_expired_before_confirm_writes_nothing(self):
        _, body = self.chat("zapiš práci 2 h pro Klient XYZ", tool_completion(("add_work_session", WORK)), ok("Připraveno."))
        db = self.Session()
        try:
            pa = db.query(PendingAction).one()
            pa.expires_at = datetime.utcnow() - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        out = ai.execute_confirm_action(body["pending_actions"][0]["id"])
        self.assertFalse(out["ok"])
        self.assertEqual(self.pending_rows(), [("add_work_session", "expired")])
        db = self.Session()
        try:
            self.assertEqual(db.query(WorkSession).count(), 0)
        finally:
            db.close()


class MaxTokensTestCase(ChatReliabilityBase):
    def test_every_chat_round_has_max_tokens(self):
        self.chat("kolik mi chybí na grind ve WoT?", tool_completion(("get_wot_grinds", {})), ok("Hodně."))
        self.assertEqual([r.get("max_tokens") for r in self.fake.requests], [ai.LLM_SETTINGS.chat_max_tokens] * 2)

    def test_truncated_empty_answer_is_readable(self):
        status, body = self.chat("ahoj", (200, completion("", finish="length")))
        self.assertEqual((status, body["answer"]), (200, ai.TRUNCATED_ANSWER))

    def test_setting_from_env(self):
        from llm_config import load_llm_settings
        self.assertEqual(load_llm_settings({"AI_CHAT_MAX_TOKENS": "1500"}).chat_max_tokens, 1500)
        with self.assertRaises(ValueError):
            load_llm_settings({"AI_CHAT_MAX_TOKENS": "10"})


if __name__ == "__main__":
    unittest.main()
