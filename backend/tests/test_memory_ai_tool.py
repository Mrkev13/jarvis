"""MRK-117: Jarvis navrhne dočasnou vzpomínku s platností (fake LLM) – pending → potvrzení → uložení v naive UTC.
Bez platnosti / s platností v minulosti / s neznámým druhem nevznikne žádná pending akce."""
import json
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

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import memory_ai_tool  # noqa: E402
import mutation_service  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import Memory, PendingAction  # noqa: E402

NOW = datetime(2026, 11, 23, 9, 0)  # naive UTC = 10:00 Praha


def _message(content=None, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)


def _save(**args):
    call = types.SimpleNamespace(id="c1", function=types.SimpleNamespace(name="save_memory", arguments=json.dumps(args)))
    return _message(tool_calls=[call])


class MemoryAiToolTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.script, self.calls = [], []

        def fake_llm(api_messages, **kwargs):
            self.calls.append([dict(m) for m in api_messages])
            return self.script.pop(0)

        self._patches = [
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(mutation_service, "SessionLocal", self.Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            patch.object(ai, "_build_context_safely", lambda db, message: None),
            patch.object(memory_ai_tool, "utc_now", lambda: NOW),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _ask(self, text, script):
        self.script = list(script)
        result = ai.ask_ai([{"role": "user", "content": text}])
        self.assertEqual(self.script, [])
        return result

    def _rows(self, model):
        db = self.Session()
        try:
            return db.query(model).all()
        finally:
            db.close()

    def test_temporary_memory_with_expiry_is_proposed_and_saved_in_utc(self):
        result = self._ask("pamatuj si, že tento týden jsem nemocný a netrénuju", [
            _save(content="Tento týden jsem nemocný, netrénuju.", area="fitness", category="context",
                  kind="temporary", expires_at="2026-11-29"),
            _message(content="Připravil jsem vzpomínku k potvrzení."),
        ])
        self.assertEqual(len(result["pending_actions"]), 1)
        self.assertEqual(self._rows(Memory), [], "nic se neuloží před potvrzením")
        confirmed = ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertTrue(confirmed["ok"], confirmed)
        [m] = self._rows(Memory)
        self.assertEqual((m.kind, m.area), ("temporary", "fitness"))
        self.assertEqual(m.expires_at, datetime(2026, 11, 29, 22, 59), "konec dne v Praze (CET) = 22:59 UTC")

    def test_time_of_day_and_decision(self):
        self.assertEqual(memory_ai_tool.parse_expires_local("2026-07-01T18:30"), datetime(2026, 7, 1, 16, 30), "letní čas")
        result = self._ask("zapamatuj si rozhodnutí: grind jen o víkendu", [
            _save(content="Grind ve WoT jen o víkendu.", area="wot", kind="decision"),
            _message(content="OK"),
        ])
        ai.execute_confirm_action(result["pending_actions"][0]["id"])
        [m] = self._rows(Memory)
        self.assertEqual((m.kind, m.expires_at), ("decision", None))

    def test_invalid_temporary_memory_creates_no_pending_action(self):
        for args, code in (
            ({"kind": "temporary"}, "missing_expires_at"),
            ({"kind": "temporary", "expires_at": "2026-11-20"}, "expires_in_past"),
            ({"kind": "temporary", "expires_at": "příští týden"}, "invalid_expires_at"),
            ({"kind": "forever"}, "invalid_kind"),
            # Codex review #95: časová zóna ani jiný suffix se neořezává potichu
            ({"kind": "temporary", "expires_at": "2026-11-29T18:30Z"}, "invalid_expires_at"),
            ({"kind": "temporary", "expires_at": "2026-11-29T18:30+09:00"}, "invalid_expires_at"),
            ({"kind": "temporary", "expires_at": "2026-11-29T18:30garbage"}, "invalid_expires_at"),
            ({"kind": "temporary", "expires_at": "2026-11-29T18:30:00"}, "invalid_expires_at"),
            ({"kind": "temporary", "expires_at": "2026-11-29x"}, "invalid_expires_at"),
        ):
            with self.subTest(code=code):
                result = self._ask("pamatuj si to", [
                    _save(content="Něco dočasného.", **args),
                    _message(content="Do kdy to platí?"),
                ])
                self.assertEqual(result["pending_actions"], [])
                tool_result = json.loads(self.calls[-1][-1]["content"])
                self.assertEqual(tool_result.get("error"), code, tool_result)
        self.assertEqual(self._rows(PendingAction), [])

    def test_preview_text_shows_kind_and_expiry(self):
        from text_utils import ai_action_details
        text = ai_action_details("save_memory", {"content": "Nemocný", "kind": "temporary", "expires_at": "2026-11-29"})
        self.assertEqual(text, "Nemocný · dočasná · platí do 2026-11-29")
