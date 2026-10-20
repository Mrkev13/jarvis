"""Built-in Finance categories and the mapping of legacy free-text categories onto them (MRK-61).

Migration 0025 seeds a frozen copy of BUILTIN_CATEGORIES; `ensure_builtin_categories` makes the same set exist in
databases created without migrations (tests). Keys are stable identities; names are what the UI shows.
"""
from __future__ import annotations

from text_utils import fold_text

# (key, name, kind, parent key) – rodič vždy před dětmi; nejvýš dvě úrovně.
BUILTIN_CATEGORIES: tuple[tuple[str, str, str, str | None], ...] = (
    ("housing", "Bydlení", "expense", None),
    ("food", "Potraviny", "expense", None),
    ("restaurants", "Restaurace a jídlo", "expense", None),
    ("transport", "Doprava", "expense", None),
    ("shopping", "Nákupy", "expense", None),
    ("health", "Zdraví", "expense", None),
    ("entertainment", "Zábava", "expense", None),
    ("education", "Vzdělávání", "expense", None),
    ("subscriptions", "Předplatné", "expense", None),
    ("income", "Příjmy", "income", None),
    ("salary", "Výplata", "income", "income"),
    ("income_other", "Ostatní příjmy", "income", "income"),
    ("other", "Ostatní", "expense", None),
    ("transfers", "Převody", "transfer", None),
    ("uncategorized", "Nezařazeno", "system", None),
)

# Starý volný text kategorie (bez diakritiky, malá písmena) → klíč vestavěné kategorie. Neznámé → other / income_other.
LEGACY_CATEGORY_KEYS: dict[str, str] = {
    "bydleni": "housing", "najem": "housing", "energie": "housing", "housing": "housing", "rent": "housing",
    "potraviny": "food", "food": "food", "groceries": "food",
    "jidlo": "restaurants", "restaurace": "restaurants", "restaurants": "restaurants",
    "doprava": "transport", "transport": "transport",
    "nakupy": "shopping", "shopping": "shopping",
    "zdravi": "health", "health": "health",
    "zabava": "entertainment", "entertainment": "entertainment",
    "vzdelavani": "education", "skola": "education", "education": "education",
    "predplatne": "subscriptions", "subscriptions": "subscriptions",
    "vyplata": "salary", "plat": "salary", "salary": "salary", "work": "salary", "prace": "salary",
    "prijem": "income_other", "income": "income_other",
    "prevod": "transfers", "prevody": "transfers", "transfer": "transfers",
    "ostatni": "other", "other": "other",
}


def legacy_category_key(category: str | None, direction: str) -> str:
    """Klíč vestavěné kategorie pro starý text; směr rozhodne fallback (příjem → income_other, jinak other)."""
    key = LEGACY_CATEGORY_KEYS.get(fold_text(category or "").strip())
    if key is None:
        return "income_other" if direction == "in" else "other"
    if direction == "in" and key not in ("salary", "income_other", "transfers"):
        return "income_other"  # příjem s výdajovou kategorií by v přehledu výdajů nedával smysl
    return key
