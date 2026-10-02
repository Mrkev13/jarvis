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
DEFAULT_MAX_CONTEXT_TOKENS = 2500
# Retry: SDK vlastní retry vypnuto (0), aby každý 429/5xx prošel aplikační smyčkou a byl vidět v logu.
DEFAULT_SDK_MAX_RETRIES = 0
DEFAULT_LLM_MAX_ATTEMPTS = 3
DEFAULT_RETRY_MAX_WAIT_SECONDS = 20


@dataclass(frozen=True)
class LLMSettings:
    groq_base_url: str
    groq_model: str
    groq_summary_model: str
    max_fixed_tokens: int
    max_context_tokens: int  # rozpočet pro injektovaný kontext (využije A3/A4)
    sdk_max_retries: int = DEFAULT_SDK_MAX_RETRIES
    llm_max_attempts: int = DEFAULT_LLM_MAX_ATTEMPTS
    retry_max_wait_seconds: int = DEFAULT_RETRY_MAX_WAIT_SECONDS
    usage_logging: bool = True


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
    return LLMSettings(
        groq_base_url=(env.get("GROQ_BASE_URL") or "").strip() or DEFAULT_GROQ_BASE_URL,
        groq_model=model,
        groq_summary_model=(env.get("GROQ_SUMMARY_MODEL") or "").strip() or model,
        max_fixed_tokens=_int_env(env, "AI_MAX_FIXED_TOKENS", DEFAULT_MAX_FIXED_TOKENS),
        max_context_tokens=_int_env(env, "AI_MAX_CONTEXT_TOKENS", DEFAULT_MAX_CONTEXT_TOKENS),
        sdk_max_retries=_int_env(env, "GROQ_SDK_MAX_RETRIES", DEFAULT_SDK_MAX_RETRIES, min_value=0),
        llm_max_attempts=_int_env(env, "AI_LLM_MAX_ATTEMPTS", DEFAULT_LLM_MAX_ATTEMPTS),
        retry_max_wait_seconds=_int_env(env, "AI_LLM_RETRY_MAX_WAIT_SECONDS", DEFAULT_RETRY_MAX_WAIT_SECONDS),
        usage_logging=_bool_env(env, "AI_USAGE_LOG", True),
    )


LLM_SETTINGS = load_llm_settings()
