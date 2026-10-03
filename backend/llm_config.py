"""Centrální konfigurace LLM (Groq přes OpenAI-kompatibilní API).

Hodnoty se čtou z prostředí / backend/.env; defaulty odpovídají dosavadnímu chování.
API klíč (GROQ_API_KEY) zůstává jen v prostředí a sem se nenačítá.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
# Groq free tier: 8 000 TPM. Fixní režie (system prompt + tool schémata) musí nechat
# prostor pro kontext, historii, tool výsledky a odpověď.
DEFAULT_MAX_FIXED_TOKENS = 3500
# Prefetch CURRENT STATE kontext (A3): cíl a tvrdé maximum odhadovaných tokenů (odděleně od fixní režie).
DEFAULT_CONTEXT_TARGET_TOKENS = 500
DEFAULT_MAX_CONTEXT_TOKENS = 600
# Retry: SDK vlastní retry vypnuto (0), aby každý 429/5xx prošel aplikační smyčkou a byl vidět v logu.
# Historie konverzace (A4): okno posledních zpráv, práh shrnutí starších zpráv, max délka shrnutí
# a tvrdé maximum celé posílané historie (shrnutí + nezahrnuté starší + okno).
DEFAULT_HISTORY_WINDOW_MESSAGES = 8
DEFAULT_SUMMARY_TRIGGER_TOKENS = 1000
DEFAULT_MAX_SUMMARY_TOKENS = 300
DEFAULT_MAX_HISTORY_TOKENS = 2500
DEFAULT_SDK_MAX_RETRIES = 0
DEFAULT_LLM_MAX_ATTEMPTS = 3
DEFAULT_RETRY_MAX_WAIT_SECONDS = 20


@dataclass(frozen=True)
class LLMSettings:
    groq_base_url: str
    groq_model: str
    groq_summary_model: str
    max_fixed_tokens: int
    max_context_tokens: int  # tvrdé maximum injektovaného CURRENT STATE kontextu
    sdk_max_retries: int = DEFAULT_SDK_MAX_RETRIES
    context_target_tokens: int = DEFAULT_CONTEXT_TARGET_TOKENS
    history_window_messages: int = DEFAULT_HISTORY_WINDOW_MESSAGES
    summary_trigger_tokens: int = DEFAULT_SUMMARY_TRIGGER_TOKENS
    max_summary_tokens: int = DEFAULT_MAX_SUMMARY_TOKENS
    max_history_tokens: int = DEFAULT_MAX_HISTORY_TOKENS
    llm_max_attempts: int = DEFAULT_LLM_MAX_ATTEMPTS
    retry_max_wait_seconds: int = DEFAULT_RETRY_MAX_WAIT_SECONDS
    usage_logging: bool = True
    # A5: deterministický výběr menší sady toolů podle dotazu; False = vždy všechny tooly (dřívější chování).
    tool_routing: bool = True


def _int_env(env: dict, name: str, default: int, *, min_value: int = 1) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} musí být celé číslo, je '{raw}'") from None
    if value < min_value:
        raise ValueError(f"{name} musí být >= {min_value}, je {value}")
    return value


def _bool_env(env: dict, name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def load_llm_settings(env: dict | None = None) -> LLMSettings:
    env = os.environ if env is None else env
    model = (env.get("GROQ_MODEL") or "").strip() or DEFAULT_GROQ_MODEL
    max_context = _int_env(env, "AI_MAX_CONTEXT_TOKENS", DEFAULT_MAX_CONTEXT_TOKENS)
    target_context = _int_env(env, "AI_CONTEXT_TARGET_TOKENS", min(DEFAULT_CONTEXT_TARGET_TOKENS, max_context))
    if target_context > max_context:
        raise ValueError(f"AI_CONTEXT_TARGET_TOKENS ({target_context}) nesmí být větší než AI_MAX_CONTEXT_TOKENS ({max_context})")
    max_history = _int_env(env, "AI_MAX_HISTORY_TOKENS", DEFAULT_MAX_HISTORY_TOKENS)
    max_summary = _int_env(env, "AI_MAX_SUMMARY_TOKENS", DEFAULT_MAX_SUMMARY_TOKENS)
    summary_trigger = _int_env(env, "AI_SUMMARY_TRIGGER_TOKENS", DEFAULT_SUMMARY_TRIGGER_TOKENS)
    if max_summary + summary_trigger > max_history:
        raise ValueError(
            f"AI_MAX_SUMMARY_TOKENS ({max_summary}) + AI_SUMMARY_TRIGGER_TOKENS ({summary_trigger}) "
            f"musí být <= AI_MAX_HISTORY_TOKENS ({max_history})"
        )
    return LLMSettings(
        groq_base_url=(env.get("GROQ_BASE_URL") or "").strip() or DEFAULT_GROQ_BASE_URL,
        groq_model=model,
        groq_summary_model=(env.get("GROQ_SUMMARY_MODEL") or "").strip() or model,
        max_fixed_tokens=_int_env(env, "AI_MAX_FIXED_TOKENS", DEFAULT_MAX_FIXED_TOKENS),
        max_context_tokens=max_context,
        context_target_tokens=target_context,
        history_window_messages=_int_env(env, "AI_HISTORY_WINDOW_MESSAGES", DEFAULT_HISTORY_WINDOW_MESSAGES),
        summary_trigger_tokens=summary_trigger,
        max_summary_tokens=max_summary,
        max_history_tokens=max_history,
        sdk_max_retries=_int_env(env, "GROQ_SDK_MAX_RETRIES", DEFAULT_SDK_MAX_RETRIES, min_value=0),
        llm_max_attempts=_int_env(env, "AI_LLM_MAX_ATTEMPTS", DEFAULT_LLM_MAX_ATTEMPTS),
        retry_max_wait_seconds=_int_env(env, "AI_LLM_RETRY_MAX_WAIT_SECONDS", DEFAULT_RETRY_MAX_WAIT_SECONDS),
        usage_logging=_bool_env(env, "AI_USAGE_LOG", True),
        tool_routing=_bool_env(env, "AI_TOOL_ROUTING", True),
    )


LLM_SETTINGS = load_llm_settings()
