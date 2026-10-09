"""Sdílené formátování řádků CURRENT STATE (MRK-20) – list grafu importů pro sekce modulů
(`ContextSection.build`), aby nemusely importovat context_service (ten importuje registr modulů)."""
from __future__ import annotations

from text_utils import WEEKDAYS_CZ_SHORT, clip

WINDOW_DAYS = 7
MAX_ITEMS = 3
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
WEEKDAYS = WEEKDAYS_CZ_SHORT


def fmt_num(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")


def short(text: str, limit: int = 60) -> str:
    return clip(text, limit)


def list_or_none(items: list[str], total: int) -> str:
    if not items:
        return "žádné"
    more = f" (+{total - len(items)} další)" if total > len(items) else ""
    return "; ".join(items) + more
