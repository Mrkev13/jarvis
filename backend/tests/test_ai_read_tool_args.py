import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ai
import tools
from database import Base
from models import Goal, GoalProgressHistory, Memory


def _tool_call(name: str, arguments: dict, call_id: str = "call_1"):
    """Stejný tvar jako tool_call objekt z OpenAI SDK."""
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _run_single(db, name: str, arguments: dict):
    tool_messages, pending = ai._run_tool_calls(db, [_tool_call(name, arguments)])
    assert pending == []
    return json.loads(tool_messages[0]["content"])


class ReadToolArgumentForwardingTestCase(unittest.TestCase):
    """_run_tool_calls musí read toolům předat argumenty z LLM tool callu."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._orig_tools_session_local = tools.SessionLocal
        tools.SessionLocal = self.Session
        self.db = self.Session()

    def tearDown(self):
        tools.SessionLocal = self._orig_tools_session_local
        self.db.close()
        self.engine.dispose()

    def test_get_goal_progress_history_receives_goal_id(self):
        g1 = Goal(area="work", title="Cíl A", status="active", priority="high", progress=0)
        g2 = Goal(area="finance", title="Cíl B", status="active", priority="medium", progress=0)
        self.db.add_all([g1, g2])
        self.db.flush()
        base = datetime(2026, 9, 1, 8, 0, 0)
        self.db.add_all([
            GoalProgressHistory(goal_id=g1.id, progress=10, current_value=10.0, recorded_at=base),
            GoalProgressHistory(goal_id=g1.id, progress=25, current_value=25.0, recorded_at=base + timedelta(days=1)),
            GoalProgressHistory(goal_id=g2.id, progress=50, current_value=500.0, recorded_at=base),
        ])
        self.db.commit()

        result = _run_single(self.db, "get_goal_progress_history", {"goal_id": g1.id})

        self.assertIsInstance(result, list, msg=f"tool vrátil chybu: {result}")
        self.assertEqual([r["goal_id"] for r in result], [g1.id, g1.id])
        self.assertEqual([r["progress"] for r in result], [10, 25])

    def test_get_memories_applies_area_filter(self):
        self.db.add_all([
            Memory(area="finance", category="plan", content="Spořit 10 % příjmu", importance=8),
            Memory(area="wot", category="plan", content="Po VZ.55 CS linie", importance=9),
            Memory(area="finance", category="preference", content="Bez kreditek", importance=5),
        ])
        self.db.commit()

        result = _run_single(self.db, "get_memories", {"area": "finance"})

        self.assertEqual(len(result), 2)
        self.assertTrue(all(m["area"] == "finance" for m in result))

        result_cat = _run_single(self.db, "get_memories", {"area": "finance", "category": "preference"})
        self.assertEqual([m["content"] for m in result_cat], ["Bez kreditek"])

    def test_unexpected_argument_returns_tool_error_without_aborting_batch(self):
        # LLM může halucinovat parametr; chyba jednoho toolu nesmí shodit ostatní.
        self.db.add(Memory(area="general", category="context", content="X", importance=5))
        self.db.commit()

        tool_messages, _ = ai._run_tool_calls(self.db, [
            _tool_call("get_memories", {"bogus": 1}, call_id="c1"),
            _tool_call("get_memories", {}, call_id="c2"),
        ])

        first = json.loads(tool_messages[0]["content"])
        second = json.loads(tool_messages[1]["content"])
        self.assertEqual(first.get("error"), "tool_execution_failed")
        self.assertEqual(len(second), 1)


if __name__ == "__main__":
    unittest.main()
