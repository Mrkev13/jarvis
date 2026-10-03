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


def format_num_cz(value, max_decimals: int = 2) -> str:
    """Číslo pro text: „0,5", „12", „1 250,75" (desetinná čárka, mezera mezi tisíci, bez zbytečných nul)."""
    if value is None:
        return "–"
    f = round(float(value), max_decimals)
    if f == 0:
        f = 0.0  # žádné „-0"
    s = f"{f:,.{max_decimals}f}" if max_decimals > 0 else f"{f:,.0f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",")


def format_hours_cz(hours, max_decimals: int = 2) -> str:
    """„0,5 h", „8 h"."""
    return f"{format_num_cz(hours, max_decimals)} h"


def memory_count_cz(n: int) -> str:
    """„Zohledněna 1 poznámka z paměti" / „Zohledněny 3 poznámky…" / „Zohledněno 5 poznámek…"."""
    verb = plural_cz(n, "Zohledněna", "Zohledněny", "Zohledněno")
    return f"{verb} {n} {plural_cz(n, 'poznámka', 'poznámky', 'poznámek')} z paměti"


def format_czk_cz(amount) -> str:
    """Přesná částka: celé koruny bez desetin („4 875 Kč"), jinak na haléře („2 437,50 Kč")."""
    cents = round(float(amount or 0) * 100)
    if cents % 100 == 0:
        return f"{format_num_cz(cents / 100, 0)} Kč"
    s = f"{abs(cents) / 100:,.2f}".replace(",", " ").replace(".", ",")
    return f"{'-' if cents < 0 else ''}{s} Kč"


def finance_category_cz(category) -> str:
    """Kategorie transakce pro text: systémová „work" (zápis z Práce) → „Práce"; ostatní je text uživatele."""
    c = str(category or "").strip()
    return "Práce" if c.lower() == "work" else c


def finance_summary_cz(transaction_type, amount, category=None, description=None) -> str:
    """„Výdaj 189,90 Kč · food (Oběd)" / „Příjem 15 000 Kč · Výplata"."""
    kind = "Příjem" if transaction_type == "income" else "Výdaj"
    s = f"{kind} {format_czk_cz(amount)}"
    cat = finance_category_cz(category)
    if cat:
        s += f" · {cat}"
    if description:
        s += f" ({clip(description, 60)})"
    return s
