"""Paměť (MRK-84): co se smí použít, odhalení duplicit a jednotné vyhledávání.

- Použitelná vzpomínka = aktivní a nevypršená (`expires_at` je NULL nebo v budoucnosti, naive UTC). Jen takové jdou do
  AI kontextu (prefetch), do planneru, do read toolu `get_memories` a do globálního vyhledávání.
- Duplicita = použitelná (aktivní a nevypršená) vzpomínka se stejným textem po sjednocení mezer a velikosti písmen (bez ohledu na oblast):
  uložení duplicity nevytvoří nový řádek a vrátí existující (bez zápisu, tedy bez Aktivity). Vypršená vzpomínka
  duplicitou není: uložení stejného textu s novou platností vytvoří novou použitelnou vzpomínku.
- Druhy: statuses.MEMORY_KINDS (fact | temporary | decision); `temporary` vyžaduje `expires_at`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_

from models import Memory
from statuses import MEMORY_KINDS
from time_utils import utc_now


class MemoryError(ValueError):
    pass


def _naive_utc(now: datetime | None) -> datetime:
    """DB drží naive UTC (time_utils.utc_now); časová zóna z volajícího se převede."""
    now = now or utc_now()
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


def usable(query, now: datetime | None = None):
    """Filtr na dotaz nad Memory: aktivní a nevypršené."""
    now = _naive_utc(now)
    return query.filter(Memory.active.is_(True), or_(Memory.expires_at.is_(None), Memory.expires_at > now))


def is_usable(m: Memory, now: datetime | None = None) -> bool:
    now = _naive_utc(now)
    return bool(m.active) and (m.expires_at is None or m.expires_at > now)


def normalize_content(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def find_duplicate(db, content: str, now: datetime | None = None) -> Memory | None:
    """Použitelná (aktivní a nevypršená) vzpomínka se stejným (normalizovaným) textem."""
    key = normalize_content(content)
    if not key:
        return None
    # jen id + text (zápisová cesta, ne vyhledávání); SQL LIKE neumí casefold mimo ASCII, proto porovnání tady
    for mid, text in usable(db.query(Memory.id, Memory.content), now).all():
        if normalize_content(text) == key:
            return db.get(Memory, mid)
    return None


def validate_kind(kind: str | None, expires_at: datetime | None) -> str:
    kind = (kind or "fact").strip().lower()
    if kind not in MEMORY_KINDS:
        raise MemoryError(f"Druh vzpomínky musí být jeden z: {', '.join(MEMORY_KINDS)}.")
    if kind == "temporary" and expires_at is None:
        raise MemoryError("Dočasná vzpomínka potřebuje datum platnosti (expires_at).")
    return kind
