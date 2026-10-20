"""Adapter contract, normalized rows and deterministic dedupe keys (MRK-62)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import BinaryIO, Iterator, Protocol, Union

from text_utils import fold_text

ROW_STATUSES = ("booked", "pending")
_LONG_DIGITS = re.compile(r"\d{12,}")  # možná čísla karet/účtů – nikdy do otisku ani do uloženého popisu
DESCRIPTION_MAX = 255
COUNTERPARTY_MAX = 200
BANK_ID_MAX = 100
SYMBOL_RE = re.compile(r"^\d{1,10}$")
HEAD_BYTES = 4096  # kolik bajtů ze začátku souboru dostane detect()


class ImportFailure(Exception):
    """Selhání importu pro uživatele: HTTP status + bezpečný kód (nikdy hodnota z výpisu)."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


@dataclass(frozen=True)
class NormalizedRow:
    """Jeden řádek výpisu v jednotném tvaru. `amount_minor` se znaménkem (minus = odchozí platba)."""
    row_no: int
    booked_on: date
    amount_minor: int
    currency: str
    status: str = "booked"  # booked / pending (blokace se neimportují)
    value_on: date | None = None
    bank_txn_id: str | None = None
    counterparty_name: str | None = None
    counterparty_account_masked: str | None = None
    counterparty_account_hash: str | None = None
    vs: str | None = None
    ks: str | None = None
    ss: str | None = None
    description: str = ""
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # jen klíče z adapter.extra_allowlist

    @property
    def direction(self) -> str:
        return "in" if self.amount_minor >= 0 else "out"


@dataclass(frozen=True)
class RowError:
    """Neplatný řádek: číslo řádku + bezpečný kód + název pole. Nikdy hodnota."""
    row_no: int
    code: str
    field: str | None = None


ParsedRow = Union[NormalizedRow, RowError]


class ImportAdapter(Protocol):
    """Parser jednoho formátu banky. Jen čte – žádná DB, žádné logování hodnot."""
    id: str  # např. "mbank_csv"
    family: str  # rodina bankovních ID (txn_key "bank:<family>:<id>"), např. "mbank"
    version: str
    extra_allowlist: frozenset[str]

    def detect(self, head: bytes) -> bool: ...

    def parse(self, stream: BinaryIO) -> Iterator[ParsedRow]: ...


class AdapterRegistry:
    """Výběr adaptéru podle podpisu souboru. Žádná nebo víc shod = `unknown_format` – nikdy se nehádá."""

    def __init__(self):
        self._adapters: dict[str, ImportAdapter] = {}

    def register(self, adapter: ImportAdapter) -> None:
        self._adapters[adapter.id] = adapter

    def unregister(self, adapter_id: str) -> None:
        self._adapters.pop(adapter_id, None)

    def get(self, adapter_id: str) -> ImportAdapter | None:
        return self._adapters.get(adapter_id)

    def select(self, head: bytes) -> ImportAdapter:
        matches = [a for a in self._adapters.values() if _safe_detect(a, head)]
        if len(matches) != 1:
            raise ImportFailure(415, "unknown_format")
        return matches[0]


def _safe_detect(adapter: ImportAdapter, head: bytes) -> bool:
    try:
        return bool(adapter.detect(head))
    except Exception:  # noqa: BLE001 – chybný detektor = neshoda, ne pád uploadu
        return False


# Produkční adaptéry registruje MRK-63; testy registrují syntetický adaptér.
REGISTRY = AdapterRegistry()


# ---------- normalizace a klíče ----------

def normalize_description(text: str | None) -> str:
    """Pro otisk: bez diakritiky, malá písmena, bez běhů ≥ 12 číslic, jedna mezera."""
    return " ".join(_LONG_DIGITS.sub(" ", fold_text(text or "")).split())


def sanitize_description(text: str | None) -> str:
    """Pro uložení: běhy ≥ 12 číslic → „…1234“ (možná čísla karet/účtů), zkrácení na DESCRIPTION_MAX."""
    clean = " ".join(str(text or "").split())
    return _LONG_DIGITS.sub(lambda m: "…" + m.group()[-4:], clean)[:DESCRIPTION_MAX]


def bank_txn_key(family: str, bank_txn_id: str) -> str:
    return f"bank:{family}:{bank_txn_id}"


def fingerprint(account_id: int, row: NormalizedRow) -> str:
    parts = (str(account_id), row.booked_on.isoformat(), str(row.amount_minor), row.currency,
             row.counterparty_account_hash or "", row.vs or "", row.ks or "", row.ss or "",
             normalize_description(row.description))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def fingerprint_txn_key(fp: str, ordinal: int) -> str:
    """Identita k-tého stejného řádku (multiset): `fp:<otisk>:<pořadí>` – stejné platby téhož dne přežijí."""
    return f"fp:{fp}:{ordinal}"
