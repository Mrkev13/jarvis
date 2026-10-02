"""Hrubý, deterministický odhad tokenů pro hlídání rozpočtu LLM requestů.

Bez tokenizer závislosti: ~4 znaky ASCII na token; ne-ASCII znaky (česká diakritika)
se počítají dvojnásobně, protože je BPE tokenizéry typicky dělí na víc tokenů.
Odhad je záměrně spíš konzervativní – slouží k regresním limitům, ne k účtování.
"""
import json
import math
from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    weighted_chars = (len(text) - non_ascii) + 2 * non_ascii
    return math.ceil(weighted_chars / 4)


def estimate_prompt_tokens(system_prompt: str) -> int:
    return estimate_tokens(system_prompt)


def estimate_tool_schema_tokens(tools: list[dict]) -> int:
    # Kompaktní JSON – stejný obsah, jaký se posílá v requestu (bez formátovacích mezer).
    return estimate_tokens(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))


@dataclass(frozen=True)
class FixedOverhead:
    prompt_tokens: int
    tool_tokens: int
    tool_count: int

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.tool_tokens


def estimate_fixed_overhead(system_prompt: str, tools: list[dict]) -> FixedOverhead:
    """Fixní režie každého LLM volání: system prompt + všechna poslaná tool schémata."""
    return FixedOverhead(
        prompt_tokens=estimate_prompt_tokens(system_prompt),
        tool_tokens=estimate_tool_schema_tokens(tools),
        tool_count=len(tools),
    )
