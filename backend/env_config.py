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
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


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


def parse_flag(raw: str | None, default: bool) -> tuple[bool, bool]:
    """Přísný přepínač (Roadmap 6C, moduly): (hodnota, platná?).

    Na rozdíl od `env_bool` je nesmyslná hodnota („ture", „maybe") = default, ne nepravda – překlep v `.env`
    nesmí potichu schovat hotový modul. Volající rozhoduje, jak neplatnou hodnotu ohlásit.
    """
    if raw is None or not raw.strip():
        return default, True
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True, True
    if value in FALSE_VALUES:
        return False, True
    return default, False


def env_flag(name: str, default: bool) -> tuple[bool, bool]:
    return parse_flag(os.environ.get(name), default)
