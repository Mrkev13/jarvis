"""Planner grounding: scripted fake model (no real Groq), real read tools on in-memory SQLite."""
import json
import os
import sys
import types
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import FinanceTransaction, Goal, Memory, WorkSession  # noqa: E402
from planner_guard import NO_GROUNDED_ACTIONS_NOTE, find_planner_block  # noqa: E402


def _message(content=None, tool_calls=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
        content=content, tool_calls=tool_calls,
    ))])


def _tools_round(*names):
    return _message(tool_calls=[
        types.SimpleNamespace(id=f"c{i}", function=types.SimpleNamespace(name=n, arguments="{}"))
        for i, n in enumerate(names)
    ])


def _plan_answer(summary, actions):
    plan = {"summary": summary, "actions": [
        {"priority": i, "area": area, "title": title, "reason": reason}
        for i, (area, title, reason) in enumerate(actions, start=1)
    ]}
    return _message(content="Tady je plán.\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```")


class PlannerGroundingTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = Session()
        db.add_all([
            WorkSession(date=date(2026, 9, 10), hours=7.5, project="Servind", hourly_rate=325, sync_to_finance=False),
            FinanceTransaction(amount=9000, category="work", description="", transaction_type="income",
                               created_at=datetime(2026, 9, 15, 10, 0)),
            Goal(area="finance", title="Našetřit 150 000 Kč", status="active", priority="high", progress=6,
                 tracking_type="manual", target_value=150000, target_date=date(2027, 8, 31)),
            Memory(area="wot", category="plan", content="Po VZ.55 chci začít CS linii.", importance=7),
        ])
        db.commit()
        db.close()
        self.script: list = []
        self.sent_messages: list[list[dict]] = []

        def fake_llm(api_messages, **_kwargs):
            self.sent_messages.append([dict(m) for m in api_messages])
            return self.script.pop(0)

        self._patches = [
            patch.object(ai, "SessionLocal", Session),
            patch.object(tools, "SessionLocal", Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            # Tyto testy pokrývají tool-based planner cestu (fallback bez CURRENT STATE kontextu);
            # cesta s prefetch kontextem je v test_context_prefetch.py.
            patch.object(ai, "_build_context_safely", lambda db, message: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _ask(self, script):
        self.script = list(script)
        result = ai.ask_ai([{"role": "user", "content": "co mám dělat tento týden"}])
        self.assertEqual(self.script, [], msg="fake model měl nevyužité odpovědi")
        return result

    def _final_plan(self, result):
        block = find_planner_block(result["answer"])
        self.assertIsNotNone(block, msg="planner JSON musí zůstat parsovatelný pro frontend")
        return block.plan

    def test_invented_project_name_is_removed(self):
        result = self._ask([
            _tools_round("get_goals", "get_memories", "get_work_sessions"),
            _plan_answer("Zaměř se na práci.", [
                ("work", "Zapsat další hodiny na projektu Servind", "Poslední záznam je 7,5 h na Servind."),
                ("work", "Začít práci na projektu Contoso", "Nový klient přinese příjem."),
            ]),
        ])
        plan = self._final_plan(result)
        titles = [a["title"] for a in plan["actions"]]
        self.assertEqual(titles, ["Zapsat další hodiny na projektu Servind"])
        self.assertEqual([a["priority"] for a in plan["actions"]], [1])
        self.assertNotIn("Contoso", result["answer"])

    def test_invented_numeric_targets_are_removed_but_derived_values_kept(self):
        result = self._ask([
            _tools_round("get_goals", "get_memories", "get_work_sessions"),
            _plan_answer("Ušetři 10 000 Kč měsíčně.", [
                ("finance", "Zkontrolovat cíl Našetřit 150 000 Kč", "Cíl je na 6 %."),
                # MRK-60: bilance z Finance (9 000 Kč) model nevidí → ani z ní odvozená částka neprojde
                ("finance", "Doplnit 141 000 Kč do cíle", "Do cíle zbývá 141 000 Kč."),
                ("finance", "Ušetřit 10 000 Kč do konce října", "Urychlí to cíl."),
                ("work", "Odpracovat 5 hodin freelance designu v pondělí", "Zvýší příjem."),
                ("work", "Zapsat odpracované hodiny na Servind", "Sazba 325 Kč/h, 7,5 h = 2 437,5 Kč."),
            ]),
        ])
        plan = self._final_plan(result)
        titles = [a["title"] for a in plan["actions"]]
        self.assertEqual(titles, ["Zkontrolovat cíl Našetřit 150 000 Kč", "Zapsat odpracované hodiny na Servind"])
        self.assertEqual([a["priority"] for a in plan["actions"]], [1, 2])
        self.assertNotIn("10 000", result["answer"])
        self.assertNotIn("141 000", result["answer"])
        self.assertNotIn("freelance", result["answer"])

    def test_plan_with_only_invented_actions_shows_note_instead_of_card(self):
        result = self._ask([
            _tools_round("get_goals", "get_memories"),
            _plan_answer("Plán.", [("finance", "Ušetřit 20 000 Kč", "Rychlejší cíl.")]),
        ])
        self.assertIsNone(find_planner_block(result["answer"]))
        self.assertIn(NO_GROUNDED_ACTIONS_NOTE, result["answer"])

    def _memories_result_present(self, messages) -> bool:
        return any(m.get("role") == "tool" and "CS linii" in m.get("content", "") for m in messages)

    def test_planner_skipping_get_memories_gets_it_in_the_same_round(self):
        # Model zavolá jen get_goals → server přidá get_memories do téhož kola (bez dalšího LLM volání).
        result = self._ask([
            _tools_round("get_goals"),
            _plan_answer("OK", [("wot", "Pokračovat ve VZ.55 před CS linií", "Plán z paměti.")]),
        ])
        self.assertEqual(len(self.sent_messages), 2)
        second_call = self.sent_messages[1]
        assistant_calls = [tc["function"]["name"] for tc in second_call[-3]["tool_calls"]]
        self.assertEqual(assistant_calls, ["get_goals", "get_memories"])
        self.assertTrue(self._memories_result_present(second_call), msg="get_memories se musel skutečně vykonat")
        self.assertFalse(any(m.get("role") == "system" for m in second_call[1:]), msg="žádná připomínka navíc")
        self.assertEqual(self._final_plan(result)["summary"], "OK")

    def test_planner_without_get_goals_is_nudged_once_to_call_required_tools(self):
        result = self._ask([
            _tools_round("get_work_summary"),
            _plan_answer("PRVNI", [("finance", "Zkontrolovat cíl Našetřit 150 000 Kč", "Cíl je na 6 %.")]),
            _tools_round("get_goals"),
            _plan_answer("DRUHY", [("wot", "Pokračovat ve VZ.55 před CS linií", "Plán z paměti.")]),
        ])
        self.assertEqual(len(self.sent_messages), 4)
        nudge = self.sent_messages[2][-1]
        self.assertEqual(nudge["role"], "system")
        self.assertIn("get_goals and get_memories", nudge["content"])
        self.assertTrue(self._memories_result_present(self.sent_messages[3]))
        self.assertEqual(self._final_plan(result)["summary"], "DRUHY")

    def test_nudge_happens_at_most_once(self):
        # Viděl jen get_work_sessions → akce musí stát jen na těchto datech (Servind, 7,5 h).
        result = self._ask([
            _tools_round("get_work_sessions"),
            _plan_answer("PRVNI", [("work", "Zapsat odpracované hodiny na Servind", "Naposledy 7,5 h.")]),
            _plan_answer("DRUHY", [("work", "Zapsat odpracované hodiny na Servind", "Naposledy 7,5 h.")]),
        ])
        self.assertEqual(len(self.sent_messages), 3)
        self.assertEqual(self._final_plan(result)["summary"], "DRUHY")

    def test_no_nudge_when_required_tools_were_called(self):
        result = self._ask([
            _tools_round("get_goals", "get_memories"),
            _plan_answer("OK", [("finance", "Zkontrolovat cíl Našetřit 150 000 Kč", "Cíl je na 6 %.")]),
        ])
        self.assertEqual(len(self.sent_messages), 2)
        self.assertFalse(any(m.get("role") == "system" for m in self.sent_messages[-1][1:]))
        self.assertEqual(len(self._final_plan(result)["actions"]), 1)


class GuardEvidenceTestCase(unittest.TestCase):
    """Regrese z reálného Groq běhu: timestampy, id a metadata nesmí „ověřit" vymyšlená čísla."""

    def test_timestamps_ids_and_metadata_do_not_ground_invented_numbers(self):
        from planner_guard import build_evidence, ungrounded_items

        tool_results = [
            json.dumps([{"id": 5, "title": "Našetřit 150 000 Kč", "target_value": 150000.0,
                         "target_date": "2027-08-31", "created_at": "2026-09-26T13:59:05.123456"}],
                       ensure_ascii=False),
            json.dumps([{"id": 1, "content": "Po VZ.55 chci začít CS linii.", "importance": 5,
                         "updated_at": "2026-09-26T14:05:00"}], ensure_ascii=False),
            json.dumps({"total_hours": 15.0, "total_earnings": 4875.0, "this_month_hours": 0.0}),
        ]
        evidence = build_evidence(["CURRENT APPLICATION DATE: 2026-10-02 (pátek)\nCurrent local time: 16:05 CEST",
                                   "co mám dělat tento týden", *tool_results])
        # vymyšlené (v reálném běhu je guard propustil kvůli roku 2026 a importance 5)
        self.assertIn("number", ungrounded_items("Vyčleň 2 000 Kč týdně na spoření", evidence))
        self.assertIn("number", ungrounded_items("Naplánuj a odpracuj alespoň 5 hodin práce", evidence))
        # skutečné hodnoty a dopočty zůstávají
        self.assertEqual(ungrounded_items("Celkem 15 h a 4 875 Kč za práci", evidence), [])
        self.assertEqual(ungrounded_items("Do cíle 150 000 Kč zbývá 145 125 Kč", evidence), [])  # 150000 − 4875
        self.assertEqual(ungrounded_items("Cíl má termín 31. 8.", evidence), [])


if __name__ == "__main__":
    unittest.main()
