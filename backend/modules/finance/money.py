"""Money as integers (MRK-61): `amount_minor` = signed haléře (minus = money out), always with a 3-letter currency.

Floats appear only at the legacy boundary (`legacy_compat`); parsing goes through Decimal, never binary floats.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MINOR_PER_UNIT = 100  # CZK/EUR/USD mají 2 desetinná místa; jiné měny až s importem, který je potřebuje
MAX_ABS_MINOR = 10_000_000_000  # 100 mil. jednotek – horní mez rozumné jedné transakce
CURRENCIES = frozenset({"CZK", "EUR", "USD"})


class MoneyError(ValueError):
    """Neplatná částka nebo měna (zpráva bez hodnoty – může jít o data z výpisu)."""


def parse_minor(value) -> int:
    """Kladná částka v jednotkách (int / Decimal / „1 234,50" / „1234.5") → haléře. Záporné a nulové odmítne."""
    if isinstance(value, bool) or value is None:
        raise MoneyError("amount_invalid")
    if isinstance(value, float):
        raise MoneyError("amount_float")  # float přichází jen přes legacy_compat.legacy_to_minor
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise MoneyError("amount_invalid") from None
    if not amount.is_finite() or amount <= 0:
        raise MoneyError("amount_invalid")
    minor = int((amount * MINOR_PER_UNIT).to_integral_value(rounding=ROUND_HALF_UP))
    if minor <= 0 or minor > MAX_ABS_MINOR:
        raise MoneyError("amount_out_of_range")
    return minor


def signed_minor(minor_abs: int, direction: str) -> int:
    if direction not in ("in", "out"):
        raise MoneyError("direction_invalid")
    return minor_abs if direction == "in" else -minor_abs


def check_currency(currency: str | None) -> str:
    code = (currency or "").strip().upper()
    if code not in CURRENCIES:
        raise MoneyError("currency_unsupported")
    return code


def minor_to_decimal(minor: int) -> Decimal:
    return (Decimal(minor) / MINOR_PER_UNIT).quantize(Decimal("0.01"))
