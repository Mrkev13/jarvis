import json
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import ai  # noqa: E402
import main  # noqa: E402

SHORT_RETRY = "Za 10 sekund"


def _chat_error(exc: Exception) -> tuple[int, dict]:
    request = main.ChatRequest(messages=[main.ChatMessage(role="user", content="ahoj")])
    with patch.object(main, "ask_ai", side_effect=exc):
        response = main.chat(request)
    return response.status_code, json.loads(response.body)


class ChatRateLimitMessageTestCase(unittest.TestCase):
    """Regrese: i po vyčerpání DENNÍHO limitu /chat sliboval „Za 10 sekund by to mělo zase fungovat"."""

    def test_daily_limit_does_not_promise_a_short_retry(self):
        status, body = _chat_error(ai.DailyLimitError("AI provider má vyčerpaný denní limit (… překročen)."))
        self.assertEqual(status, 429)
        self.assertNotIn(SHORT_RETRY, body["answer"])
        self.assertIn("později", body["answer"])
        self.assertEqual(body["pending_actions"], [])

    def test_per_minute_rate_limit_keeps_short_retry_message(self):
        status, body = _chat_error(ai.LLMRateLimitError("AI provider nedisponuje (Rate limit 8 000 tokenů/minutu byl překročen)."))
        self.assertEqual(status, 429)
        self.assertIn(SHORT_RETRY, body["answer"])

    def test_provider_error_keeps_short_retry_message(self):
        status, body = _chat_error(RuntimeError("AI provider vrátil chybu (503). Zkus to prosím později znovu."))
        self.assertEqual(status, 503)
        self.assertIn(SHORT_RETRY, body["answer"])

    def test_status_depends_on_error_type_not_message_text(self):
        # Roadmap 3.5: žádné rozhodování podle českého textu zprávy.
        status, _ = _chat_error(RuntimeError("Rate limit … překročen"))
        self.assertEqual(status, 503)

    def test_daily_limit_error_is_still_a_runtime_error(self):
        # Volající, kteří chytají RuntimeError (beze změny chování), dál fungují.
        self.assertTrue(issubclass(ai.DailyLimitError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
