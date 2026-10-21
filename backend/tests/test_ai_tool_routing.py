"""Roadmap 3.0 A5: napojení routingu toolů v ask_ai – pevná sada pro všechna kola, blokace nerutovaných
write toolů, nouzové rozšíření po odmítnutém tool callu, kill switch, log."""
import dataclasses
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import httpx  # noqa: E402
import openai  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import tool_registry as reg  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import FinanceTransaction, PendingAction, WorkSession  # noqa: E402

WRITE_NAMES = {s.name for s in reg.WRITE_SPECS}
READ_NAMES = {s.name for s in reg.READ_SPECS}


def _message(content=None, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)


def _call(name, args=None, call_id="c1"):
    return types.SimpleNamespace(id=call_id, function=types.SimpleNamespace(name=name, arguments=json.dumps(args or {})))


def _tool_validation_error():
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    bad = openai.BadRequestError(
        "tool call validation failed: attempted to call tool 'get_goals' which was not in request.tools",
        response=httpx.Response(400, request=request), body=None,
    )
    try:
        raise RuntimeError("AI provider vrátil chybu (400). Zkus to prosím později znovu.") from bad
    except RuntimeError as exc:
        return exc


class AskAiRoutingTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.script: list = []
        self.calls: list[dict] = []

        def fake_llm(api_messages, **kwargs):
            self.calls.append({"messages": [dict(m) for m in api_messages], **kwargs})
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        self._patches = [
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            patch.object(ai, "_build_context_safely", lambda db, message: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _ask(self, messages, script):
        self.script = list(script)
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        result = ai.ask_ai(messages)
        self.assertEqual(self.script, [], "nevyužité odpovědi fake modelu")
        return result

    def _tool_names(self, call):
        return {t["function"]["name"] for t in (call["tools"] or [])}

    def test_routed_tool_set_is_fixed_for_all_rounds(self):
        with self.assertLogs("standa_hub.llm", "INFO") as logs:
            self._ask("Ukaž mi posledních 5 pracovních směn", [
                _message(tool_calls=[_call("get_work_sessions", {"limit": 5})]),
                _message(content="Žádné směny."),
            ])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]["tools"], self.calls[1]["tools"])
        self.assertIn("get_work_sessions", self._tool_names(self.calls[0]))
        self.assertFalse(self._tool_names(self.calls[0]) & WRITE_NAMES)
        summary = next(line for line in logs.output if "request calls=" in line)
        self.assertRegex(summary, r"tools_exposed=[1-7] tool_schema_tokens=\d+ tool_route=areas route_widened=False")

    def test_greeting_request_sends_no_tools(self):
        self._ask("ahoj", [_message(content="Ahoj!")])
        self.assertIsNone(self.calls[0]["tools"])

    def test_kill_switch_sends_exact_full_tool_list(self):
        with patch.object(ai, "LLM_SETTINGS", dataclasses.replace(ai.LLM_SETTINGS, tool_routing=False)):
            self._ask("ahoj", [_message(content="Ahoj!")])
        self.assertIs(self.calls[0]["tools"], ai.TOOLS)

    def test_unrouted_write_tool_is_refused_and_creates_no_pending_action(self):
        result = self._ask("kolik hodin jsem odpracoval?", [
            _message(tool_calls=[_call("add_work_session", {"date_value": "2026-10-03", "hours": 2,
                                                            "project": "Servind", "hourly_rate": 300})]),
            _message(content="Nic jsem nezměnil."),
        ])
        self.assertEqual(result["pending_actions"], [])
        db = self.Session()
        try:
            self.assertEqual(db.query(PendingAction).count(), 0)
            self.assertEqual(db.query(WorkSession).count(), 0)
        finally:
            db.close()
        tool_msg = self.calls[1]["messages"][-1]
        self.assertEqual(json.loads(tool_msg["content"])["error"], "write_not_available")

    def test_routed_write_tool_creates_pending_action_only(self):
        result = self._ask("zapiš práci 2 hodiny na Servind za 300 Kč/h", [
            _message(tool_calls=[_call("add_work_session", {"date_value": "2026-10-03", "hours": 2,
                                                            "project": "Servind", "hourly_rate": 300})]),
            _message(content="Připravil jsem změnu k potvrzení."),
        ])
        self.assertIn("add_work_session", self._tool_names(self.calls[0]))
        self.assertEqual([p["tool"] for p in result["pending_actions"]], ["add_work_session"])
        db = self.Session()
        try:
            self.assertEqual(db.query(PendingAction).filter(PendingAction.status == "pending").count(), 1)
            self.assertEqual(db.query(WorkSession).count(), 0, "zápis až po potvrzení")
        finally:
            db.close()

    def test_finance_tools_are_never_offered_and_a_finance_call_is_refused(self):
        """MRK-60: Finance nemá AI tooly – ani výslovná žádost je nevystaví a vymyšlené volání nic nepřipraví."""
        result = self._ask("přidej výdaj 300 Kč za oběd a ukaž mi transakce", [
            _message(tool_calls=[
                _call("add_finance_transaction", {"amount": 300, "category": "Jídlo", "transaction_type": "expense"}),
                _call("get_finance_transactions", {"limit": 5}, call_id="c2"),
            ]),
            _message(content="Finance nemám k dispozici."),
        ])
        offered = self._tool_names(self.calls[0])
        self.assertFalse({n for n in offered if "finance" in n}, offered)
        self.assertEqual(result["pending_actions"], [])
        errors = [json.loads(m["content"])["error"] for m in self.calls[1]["messages"] if m.get("role") == "tool"]
        self.assertEqual(errors, ["unknown_tool", "unknown_tool"])
        db = self.Session()
        try:
            self.assertEqual(db.query(PendingAction).count(), 0)
            self.assertEqual(db.query(FinanceTransaction).count(), 0)
        finally:
            db.close()

    def test_conversation_summary_does_not_widen_tools(self):
        messages = [
            {"role": "system", "content": "Shrnutí starší konverzace:\n- uživatel chtěl přidat výdaj 300 Kč a zapsat práci"},
            {"role": "user", "content": "kolik mám kreditů ve WoT?"},
        ]
        self._ask(messages, [_message(content="Máš 1 000 000 kreditů.")])
        self.assertEqual(self._tool_names(self.calls[0]), {"get_wot_resources", "get_wot_grinds"})

    def test_tool_validation_error_widens_once_and_retries(self):
        with self.assertLogs("standa_hub.llm", "INFO") as logs:
            result = self._ask("kolik mám kreditů ve WoT?", [
                _tool_validation_error(),
                _message(content="Hotovo."),
            ])
        self.assertEqual(result["answer"], "Hotovo.")
        self.assertEqual(self._tool_names(self.calls[0]), {"get_wot_resources", "get_wot_grinds"})
        self.assertEqual(self._tool_names(self.calls[1]), READ_NAMES, "fallback: všechny READ, žádné WRITE")
        summary = next(line for line in logs.output if "request calls=" in line)
        self.assertIn("tool_route=fallback route_widened=True", summary)

    def test_second_tool_validation_error_falls_back_to_no_tools(self):
        result = self._ask("kolik jsem utratil za jídlo?", [
            _tool_validation_error(), _tool_validation_error(), _message(content="Napiš prosím, co mám zapsat."),
        ])
        self.assertEqual(result["answer"], "Napiš prosím, co mám zapsat.")
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(self._tool_names(self.calls[1]) & WRITE_NAMES, "bez write záměru ani ve fallbacku")
        self.assertIsNone(self.calls[2]["tools"])

    def test_third_tool_validation_error_is_reported(self):
        with self.assertRaises(RuntimeError):
            self._ask("kolik mám kreditů ve WoT?", [_tool_validation_error()] * 3)
        self.assertEqual(len(self.calls), 3)

    def test_no_widening_when_routing_disabled(self):
        with patch.object(ai, "LLM_SETTINGS", dataclasses.replace(ai.LLM_SETTINGS, tool_routing=False)):
            with self.assertRaises(RuntimeError):
                self._ask("kolik mám kreditů ve WoT?", [_tool_validation_error()])
        self.assertEqual(len(self.calls), 1)

    def test_other_api_errors_are_not_treated_as_routing_problems(self):
        try:
            raise RuntimeError("AI provider má vyčerpaný denní limit") from None
        except RuntimeError as exc:
            err = exc
        with self.assertRaises(RuntimeError):
            self._ask("kolik mám kreditů ve WoT?", [err])
        self.assertEqual(len(self.calls), 1)

    def test_planner_nudge_only_for_available_tools(self):
        plan = "Plán:\n```json\n" + json.dumps({"summary": "x", "actions": []}) + "\n```"
        # Dotaz bez plánovacích slov → get_goals/get_memories nejsou v routované sadě → žádná připomínka.
        self._ask("kolik mám kreditů ve WoT?", [_message(content=plan)])
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
