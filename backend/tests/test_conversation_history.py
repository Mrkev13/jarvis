"""A4 history window + conversation summary. Fake summarizer / fake model only – no real Groq."""
import dataclasses
import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import auth_service  # noqa: E402
import main  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from history_service import (  # noqa: E402
    SUMMARY_HEADER,
    message_tokens,
    prepare_conversation_history,
    window_client_messages,
)
from llm_budget import estimate_fixed_overhead  # noqa: E402
from llm_config import LLM_SETTINGS, load_llm_settings  # noqa: E402
from models import Conversation, Message, PendingAction, WorkSession  # noqa: E402

SETTINGS = LLM_SETTINGS  # defaulty: okno 8, práh 1000, shrnutí 300, historie 2500
WINDOW = SETTINGS.history_window_messages


def _content(i: int) -> str:
    # ~80 odhadovaných tokenů na zprávu
    return f"Zpráva {i}: " + "probíráme plán úspor a školu " * 10


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _add_messages(db, conv, start: int, count: int):
    base = datetime(2026, 10, 1, 8, 0)
    for i in range(start, start + count):
        db.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant",
                       content=_content(i), created_at=base + timedelta(minutes=i)))
    db.commit()


def _messages(db, conv):
    return db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at, Message.id).all()


class FakeSummarizer:
    def __init__(self, fail: bool = False, text: str | None = None):
        self.calls: list[tuple[str | None, list[dict]]] = []
        self.fail = fail
        self.text = text

    def __call__(self, previous, messages):
        self.calls.append((previous, list(messages)))
        if self.fail:
            raise RuntimeError("AI provider má vyčerpaný denní limit")
        first, last = messages[0]["content"].split(":")[0], messages[-1]["content"].split(":")[0]
        return self.text if self.text is not None else f"- Shrnutí #{len(self.calls)} ({first} až {last}); úspory, škola"


class HistoryWindowTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()
        self.conv = Conversation(title="Dlouhý chat")
        self.db.add(self.conv)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _prepare(self, summarizer, settings=SETTINGS):
        return prepare_conversation_history(self.db, self.conv, _messages(self.db, self.conv), settings, summarizer)

    def test_short_conversation_is_sent_verbatim_without_summary(self):
        _add_messages(self.db, self.conv, 0, 6)
        summarizer = FakeSummarizer()
        result = self._prepare(summarizer)
        self.assertEqual(summarizer.calls, [])
        self.assertEqual([m["content"] for m in result.messages], [_content(i) for i in range(6)])

    def test_older_messages_below_trigger_are_kept_verbatim(self):
        _add_messages(self.db, self.conv, 0, WINDOW + 3)  # 3 starší × ~84 tokenů < práh 1000
        summarizer = FakeSummarizer()
        result = self._prepare(summarizer)
        self.assertEqual(summarizer.calls, [])
        self.assertEqual(len(result.messages), WINDOW + 3)

    def test_60_messages_window_summary_budget_and_incremental_catch_up(self):
        _add_messages(self.db, self.conv, 0, 60)
        all_msgs = _messages(self.db, self.conv)
        summarizer = FakeSummarizer()

        first = self._prepare(summarizer)
        # rozpočet
        self.assertLessEqual(first.history_tokens, SETTINGS.max_history_tokens)
        self.assertLess(first.history_tokens, message_tokens([{"content": m.content} for m in all_msgs]))
        # posledních 8 doslovně, na začátku shrnutí, žádná starší zpráva v plném znění
        self.assertEqual([m["content"] for m in first.messages[-WINDOW:]], [m.content for m in all_msgs[-WINDOW:]])
        self.assertEqual(first.messages[0]["role"], "system")
        self.assertTrue(first.messages[0]["content"].startswith(SUMMARY_HEADER))
        self.assertEqual(len(first.messages), 1 + WINDOW)
        self.assertFalse(any(m["content"].startswith("Zpráva 0:") for m in first.messages))
        # jedno volání nad omezenou dávkou; zbytek nad práh se tento turn vynechá
        self.assertEqual(len(summarizer.calls), 1)
        batch = summarizer.calls[0][1]
        self.assertTrue(batch[0]["content"].startswith("Zpráva 0:"))
        self.db.refresh(self.conv)
        self.assertEqual(self.conv.summarized_until_message_id, all_msgs[len(batch) - 1].id)
        stored_summary = self.conv.summary
        self.assertEqual(stored_summary, f"- Shrnutí #1 (Zpráva 0 až Zpráva {len(batch) - 1}); úspory, škola")
        self.assertGreater(first.dropped_messages, 0)

        # druhý turn: dohání zbytek – uložené shrnutí + jen dosud neshrnuté zprávy
        second = self._prepare(summarizer)
        self.assertEqual(len(summarizer.calls), 2)
        previous, batch2 = summarizer.calls[1]
        self.assertEqual(previous, stored_summary)
        self.assertTrue(batch2[0]["content"].startswith(f"Zpráva {len(batch)}:"))
        self.db.refresh(self.conv)
        self.assertEqual(self.conv.summarized_until_message_id, all_msgs[-WINDOW - 1].id)
        self.assertEqual(second.dropped_messages, 0)
        self.assertLessEqual(second.history_tokens, SETTINGS.max_history_tokens)

        # třetí turn bez nových starších zpráv: shrnutí se znovu použije, žádné volání
        third = self._prepare(summarizer)
        self.assertEqual(len(summarizer.calls), 2)
        self.assertTrue(third.summary_used)
        self.assertFalse(third.summary_called)
        self.assertIn("Shrnutí #2", third.messages[0]["content"])

    def test_new_old_messages_advance_summary_incrementally(self):
        _add_messages(self.db, self.conv, 0, 30)
        summarizer = FakeSummarizer()
        self._prepare(summarizer)
        self.db.refresh(self.conv)
        until_before = self.conv.summarized_until_message_id
        calls_before = len(summarizer.calls)

        _add_messages(self.db, self.conv, 30, 4)  # okno posune 4 zprávy do „starších" (< práh)
        result = self._prepare(summarizer)
        self.assertEqual(len(summarizer.calls), calls_before, msg="pod prahem se neshrnuje")
        self.assertEqual(len(result.messages), 1 + 4 + WINDOW)  # shrnutí + 4 neshrnuté + okno

        _add_messages(self.db, self.conv, 34, 12)  # teď nad práh
        result = self._prepare(summarizer)
        self.assertEqual(len(summarizer.calls), calls_before + 1)
        previous, batch = summarizer.calls[-1]
        self.assertIsNotNone(previous)
        ids = [m.id for m in _messages(self.db, self.conv)]
        self.db.refresh(self.conv)
        self.assertGreater(self.conv.summarized_until_message_id, until_before)
        self.assertEqual(self.conv.summarized_until_message_id, ids[-WINDOW - 1])
        self.assertTrue(batch[0]["content"].startswith(f"Zpráva {ids.index(until_before) + 1}:"))
        self.assertEqual(len(result.messages), 1 + WINDOW)

    def test_summary_failure_falls_back_to_truncation(self):
        _add_messages(self.db, self.conv, 0, 40)
        all_msgs = _messages(self.db, self.conv)
        for summarizer in (FakeSummarizer(fail=True), FakeSummarizer(text="   ")):
            with self.subTest(failure="exception" if summarizer.fail else "empty"):
                result = self._prepare(summarizer)
                self.assertTrue(result.summary_failed)
                self.assertFalse(result.summary_used)
                self.assertEqual([m["content"] for m in result.messages], [m.content for m in all_msgs[-WINDOW:]])
                self.db.refresh(self.conv)
                self.assertIsNone(self.conv.summary)
                self.assertIsNone(self.conv.summarized_until_message_id)

    def test_summary_text_is_clipped_to_max_tokens(self):
        _add_messages(self.db, self.conv, 0, 40)
        result = self._prepare(FakeSummarizer(text="dlouhé shrnutí " * 400))
        self.db.refresh(self.conv)
        from llm_budget import estimate_tokens
        self.assertLessEqual(estimate_tokens(self.conv.summary), SETTINGS.max_summary_tokens)
        self.assertLessEqual(result.history_tokens, SETTINGS.max_history_tokens)

    def test_client_side_history_is_windowed(self):
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": _content(i)} for i in range(30)]
        result = window_client_messages(msgs, SETTINGS)
        self.assertEqual([m["content"] for m in result.messages], [_content(i) for i in range(22, 30)])
        self.assertEqual(result.dropped_messages, 22)

    def test_history_settings_validation(self):
        s = load_llm_settings({})
        self.assertEqual((s.history_window_messages, s.summary_trigger_tokens, s.max_summary_tokens, s.max_history_tokens),
                         (8, 1000, 300, 2500))
        with self.assertRaises(ValueError):
            load_llm_settings({"AI_SUMMARY_TRIGGER_TOKENS": "2400", "AI_MAX_SUMMARY_TOKENS": "300"})


def _completion(content=None, tool_calls=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
        content=content, tool_calls=tool_calls,
    ))])


class ChatIntegrationTestCase(unittest.TestCase):
    """main.chat s uloženou konverzací: shrnutí + A3 kontext + write safety (fake model)."""

    def setUp(self):
        self.engine, Session = _session()
        self.Session = Session
        db = Session()
        conv = Conversation(title="Dlouhý chat")
        db.add(conv)
        db.commit()
        self.conv_id = conv.id
        _add_messages(db, conv, 0, 59)  # + 1 nová zpráva z requestu = 60
        db.close()
        self.llm_calls: list[dict] = []
        self.chat_script: list = []

        def fake_llm(api_messages, tools=None, **kwargs):
            self.llm_calls.append({"messages": [dict(m) for m in api_messages], "tools": tools, **kwargs})
            if tools is None:
                return _completion(content="- Uživatel řeší plán úspor a školu; otevřené: rozpočet na říjen.")
            return self.chat_script.pop(0)

        self._orig_pin = auth_service.AUTH_PIN_HASH
        auth_service.AUTH_PIN_HASH = ""
        self._patches = [
            patch.object(main, "SessionLocal", Session),
            patch.object(ai, "SessionLocal", Session),
            patch.object(tools, "SessionLocal", Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        auth_service.AUTH_PIN_HASH = self._orig_pin
        self.engine.dispose()

    def _chat(self, text):
        return main.chat(main.ChatRequest(conversation_id=self.conv_id, message=text))

    def test_long_chat_uses_summary_context_prefetch_and_stays_in_budget(self):
        self.chat_script = [_completion(content="Navážu na rozpočet na říjen.")]
        result = self._chat("pokračujme s rozpočtem")
        self.assertEqual(result["answer"], "Navážu na rozpočet na říjen.")

        summary_call, chat_call = self.llm_calls
        self.assertIsNone(summary_call["tools"])
        self.assertEqual(summary_call["model"], ai.LLM_SETTINGS.groq_summary_model)
        self.assertEqual(summary_call["max_tokens"], ai.LLM_SETTINGS.max_summary_tokens)

        msgs = chat_call["messages"]
        self.assertEqual(msgs[0]["content"][:40], ai.SYSTEM_PROMPT[:40])
        self.assertTrue(msgs[1]["content"].startswith("CURRENT STATE"), msg="A3 prefetch musí zůstat")
        self.assertTrue(msgs[2]["content"].startswith(SUMMARY_HEADER))
        history = msgs[3:]
        self.assertEqual(len(history), WINDOW)
        self.assertEqual(history[-1]["content"], "pokračujme s rozpočtem")
        self.assertFalse(any(m["content"].startswith("Zpráva 0:") for m in msgs))

        fixed = estimate_fixed_overhead(msgs[0]["content"], ai.TOOLS).total
        context = message_tokens([msgs[1]])
        history_tokens = message_tokens(msgs[2:])
        self.assertLessEqual(history_tokens, ai.LLM_SETTINGS.max_history_tokens)
        self.assertLessEqual(context, ai.LLM_SETTINGS.max_context_tokens + 10)
        self.assertLessEqual(fixed + context + history_tokens,
                             ai.LLM_SETTINGS.max_fixed_tokens + ai.LLM_SETTINGS.max_context_tokens
                             + ai.LLM_SETTINGS.max_history_tokens)

        db = self.Session()
        try:
            conv = db.query(Conversation).get(self.conv_id)
            self.assertIn("rozpočet na říjen", conv.summary)
            self.assertIsNotNone(conv.summarized_until_message_id)
        finally:
            db.close()

    def test_write_proposal_with_long_history_stays_pending_only(self):
        tool_call = types.SimpleNamespace(id="w1", function=types.SimpleNamespace(
            name="add_work_session",
            arguments='{"date_value": "2026-10-03", "hours": 2, "project": "Servind", "hourly_rate": 300}',
        ))
        self.chat_script = [
            _completion(tool_calls=[tool_call]),
            _completion(content="Připravil jsem změnu k potvrzení."),
        ]
        result = self._chat("zapiš práci 2 hodiny na Servind za 300 Kč/h")
        self.assertEqual(result["answer"], "Připravil jsem změnu k potvrzení.")
        self.assertEqual([p["tool"] for p in result["pending_actions"]], ["add_work_session"])
        db = self.Session()
        try:
            self.assertEqual(db.query(WorkSession).count(), 0, msg="bez potvrzení žádný záznam")
            pending = db.query(PendingAction).one()
            self.assertEqual(pending.status, "pending")
        finally:
            db.close()
        self.assertEqual(main.ai_reject(result["pending_actions"][0]["id"])["status"], "rejected")
        db = self.Session()
        try:
            self.assertEqual(db.query(WorkSession).count(), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
