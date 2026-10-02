import os
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ai
from database import Base
from time_utils import now_local


def _fake_completion(content: str = "ok"):
    message = types.SimpleNamespace(content=content, tool_calls=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class SystemPromptDateTestCase(unittest.TestCase):
    """Model musí v každém requestu dostat skutečné pražské datum/čas."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.captured: list[list[dict]] = []

        def fake_llm(api_messages, **_kwargs):
            self.captured.append([dict(m) for m in api_messages])
            return _fake_completion()

        self._patches = [
            patch.object(ai, "SessionLocal", sessionmaker(bind=self.engine)),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _system_prompt_for(self, now_utc: datetime) -> str:
        with patch.object(ai, "now_local", lambda: now_local(now_utc)):
            ai.ask_ai([{"role": "user", "content": "Přidej mi zítra 3 hodiny práce."}])
        return self.captured[-1][0]["content"]

    def test_prompt_contains_current_prague_date_and_time(self):
        # 30. 9. 22:30 UTC = čtvrtek 1. 10. 2026 00:30 CEST (UTC datum by bylo špatně)
        prompt = self._system_prompt_for(datetime(2026, 9, 30, 22, 30))
        self.assertIn("CURRENT APPLICATION DATE: 2026-10-01 (čtvrtek)", prompt)
        self.assertIn("Current local time: 00:30 CEST", prompt)
        self.assertTrue(prompt.startswith(ai.SYSTEM_PROMPT))

    def test_date_is_recomputed_on_every_request(self):
        first = self._system_prompt_for(datetime(2026, 10, 25, 0, 30))   # 02:30 CEST
        second = self._system_prompt_for(datetime(2026, 10, 25, 1, 30))  # 02:30 CET (po změně času)
        self.assertIn("CURRENT APPLICATION DATE: 2026-10-25 (neděle)", first)
        self.assertIn("Current local time: 02:30 CEST", first)
        self.assertIn("Current local time: 02:30 CET", second)
        self.assertEqual(len(self.captured), 2)


if __name__ == "__main__":
    unittest.main()
