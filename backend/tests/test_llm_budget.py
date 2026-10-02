import dataclasses
import inspect
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

import ai
from llm_budget import estimate_fixed_overhead, estimate_tokens, estimate_tool_schema_tokens
from llm_config import DEFAULT_GROQ_MODEL, DEFAULT_MAX_FIXED_TOKENS, load_llm_settings
from time_utils import now_local

ALL_TOOL_FUNCTIONS = {**ai.READ_TOOL_FUNCTIONS, **ai.WRITE_TOOL_FUNCTIONS}
WRITE_PREFIXES = ("add_", "update_", "upsert_", "save_")
# Interní parametry write funkcí, které LLM nesmí vidět ani nastavit.
INTERNAL_PARAMS = {"user_context"}


def _schema(tool: dict) -> dict:
    return tool["function"]["parameters"]


class TokenEstimatorTestCase(unittest.TestCase):
    def test_estimate_is_deterministic_and_weights_non_ascii(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("abcd" * 10), 10)
        # „ž" a „í" se počítají 2× → (2 + 2*2) / 4 → 2
        self.assertEqual(estimate_tokens("žaíb"), 2)
        self.assertEqual(estimate_tokens(ai.SYSTEM_PROMPT), estimate_tokens(ai.SYSTEM_PROMPT))

    def test_tool_schema_estimate_uses_compact_json(self):
        tools = [ai._tool("x", "d", {"a": {"type": "string"}})]
        compact = '[{"type":"function","function":{"name":"x","description":"d","parameters":' \
                  '{"type":"object","properties":{"a":{"type":"string"}},"additionalProperties":false}}}]'
        self.assertEqual(estimate_tool_schema_tokens(tools), estimate_tokens(compact))


class FixedOverheadBudgetTestCase(unittest.TestCase):
    """System prompt (vč. A1 data/času) + výchozí sada tool schémat musí zůstat pod pevným limitem."""

    def test_fixed_overhead_within_budget_for_every_weekday_and_dst_state(self):
        # pondělí–neděle v létě (CEST) i v zimě (CET) – délka názvu dne / pásma se liší
        samples = [datetime(2026, 7, d, 10, 0) for d in range(6, 13)] + \
                  [datetime(2026, 12, d, 10, 0) for d in range(7, 14)]
        worst = max(
            estimate_fixed_overhead(ai.build_system_prompt(now_local(s)), ai.TOOLS).total
            for s in samples
        )
        self.assertLessEqual(
            worst, DEFAULT_MAX_FIXED_TOKENS,
            msg=f"fixní režie ~{worst} tokenů > {DEFAULT_MAX_FIXED_TOKENS}; zkrať prompt/popisy nebo zaveď routing",
        )

    def test_overhead_counts_every_default_tool(self):
        overhead = estimate_fixed_overhead(ai.build_system_prompt(), ai.TOOLS)
        self.assertEqual(overhead.tool_count, len(ai.READ_TOOLS) + len(ai.WRITE_TOOLS))
        self.assertEqual(overhead.total, overhead.prompt_tokens + overhead.tool_tokens)


class ToolRegistryTestCase(unittest.TestCase):
    """Tool schémata musí přesně odpovídat Python funkcím, které se volají s **arguments."""

    def test_tool_names_are_unique_and_registered_exactly_once(self):
        names = [t["function"]["name"] for t in ai.TOOLS]
        self.assertEqual(len(names), len(set(names)), msg=f"duplicitní tool: {names}")
        self.assertEqual(set(names), set(ALL_TOOL_FUNCTIONS))
        self.assertFalse(set(ai.READ_TOOL_FUNCTIONS) & set(ai.WRITE_TOOL_FUNCTIONS))
        self.assertEqual({t["function"]["name"] for t in ai.WRITE_TOOLS}, set(ai.WRITE_TOOL_FUNCTIONS))
        self.assertEqual(ai.WRITE_TOOL_NAMES, set(ai.WRITE_TOOL_FUNCTIONS))

    def test_schema_properties_match_function_signature(self):
        for tool in ai.TOOLS:
            name = tool["function"]["name"]
            with self.subTest(tool=name):
                params = inspect.signature(ALL_TOOL_FUNCTIONS[name]).parameters
                props = set(_schema(tool)["properties"])
                self.assertLessEqual(props, set(params), msg="schema má parametr, který funkce nepřijme")
                self.assertFalse(props & INTERNAL_PARAMS, msg="interní parametr je vystaven LLM")
                exposable = set(params) - INTERNAL_PARAMS
                self.assertIs(_schema(tool)["additionalProperties"], False)
                self.assertLessEqual(props, exposable)

    def test_required_arguments_match_function_requirements(self):
        for tool in ai.TOOLS:
            name = tool["function"]["name"]
            with self.subTest(tool=name):
                params = inspect.signature(ALL_TOOL_FUNCTIONS[name]).parameters
                schema_required = set(_schema(tool).get("required", []))
                py_required = {k for k, p in params.items() if p.default is inspect.Parameter.empty}
                self.assertLessEqual(schema_required, set(_schema(tool)["properties"]))
                # Bez povinného argumentu by volání funkce spadlo → schéma ho musí vyžadovat.
                self.assertLessEqual(py_required, schema_required)

    def test_write_classification_matches_prompt_naming_rule(self):
        # SYSTEM_PROMPT rozlišuje READ (get_*) a WRITE (add_*, update_*, upsert_*, save_memory) podle jména.
        for name in ai.READ_TOOL_FUNCTIONS:
            self.assertTrue(name.startswith("get_"), msg=name)
        for name in ai.WRITE_TOOL_FUNCTIONS:
            self.assertTrue(name.startswith(WRITE_PREFIXES), msg=name)
        self.assertIn("save_memory", ai.WRITE_TOOL_FUNCTIONS)


class SystemPromptSafetyTestCase(unittest.TestCase):
    """Zkrácený prompt nesmí ztratit bezpečnostní a kontraktní pravidla."""

    REQUIRED_PHRASES = {
        "write tools prepare, never apply": "they only PREPARE a change",
        "confirmation signal": "confirmation_required",
        "confirmation in UI": "must confirm it in the UI",
        "never bypass": "Never bypass it",
        "never claim saved": '"uložil jsem"',
        "never claim changed": '"změnil jsem"',
        "never claim added": '"přidal jsem"',
        "prepared wording": "Připravil jsem změnu k potvrzení.",
        "ask instead of guessing": "Never guess a missing value",
        "tool data authoritative": "Tool results are authoritative",
        "never invent data": "Never invent data",
        "memory not authoritative": "Memory is NOT authoritative for volatile data",
        "module data wins": "module data wins",
        "explicit save_memory only": "Call save_memory only when the user explicitly wants",
        "planner read-only": "Read-only",
        "planner never writes by itself": "never creates or modifies anything by itself",
        "no internals exposed": "Never expose internals",
        "relative dates from injected date": "CURRENT APPLICATION DATE",
        "czech replies": "reply in Czech",
    }

    def test_safety_rules_present(self):
        for rule, phrase in self.REQUIRED_PHRASES.items():
            with self.subTest(rule=rule):
                self.assertIn(phrase, ai.SYSTEM_PROMPT)

    def test_planner_json_contract_matches_frontend_parser(self):
        # frontend/app/ai/page.tsx → tryParseWeeklyPlan: ```json blok se summary + actions[priority, area, title, reason]
        self.assertIn("```json", ai.SYSTEM_PROMPT)
        for key in ('"summary"', '"actions"', '"priority"', '"area"', '"title"', '"reason"'):
            self.assertIn(key, ai.SYSTEM_PROMPT)
        for area in ("school", "work", "finance", "wot", "mff", "personal", "fitness", "hobby", "travel", "general"):
            self.assertIn(area, ai.SYSTEM_PROMPT)


class LLMSettingsTestCase(unittest.TestCase):
    def test_defaults_preserve_previous_behavior(self):
        s = load_llm_settings({})
        self.assertEqual(s.groq_model, "openai/gpt-oss-120b")
        self.assertEqual(s.groq_model, DEFAULT_GROQ_MODEL)
        self.assertEqual(s.groq_summary_model, s.groq_model)
        self.assertEqual(s.groq_base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(s.max_fixed_tokens, 3500)

    def test_env_overrides_and_invalid_values(self):
        s = load_llm_settings({"GROQ_MODEL": "m1", "AI_MAX_FIXED_TOKENS": "4000", "AI_MAX_CONTEXT_TOKENS": "900"})
        self.assertEqual((s.groq_model, s.groq_summary_model), ("m1", "m1"))
        self.assertEqual((s.max_fixed_tokens, s.max_context_tokens), (4000, 900))
        self.assertEqual(load_llm_settings({"GROQ_SUMMARY_MODEL": "small"}).groq_summary_model, "small")
        with self.assertRaises(ValueError):
            load_llm_settings({"AI_MAX_FIXED_TOKENS": "lots"})
        with self.assertRaises(ValueError):
            load_llm_settings({"AI_MAX_CONTEXT_TOKENS": "0"})

    def test_llm_call_uses_configured_model(self):
        calls = []
        fake_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **kw: calls.append(kw) or "response"
        )))
        custom = dataclasses.replace(ai.LLM_SETTINGS, groq_model="custom/model")
        with patch.object(ai, "client", fake_client), patch.object(ai, "LLM_SETTINGS", custom):
            self.assertEqual(ai._llm_create_with_retry([{"role": "user", "content": "x"}], tools=ai.TOOLS), "response")
        self.assertEqual(calls[0]["model"], "custom/model")
        self.assertIs(calls[0]["tools"], ai.TOOLS)


if __name__ == "__main__":
    unittest.main()
