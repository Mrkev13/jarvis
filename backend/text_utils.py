"""Sdílené drobnosti pro text zobrazovaný uživateli (Roadmap 3.5) – bez závislostí na DB i LLM."""
from __future__ import annotations

WEEKDAYS_CZ = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
WEEKDAYS_CZ_SHORT = ("po", "út", "st", "čt", "pá", "so", "ne")


def clip(text, limit: int = 70) -> str:
    """Sloučí bílé znaky a zkrátí na `limit` znaků (s „…")."""
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"
