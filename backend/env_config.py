"""Jediný parser proměnných prostředí (Roadmap 3.5).

Pravidla pro všechny moduly: hodnota se ořízne; prázdná / chybějící = default; bool je pravda pro
1 / true / yes / on (bez ohledu na velikost písmen), cokoliv jiného = nepravda. Celá čísla mají volitelné
minimum (menší hodnota se zvedne). `.env` se načte jednou při importu (existující proměnné nepřepisuje).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def env_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    return default if raw is None or not raw.strip() else raw.strip()


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in TRUE_VALUES


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    value = default if raw is None or not raw.strip() else int(raw.strip())
    return value if minimum is None else max(minimum, value)
