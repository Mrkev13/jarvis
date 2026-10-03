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


# ===== AI akce (Roadmap 4C): lidské popisky místo interních názvů toolů =====

# Interní název toolu se nemění (pending akce, audit entity_type); tohle je jen text pro uživatele.
AI_TOOL_LABELS_CZ = {
    "add_work_session": "Přidán pracovní záznam",
    "add_finance_transaction": "Přidána transakce",
    "add_school_subject": "Přidán předmět",
    "add_school_assignment": "Přidán úkol",
    "add_school_exam": "Přidána zkouška",
    "update_wot_resource": "Aktualizovány zdroje WoT",
    "upsert_wot_grind": "Uložen grind WoT",
    "upsert_mff_character": "Uložena postava MFF",
    "upsert_goal": "Uložen cíl",
    "save_memory": "Uložena poznámka do paměti",
    "modify_records": "Upravená data",
    "add_reminder": "Přidána připomínka",
    "manage_reminder": "Upravená připomínka",
    "undo_change": "Vrácená změna",
}

_WOT_RESOURCES_CZ = {"credits": "Credits", "gold": "Gold", "bonds": "Bonds", "free_xp": "Free XP"}


def ai_action_label(tool) -> str:
    """„add_work_session" → „Přidán pracovní záznam"; neznámý tool → „Akce AI"."""
    return AI_TOOL_LABELS_CZ.get(str(tool or ""), "Akce AI")


def _iso_date_cz(value) -> str:
    from datetime import date as _date

    try:
        return format_date_cz(_date.fromisoformat(str(value)[:10]))
    except (TypeError, ValueError):
        return str(value)


def ai_action_details(tool, arguments) -> str:
    """Krátký lidský popis argumentů akce (bez interních klíčů „k=v"): „2. 10. 2026 · 6,5 h · Klient XYZ"."""
    a = arguments if isinstance(arguments, dict) else {}
    plan = a.get("plan") if isinstance(a.get("plan"), dict) else None
    preview = plan.get("preview") if plan and isinstance(plan.get("preview"), dict) else None
    if preview:
        title = clip(preview.get("title") or "", 80)
        try:
            count = int(preview.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 1:
            return f"{title} ({count} {plural_cz(count, 'záznam', 'záznamy', 'záznamů')})"
        items = preview.get("items") if isinstance(preview.get("items"), list) else []
        label = items[0].get("label") if items and isinstance(items[0], dict) else None
        return f"{title}: {clip(label, 60)}" if label else title

    parts: list[str] = []
    if tool == "add_work_session":
        if a.get("date_value"):
            parts.append(_iso_date_cz(a["date_value"]))
        if a.get("hours") not in (None, ""):
            parts.append(format_hours_cz(a["hours"]))
        if a.get("project"):
            parts.append(clip(a["project"], 40))
    elif tool == "add_finance_transaction":
        return finance_summary_cz(a.get("transaction_type"), a.get("amount") or 0, a.get("category"), a.get("description"))
    elif tool in ("add_school_assignment", "add_school_exam"):
        if a.get("title"):
            parts.append(clip(a["title"], 60))
        due = a.get("due_date") or a.get("exam_date")
        if due:
            parts.append(f"termín {_iso_date_cz(due)}")
    elif tool == "update_wot_resource":
        res = _WOT_RESOURCES_CZ.get(str(a.get("resource") or ""), str(a.get("resource") or ""))
        parts.append(f"{res}: {format_num_cz(a.get('amount') or 0, 0)}")
    elif tool == "upsert_wot_grind":
        if a.get("tank"):
            parts.append(clip(a["tank"], 40))
        if a.get("xp_remaining") not in (None, ""):
            parts.append(f"zbývá {format_num_cz(a['xp_remaining'], 0)} XP")
    elif tool in ("add_school_subject", "upsert_mff_character"):
        if a.get("name"):
            parts.append(clip(a["name"], 60))
    elif tool == "upsert_goal":
        if a.get("title"):
            parts.append(clip(a["title"], 60))
        if a.get("progress") not in (None, ""):
            parts.append(f"{format_num_cz(a['progress'], 0)} %")
    elif tool == "save_memory":
        if a.get("content"):
            parts.append(clip(a["content"], 60))
    elif a.get("title"):
        parts.append(clip(a["title"], 60))
    return " · ".join(p for p in parts if p)


def ai_action_summary(tool, arguments, prefix: str = "") -> str:
    """Text do Aktivity: „Přidán pracovní záznam (AI): 2. 10. 2026 · 6,5 h · Klient XYZ"."""
    label = ai_action_label(tool)
    details = ai_action_details(tool, arguments)
    head = f"{prefix}{label} (AI)"
    return f"{head}: {details}" if details else head


# Oblasti pro text (stejné popisky jako frontend lib/areas.ts); neznámá oblast → s velkým prvním písmenem.
AREA_LABELS_CZ = {
    "school": "Škola", "work": "Práce", "finance": "Finance", "wot": "World of Tanks", "mff": "Marvel FF",
    "personal": "Osobní", "fitness": "Fitness", "hobby": "Hobby", "travel": "Cestování", "general": "Obecné",
    "reminders": "Připomínky", "briefing": "Přehled", "review": "Týdenní přehled", "goals": "Cíle",
    "memory": "Paměť", "ai": "AI", "system": "Systém",
}


def area_label_cz(area) -> str:
    a = str(area or "").strip()
    return AREA_LABELS_CZ.get(a.lower(), a[:1].upper() + a[1:]) if a else ""


def planner_action_line(idx: int, action: dict) -> str:
    """Řádek plánu v textu odpovědi chatu: „1. Připravit se na zkoušku: test (Škola)" – bez interního klíče oblasti."""
    title = str(action.get("title") or "").strip()
    area = area_label_cz(action.get("area"))
    return f"{idx}. {title} ({area})" if area else f"{idx}. {title}"
