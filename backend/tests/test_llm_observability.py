"""LLM usage / retry observability – fake raw client, no real Groq. Logs must contain numbers only."""
import dataclasses
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
import tools  # noqa: E402
from database import Base  # noqa: E402
from llm_config import load_llm_settings  # noqa: E402
from llm_usage import retry_wait_seconds  # noqa: E402

LOGGER = "standa_hub.llm"
SECRETS = ("TAJNA_ZPRAVA_UZIVATELE", "TAJNY_ARGUMENT_TOOLU", "TAJNA_ODPOVED_MODELU", "sk-test-SECRET-KEY")


def _response(content=None, tool_calls=None, prompt=100, completion=20):
    usage = types.SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(usage=usage, choices=[types.SimpleNamespace(message=msg)])


def _raw(response, remaining="4321"):
    return types.SimpleNamespace(headers={"x-ratelimit-remaining-tokens": remaining}, parse=lambda: response)


def _rate_limit_error(retry_after="2", remaining="0"):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(
        429, headers={"retry-after": retry_after, "x-ratelimit-remaining-tokens": remaining}, request=request,
    )
    return openai.RateLimitError("Rate limit reached. Please try again in 1.5s.", response=response, body=None)


def _fake_client(script, calls):
    def create(**kwargs):
        calls.append(kwargs)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return types.SimpleNamespace(
        api_key=SECRETS[3],
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            with_raw_response=types.SimpleNamespace(create=create),
        )),
    )


class LLMObservabilityTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.calls: list[dict] = []
        self.sleeps: list[float] = []
        self._patches = [
            patch.object(ai, "SessionLocal", Session),
            patch.object(tools, "SessionLocal", Session),
            patch.object(ai, "LLM_SETTINGS", dataclasses.replace(ai.LLM_SETTINGS, usage_logging=True)),
            patch.object(ai.time, "sleep", lambda s: self.sleeps.append(s)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _assert_no_content(self, log_text: str):
        for secret in SECRETS:
            self.assertNotIn(secret, log_text)
        self.assertNotIn("CURRENT APPLICATION DATE", log_text)
        self.assertNotIn(ai.SYSTEM_PROMPT[:60].strip(), log_text)

    def test_usage_rounds_and_rate_limit_headers_logged_without_content(self):
        tool_call = types.SimpleNamespace(id="c1", function=types.SimpleNamespace(
            name="get_memories", arguments='{"area": "TAJNY_ARGUMENT_TOOLU"}',
        ))
        script = [
            _raw(_response(tool_calls=[tool_call], prompt=2711, completion=183), remaining="5000"),
            _raw(_response(content="TAJNA_ODPOVED_MODELU", prompt=2800, completion=50), remaining="2100"),
        ]
        with patch.object(ai, "client", _fake_client(script, self.calls)), self.assertLogs(LOGGER, "INFO") as logs:
            result = ai.ask_ai([{"role": "user", "content": "TAJNA_ZPRAVA_UZIVATELE"}])
        self.assertEqual(result["answer"], "TAJNA_ODPOVED_MODELU")
        text = "\n".join(logs.output)
        self.assertIn("prompt_tokens=2711 completion_tokens=183 total_tokens=2894", text)
        self.assertIn("rl_remaining_tokens=2100", text)
        self.assertIn("latency_ms=", text)
        self.assertIn("request calls=2 tool_rounds=1 prompt_tokens=5511 completion_tokens=233", text)
        self.assertIn("rate_limited=0", text)
        self._assert_no_content(text)

    def test_429_is_retried_with_header_wait_and_logged(self):
        script = [_rate_limit_error(retry_after="2"), _raw(_response(content="ok"))]
        records = []
        with patch.object(ai, "client", _fake_client(script, self.calls)), self.assertLogs(LOGGER, "INFO") as logs:
            response = ai._llm_create_with_retry([{"role": "user", "content": "TAJNA_ZPRAVA_UZIVATELE"}],
                                                 tools=[], call_log=records)
        self.assertEqual(response.choices[0].message.content, "ok")
        self.assertEqual([r.rate_limited for r in records], [True, False])
        self.assertEqual(records[0].ratelimit_remaining_tokens, "0")
        self.assertEqual(self.sleeps, [2.3])
        text = "\n".join(logs.output)
        self.assertIn("429 rate_limited", text)
        self.assertIn("retry after 429 attempt=1/3 wait_s=2.3", text)
        self._assert_no_content(text)

    def test_429_exhausting_attempts_raises_and_logs_each_attempt(self):
        attempts = ai.LLM_SETTINGS.llm_max_attempts
        script = [_rate_limit_error() for _ in range(attempts)]
        records = []
        with patch.object(ai, "client", _fake_client(script, self.calls)), self.assertLogs(LOGGER, "INFO") as logs:
            with self.assertRaises(RuntimeError):
                ai._llm_create_with_retry([{"role": "user", "content": "x"}], tools=[], call_log=records)
        self.assertEqual(len(self.calls), attempts)
        self.assertEqual(sum(r.rate_limited for r in records), attempts)
        self.assertEqual(len(self.sleeps), attempts - 1)
        self.assertEqual(sum("429 rate_limited" in line for line in logs.output), attempts)

    def test_retry_wait_prefers_header_then_message_and_is_capped(self):
        self.assertEqual(retry_wait_seconds(_rate_limit_error(retry_after="2"), max_wait=20), 2.3)
        self.assertEqual(retry_wait_seconds(_rate_limit_error(retry_after="120"), max_wait=20), 20)
        no_header = openai.RateLimitError(
            "Please try again in 850ms.",
            response=httpx.Response(429, request=httpx.Request("POST", "https://x")), body=None,
        )
        self.assertAlmostEqual(retry_wait_seconds(no_header, max_wait=20), 1.15)


class RetrySettingsTestCase(unittest.TestCase):
    def test_sdk_retries_are_explicit_and_disabled_by_default(self):
        self.assertEqual(load_llm_settings({}).sdk_max_retries, 0)
        self.assertEqual(ai.client.max_retries, ai.LLM_SETTINGS.sdk_max_retries)
        self.assertEqual(load_llm_settings({}).llm_max_attempts, 3)
        self.assertEqual(load_llm_settings({"GROQ_SDK_MAX_RETRIES": "2"}).sdk_max_retries, 2)
        with self.assertRaises(ValueError):
            load_llm_settings({"GROQ_SDK_MAX_RETRIES": "-1"})
        self.assertFalse(load_llm_settings({"AI_USAGE_LOG": "false"}).usage_logging)


if __name__ == "__main__":
    unittest.main()
