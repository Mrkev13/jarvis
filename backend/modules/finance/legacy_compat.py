"""Legacy ↔ ledger bridge for `finance_transactions` (MRK-61) – the only place that touches the Float `amount`.

Old writers (Quick Add via `tools.add_finance_transaction`, legacy undo of linked work income, test fixtures) still set
`amount` / `category` / `transaction_type`. Before every INSERT/UPDATE this fills the ledger columns from them
(and the legacy mirror from the ledger columns for new writers), so the NOT NULL ledger columns are always set and
all readers can use `amount_minor`. Remove together with the legacy columns once nothing writes them.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import event, insert, select

from modules.finance.categories import BUILTIN_CATEGORIES, legacy_category_key
from modules.finance.models import MANUAL_ACCOUNT_KEY, FinanceAccount, FinanceCategory
from modules.finance.money import MINOR_PER_UNIT
from text_utils import fold_text
from time_utils import to_local, utc_now

MANUAL_ACCOUNT_NAME = "Ruční / hotovost"
DEFAULT_CURRENCY = "CZK"
_SEARCH_CHARS = 600


def legacy_to_minor(amount) -> int:
    """Kladná Float částka ze starého sloupce → haléře (přes Decimal z textu, ne binární float)."""
    return int((abs(Decimal(str(amount or 0))) * MINOR_PER_UNIT).to_integral_value(rounding=ROUND_HALF_UP))


def legacy_request_minor(amount) -> int:
    """Float částka z legacy API/toolu → haléře se znaménkem vstupu (nekladná/nekonečná → ≤ 0, služba ji odmítne)."""
    value = Decimal(str(amount))
    if not value.is_finite():
        return 0
    return int((value * MINOR_PER_UNIT).to_integral_value(rounding=ROUND_HALF_UP))


def minor_to_legacy(amount_minor: int) -> float:
    """Zrcadlo pro starý sloupec `amount` a legacy API: vždy kladné, v jednotkách."""
    return float(Decimal(abs(int(amount_minor))) / MINOR_PER_UNIT)


def _direction_of(transaction_type: str | None) -> str:
    return "in" if (transaction_type or "").strip().lower() == "income" else "out"


def manual_account_id(connection) -> int:
    """Id vestavěného účtu „Ruční / hotovost“ (migrace 0025 ho zakládá; DB bez migrací ho dostane tady)."""
    table = FinanceAccount.__table__
    found = connection.execute(select(table.c.id).where(table.c.key == MANUAL_ACCOUNT_KEY)).scalar()
    if found is not None:
        return found
    return connection.execute(insert(table).values(
        key=MANUAL_ACCOUNT_KEY, name=MANUAL_ACCOUNT_NAME, kind="cash", currency=DEFAULT_CURRENCY,
        created_at=utc_now())).inserted_primary_key[0]


def builtin_category_id(connection, key: str) -> int:
    """Id vestavěné kategorie podle klíče; chybějící vestavěné kategorie doplní (idempotentně)."""
    table = FinanceCategory.__table__
    found = connection.execute(select(table.c.id).where(table.c.key == key)).scalar()
    if found is not None:
        return found
    ids = dict(connection.execute(select(table.c.key, table.c.id).where(table.c.key.isnot(None))).all())
    for k, name, kind, parent in BUILTIN_CATEGORIES:
        if k not in ids:
            ids[k] = connection.execute(insert(table).values(
                key=k, name=name, kind=kind, parent_id=ids.get(parent) if parent else None,
                created_at=utc_now())).inserted_primary_key[0]
    return ids[key]


def category_name(connection, category_id: int | None) -> str | None:
    if category_id is None:
        return None
    table = FinanceCategory.__table__
    return connection.execute(select(table.c.name).where(table.c.id == category_id)).scalar()


def search_text_of(*parts) -> str:
    return fold_text(" ".join(str(p) for p in parts if p)).strip()[:_SEARCH_CHARS]


def _fill(connection, tx, *, insert_: bool, changed: set[str]) -> None:
    if insert_ and tx.created_at is None:
        tx.created_at = utc_now()
    # směr a typ
    if tx.direction is None or (not insert_ and "transaction_type" in changed and "direction" not in changed):
        tx.direction = _direction_of(tx.transaction_type)
    if tx.transaction_type is None or (not insert_ and "direction" in changed and "transaction_type" not in changed):
        tx.transaction_type = "income" if tx.direction == "in" else "expense"
    # částka: nový zápis nastaví amount_minor, starý amount
    sign = 1 if tx.direction == "in" else -1
    if tx.amount_minor is None or (not insert_ and "amount" in changed and "amount_minor" not in changed):
        tx.amount_minor = sign * legacy_to_minor(tx.amount)
    else:
        tx.amount_minor = sign * abs(int(tx.amount_minor))
    tx.amount = minor_to_legacy(tx.amount_minor)
    if tx.currency is None:
        tx.currency = DEFAULT_CURRENCY
    if tx.source is None:
        tx.source = "manual"
    if tx.account_id is None:
        tx.account_id = manual_account_id(connection)
    moved = not insert_ and "created_at" in changed and "booked_on" not in changed and tx.source != "import"
    if tx.booked_on is None or (moved and tx.created_at is not None):
        tx.booked_on = to_local(tx.created_at).date()  # u ručních řádků je den zaúčtování pražský den vzniku
    if tx.review_flag is None:
        tx.review_flag = False
    # kategorie: starý text → vestavěná kategorie jako ruční volba (zachová, co uživatel kdysi zvolil)
    # text kategorie přemapuje jen u starých zápisů (import/ruční zápis nové služby nastavují kategorie samy)
    legacy_remap = not insert_ and "override_category_id" not in changed and tx.category_source in (None, "legacy") \
        and bool("category" in changed or {"transaction_type", "direction"} & changed)
    if (tx.override_category_id is None and tx.system_category_id is None and tx.category) or legacy_remap:
        tx.override_category_id = builtin_category_id(connection, legacy_category_key(tx.category, tx.direction))
        tx.category_source = "legacy"
    tx.effective_category_id = tx.override_category_id or tx.system_category_id
    if not tx.category:
        tx.category = category_name(connection, tx.effective_category_id) or "Nezařazeno"
    tx.search_text = search_text_of(tx.description, tx.counterparty_name, tx.category,
                                    category_name(connection, tx.effective_category_id))


def install_legacy_compat(model) -> None:
    """Zaregistruje doplňování sloupců pro model FinanceTransaction (volá models.py jednou při importu)."""
    from sqlalchemy import inspect as sa_inspect

    @event.listens_for(model, "before_insert")
    def _before_insert(mapper, connection, target):
        _fill(connection, target, insert_=True, changed=set())

    @event.listens_for(model, "before_update")
    def _before_update(mapper, connection, target):
        state = sa_inspect(target)
        changed = {attr.key for attr in state.attrs if attr.history.has_changes()}
        _fill(connection, target, insert_=False, changed=changed)
