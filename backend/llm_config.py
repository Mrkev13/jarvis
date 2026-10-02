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


@dataclass(frozen=True)
class LLMSettings:
    groq_base_url: str
    groq_model: str
    groq_summary_model: str
    max_fixed_tokens: int
    max_context_tokens: int  # rozpočet pro injektovaný kontext (využije A3/A4)


def _int_env(env: dict, name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} musí být celé číslo, je '{raw}'") from None
    if value <= 0:
        raise ValueError(f"{name} musí být kladné, je {value}")
    return value


def load_llm_settings(env: dict | None = None) -> LLMSettings:
    env = os.environ if env is None else env
    model = (env.get("GROQ_MODEL") or "").strip() or DEFAULT_GROQ_MODEL
    return LLMSettings(
        groq_base_url=(env.get("GROQ_BASE_URL") or "").strip() or DEFAULT_GROQ_BASE_URL,
        groq_model=model,
        groq_summary_model=(env.get("GROQ_SUMMARY_MODEL") or "").strip() or model,
        max_fixed_tokens=_int_env(env, "AI_MAX_FIXED_TOKENS", DEFAULT_MAX_FIXED_TOKENS),
        max_context_tokens=_int_env(env, "AI_MAX_CONTEXT_TOKENS", DEFAULT_MAX_CONTEXT_TOKENS),
    )


LLM_SETTINGS = load_llm_settings()
