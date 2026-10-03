"""Sdílené jádro pro „přehledová" LLM volání (Daily Briefing – Phase F, Weekly Review – Phase G).

Jedno volání Chat Completions BEZ toolů a bez historie konverzace, se strict JSON Schema (Structured Outputs),
nízkým reasoning effortem a stropem výstupu. Chyby se mapují na kategorie, podle kterých volající plánuje
další pokus. Obsah odpovědi se nikdy neloguje.
"""
from __future__ import annotations

import json
import re
import time

from text_utils import clip as text_clip


class StructuredLLMError(Exception):
    def __init__(self, category: str, usage: dict | None = None):
        super().__init__(category)
        self.category = category
        self.usage = usage  # spotřeba i u nepovedené odpovědi (např. output_limit)


def request_params(schema_name: str, schema: dict, max_completion_tokens: int, reasoning_effort: str = "low") -> dict:
    """Parametry jen pro tato volání (běžný AI chat je nepoužívá)."""
    return {
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": reasoning_effort,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
    }


def classify_call_error(exc: RuntimeError, records: list) -> str:
    """RuntimeError z ai._llm_create_with_retry → kategorie. Původní výjimka SDK je v __cause__."""
    import ai

    if isinstance(exc, ai.LLMRateLimitError) or any(r.rate_limited for r in records):
        return "rate_limit"
    cause = exc.__cause__
    status = getattr(cause, "status_code", None)
    if status is None or status >= 500 or status in (408, 409):
        return "provider"
    text = f"{getattr(cause, 'code', '') or ''} {cause}".lower()
    if any(k in text for k in ("max_completion_tokens", "max_tokens", "max completion tokens", "token limit",
                               "finish_reason: length", "finish_reason=length")):
        return "output_limit"
    if "json_validate_failed" in text or "schema" in text or "response_format" in text:
        return "schema_error"
    return "request_rejected"


def usage_from(response, records: list, started: float) -> dict:
    from llm_config import LLM_SETTINGS

    ok = [r for r in records if not r.rate_limited and r.error_status is None]
    usage = {
        "model": getattr(response, "model", None) or LLM_SETTINGS.groq_model,
        "prompt_tokens": sum(r.prompt_tokens or 0 for r in ok),
        "completion_tokens": sum(r.completion_tokens or 0 for r in ok),
        "total_tokens": sum(r.total_tokens or 0 for r in ok),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "reasoning_tokens": None,
    }
    # OpenAI-kompatibilní detail (Groq ho u reasoning modelů vrací); jen se loguje, bez migrace.
    details = getattr(getattr(response, "usage", None), "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    if isinstance(reasoning, int):
        usage["reasoning_tokens"] = reasoning
    return usage


def call_structured(messages: list[dict], params: dict) -> tuple[str, dict]:
    """Jedno volání přes ai._llm_create_with_retry. Vrací (text, usage) nebo StructuredLLMError(kategorie)."""
    import ai

    records = []
    started = time.monotonic()
    try:
        response = ai._llm_create_with_retry(messages, tools=None, temperature=0.2, max_retries=2,
                                             call_log=records, extra_params=params)
    except ai.DailyLimitError:
        raise StructuredLLMError("daily_limit") from None
    except RuntimeError as exc:
        raise StructuredLLMError(classify_call_error(exc, records)) from None
    except Exception:  # noqa: BLE001 - nečekaný tvar odpovědi providera (např. ne-JSON tělo)
        raise StructuredLLMError("invalid_response") from None
    usage = usage_from(response, records, started)
    choices = getattr(response, "choices", None) or []
    if not choices or getattr(choices[0], "message", None) is None:
        raise StructuredLLMError("invalid_response", usage)
    choice = choices[0]
    finish = getattr(choice, "finish_reason", None)
    if getattr(choice.message, "refusal", None) or finish == "content_filter":
        raise StructuredLLMError("refused", usage)
    if finish == "length":
        # Uťato na stropu výstupu – i kdyby JSON vypadal celý, nevěříme mu.
        raise StructuredLLMError("output_limit", usage)
    text = choice.message.content
    if not isinstance(text, str) or not text.strip():
        raise StructuredLLMError("invalid_response", usage)
    return text, usage


def parse_json_object(text: str) -> dict:
    """Defenzivní parsování i přes strict schéma (ohraničení ```json, text kolem)."""
    t = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if fence:
        t = fence.group(1)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise StructuredLLMError("invalid_response")
    try:
        data = json.loads(t[start:end + 1])
    except ValueError:
        raise StructuredLLMError("invalid_response") from None
    if not isinstance(data, dict):
        raise StructuredLLMError("invalid_response")
    return data


clip = text_clip  # re-export (briefing/weekly ho importují odsud)


def make_ref_stripper(kinds: tuple[str, ...]):
    """Funkce, která z viditelného textu odstraní interní odkazy daných druhů („exam:2", „[metric:work]")."""
    ref = rf"\[?(?<![\w-])(?:{'|'.join(kinds)}):[0-9A-Za-z_-]+\]?"
    group_re = re.compile(rf"\s*[(\[]\s*(?:{ref}\s*(?:[,;]|\ba\b|\band\b)?\s*)+[)\]]")
    ref_re = re.compile(rf"\s*{ref}")

    def strip(text: str) -> str:
        t = str(text or "")
        if not ref_re.search(t):
            return t
        t = group_re.sub("", t)
        t = ref_re.sub("", t)
        t = re.sub(r"\s+([,.;:!?])", r"\1", t)
        t = re.sub(r"([,;])(?:\s*[,;])+", r"\1", t)
        t = re.sub(r"[,;]\s*(?=[.!?]|$)", "", t)
        return " ".join(t.split()).strip(" ,;")

    return strip
