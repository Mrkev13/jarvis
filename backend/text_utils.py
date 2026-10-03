"""Sdílené drobnosti pro text zobrazovaný uživateli (Roadmap 3.5) – bez závislostí na DB i LLM."""
from __future__ import annotations

WEEKDAYS_CZ = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
WEEKDAYS_CZ_SHORT = ("po", "út", "st", "čt", "pá", "so", "ne")


def clip(text, limit: int = 70) -> str:
    """Sloučí bílé znaky a zkrátí na `limit` znaků (s „…")."""
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def plural_cz(n: int, one: str, few: str, many: str) -> str:
    """Česká množná čísla: 1 den, 2–4 dny, 0/5+ dní."""
    a = abs(int(n))
    return one if a == 1 else few if 2 <= a <= 4 else many


def format_date_cz(d) -> str:
    """date → „2. 10. 2026" (pro text pro uživatele; ISO patří jen do API polí)."""
    return f"{d.day}. {d.month}. {d.year}"


def days_left_cz(days: int) -> str:
    """Kolik dní zbývá do termínu: „dnes", „zítra", „zbývají 3 dny", „zbývá 5 dní"."""
    if days == 0:
        return "dnes"
    if days == 1:
        return "zítra"
    verb = "zbývají" if 2 <= days <= 4 else "zbývá"
    return f"{verb} {days} {plural_cz(days, 'den', 'dny', 'dní')}"
