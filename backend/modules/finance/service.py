"""Finance ledger service (MRK-61). Caller-owned transactions: functions flush and write the audit row in the same
session; the caller commits. Money is `amount_minor` (signed int) + `currency`; Float only via `legacy_compat`.

Voided rows (`voided_at`) are kept for history but never counted, searched or offered – use `active_transactions`.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from activity_service import log_activity
from models import FinanceTransaction
from modules.finance.categories import BUILTIN_CATEGORIES, legacy_category_key
from modules.finance.legacy_compat import builtin_category_id, manual_account_id, minor_to_legacy
from modules.finance.models import ACCOUNT_KINDS, CATEGORY_KINDS, MANUAL_ACCOUNT_KEY, FinanceAccount, FinanceCategory
from modules.finance.money import MoneyError, check_currency, minor_to_decimal, signed_minor
from text_utils import clip, format_czk_cz
from time_utils import utc_now

NAME_MAX = 80
ACCOUNT_NAME_MAX = 120
DESCRIPTION_MAX = 255
VOID_REASON_MAX = 200
_DIGITS = re.compile(r"\d")
_IDENTIFIER_SALT = "standa-hub:finance-account:v1:"


class FinanceError(ValueError):
    """Chyba pro uživatele: HTTP status + česká zpráva bez dat z výpisu."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---------- účty ----------

def account_identifier(raw: str | None) -> tuple[str | None, str | None]:
    """Číslo účtu/karty → („…1234", otisk pro párování). Celé číslo se nikdy neukládá.
    Otisk je pro rozpoznání téhož účtu, ne pro utajení (čísla účtů mají malou entropii) – chrání ho soukromá DB."""
    normalized = re.sub(r"[\s-]", "", raw or "").upper()
    if not normalized:
        return None, None
    digits = "".join(_DIGITS.findall(normalized))
    masked = f"…{(digits or normalized)[-4:]}"
    return masked, hashlib.sha256((_IDENTIFIER_SALT + normalized).encode()).hexdigest()


def account_dict(a: FinanceAccount) -> dict:
    return {"id": a.id, "name": a.name, "institution": a.institution, "kind": a.kind, "currency": a.currency,
            "masked_identifier": a.masked_identifier, "builtin": a.key is not None,
            "archived": a.archived_at is not None}


def list_accounts(db: Session, include_archived: bool = False) -> list[dict]:
    manual_account_id(db.connection())  # vestavěný účet existuje vždy
    q = db.query(FinanceAccount)
    if not include_archived:
        q = q.filter(FinanceAccount.archived_at.is_(None))
    return [account_dict(a) for a in q.order_by(FinanceAccount.key.is_(None), FinanceAccount.name, FinanceAccount.id)]


def _clean_name(value, limit: int) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise FinanceError(422, "Název je povinný.")
    if len(name) > limit:
        raise FinanceError(422, f"Název může mít nejvýš {limit} znaků.")
    return name


def create_account(db: Session, *, name, kind="current", currency="CZK", institution=None, identifier=None,
                   user_context: str = "manual") -> FinanceAccount:
    if kind not in ACCOUNT_KINDS:
        raise FinanceError(422, "Neznámý druh účtu.")
    try:
        currency = check_currency(currency)
    except MoneyError:
        raise FinanceError(422, "Nepodporovaná měna.") from None
    masked, digest = account_identifier(identifier)
    if digest and db.query(FinanceAccount.id).filter(FinanceAccount.identifier_hash == digest).first():
        raise FinanceError(409, "Tento účet už existuje.")
    account = FinanceAccount(name=_clean_name(name, ACCOUNT_NAME_MAX), kind=kind, currency=currency,
                             institution=clip(institution, 120) if institution else None,
                             masked_identifier=masked, identifier_hash=digest)
    db.add(account)
    db.flush()
    log_activity(db, "finance", "create", f"Účet přidán: {account.name}", entity_type="FinanceAccount",
                 entity_id=account.id, delta={"name": {"old": None, "new": account.name}}, user_context=user_context)
    return account


def _account(db: Session, account_id: int) -> FinanceAccount:
    account = db.get(FinanceAccount, account_id)
    if account is None:
        raise FinanceError(404, "Účet neexistuje.")
    return account


def update_account(db: Session, account_id: int, *, name=None, institution=None, kind=None,
                   user_context: str = "manual") -> FinanceAccount:
    account = _account(db, account_id)
    delta = {}
    if name is not None and _clean_name(name, ACCOUNT_NAME_MAX) != account.name:
        delta["name"] = {"old": account.name, "new": _clean_name(name, ACCOUNT_NAME_MAX)}
        account.name = delta["name"]["new"]
    if institution is not None and (institution or None) != account.institution:
        delta["institution"] = {"old": account.institution, "new": institution or None}
        account.institution = institution or None
    if kind is not None and kind != account.kind:
        if kind not in ACCOUNT_KINDS:
            raise FinanceError(422, "Neznámý druh účtu.")
        delta["kind"] = {"old": account.kind, "new": kind}
        account.kind = kind
    if delta:
        log_activity(db, "finance", "update", f"Účet upraven: {account.name}", entity_type="FinanceAccount",
                     entity_id=account.id, delta=delta, user_context=user_context)
    return account


def archive_account(db: Session, account_id: int, user_context: str = "manual") -> FinanceAccount:
    """Archivace místo mazání: transakce účtu zůstávají a počítají se dál."""
    account = _account(db, account_id)
    if account.key == MANUAL_ACCOUNT_KEY:
        raise FinanceError(409, "Vestavěný účet nejde archivovat.")
    if account.archived_at is None:
        account.archived_at = utc_now()
        log_activity(db, "finance", "archive", f"Účet archivován: {account.name}", entity_type="FinanceAccount",
                     entity_id=account.id, delta={"archived_at": {"old": None, "new": account.archived_at.isoformat()}},
                     user_context=user_context)
    return account


# ---------- kategorie ----------

def ensure_builtin_categories(db: Session) -> None:
    for key, *_ in BUILTIN_CATEGORIES:
        builtin_category_id(db.connection(), key)


def category_dict(c: FinanceCategory) -> dict:
    return {"id": c.id, "key": c.key, "name": c.name, "kind": c.kind, "parent_id": c.parent_id,
            "builtin": c.key is not None, "archived": c.archived_at is not None}


def list_categories(db: Session, include_archived: bool = False) -> list[dict]:
    ensure_builtin_categories(db)
    q = db.query(FinanceCategory)
    if not include_archived:
        q = q.filter(FinanceCategory.archived_at.is_(None))
    return [category_dict(c) for c in q.order_by(FinanceCategory.parent_id.isnot(None), FinanceCategory.name)]


def _category(db: Session, category_id: int) -> FinanceCategory:
    category = db.get(FinanceCategory, category_id)
    if category is None:
        raise FinanceError(404, "Kategorie neexistuje.")
    return category


def create_category(db: Session, *, name, kind, parent_id: int | None = None,
                    user_context: str = "manual") -> FinanceCategory:
    if kind not in CATEGORY_KINDS or kind == "system":
        raise FinanceError(422, "Neznámý druh kategorie.")
    if parent_id is not None:
        parent = _category(db, parent_id)
        if parent.parent_id is not None:
            raise FinanceError(422, "Kategorie mají nejvýš dvě úrovně.")
        if parent.kind != kind or parent.archived_at is not None:
            raise FinanceError(422, "Podkategorie musí mít stejný druh jako aktivní nadřazená kategorie.")
    category = FinanceCategory(name=_clean_name(name, NAME_MAX), kind=kind, parent_id=parent_id)
    db.add(category)
    db.flush()
    log_activity(db, "finance", "create", f"Kategorie přidána: {category.name}", entity_type="FinanceCategory",
                 entity_id=category.id, delta={"name": {"old": None, "new": category.name}}, user_context=user_context)
    return category


def rename_category(db: Session, category_id: int, name, user_context: str = "manual") -> FinanceCategory:
    category = _category(db, category_id)
    new = _clean_name(name, NAME_MAX)
    if new != category.name:
        log_activity(db, "finance", "update", f"Kategorie přejmenována: {new}", entity_type="FinanceCategory",
                     entity_id=category.id, delta={"name": {"old": category.name, "new": new}},
                     user_context=user_context)
        category.name = new
    return category


def archive_category(db: Session, category_id: int, user_context: str = "manual") -> FinanceCategory:
    """Archivovaná kategorie se nenabízí pro nové přiřazení; existující transakce ji drží dál."""
    category = _category(db, category_id)
    if category.key is not None:
        raise FinanceError(409, "Vestavěnou kategorii nejde archivovat.")
    if db.query(FinanceCategory.id).filter(FinanceCategory.parent_id == category.id,
                                           FinanceCategory.archived_at.is_(None)).first():
        raise FinanceError(409, "Nejdřív archivuj podkategorie.")
    if category.archived_at is None:
        category.archived_at = utc_now()
        log_activity(db, "finance", "archive", f"Kategorie archivována: {category.name}",
                     entity_type="FinanceCategory", entity_id=category.id,
                     delta={"archived_at": {"old": None, "new": category.archived_at.isoformat()}},
                     user_context=user_context)
    return category


# ---------- transakce ----------

def active_transactions(db: Session):
    """Jediný vstup pro čtení součtů, seznamů a hledání: bez zrušených řádků."""
    return db.query(FinanceTransaction).filter(FinanceTransaction.voided_at.is_(None))


def totals_minor(db: Session, *, start: date | None = None, end: date | None = None,
                 currency: str = "CZK") -> dict[str, int]:
    """Součty v haléřích za [start, end) podle pražského dne zaúčtování; příjmy kladně, výdaje jako kladné číslo."""
    q = db.query(
        func.coalesce(func.sum(case((FinanceTransaction.direction == "in", FinanceTransaction.amount_minor), else_=0)), 0),
        func.coalesce(func.sum(case((FinanceTransaction.direction == "out", -FinanceTransaction.amount_minor), else_=0)), 0),
        func.count(FinanceTransaction.id),
    ).filter(FinanceTransaction.voided_at.is_(None), FinanceTransaction.currency == currency)
    if start is not None:
        q = q.filter(FinanceTransaction.booked_on >= start)
    if end is not None:
        q = q.filter(FinanceTransaction.booked_on < end)
    income, expenses, count = q.one()
    return {"income_minor": int(income), "expenses_minor": int(expenses), "count": int(count)}


def summary_text(tx: FinanceTransaction) -> str:
    """„Výdaj 189,90 Kč · Jídlo (oběd)" pro Aktivitu – stejný tvar jako dřív (text_utils.finance_summary_cz)."""
    kind = "Příjem" if tx.direction == "in" else "Výdaj"
    text = f"{kind} {format_czk_cz(minor_to_decimal(abs(tx.amount_minor)))}"
    if tx.category:
        text += f" · {'Práce' if tx.category.lower() == 'work' else tx.category}"
    if tx.description:
        text += f" ({clip(tx.description, 60)})"
    return text


def create_manual_transaction(db: Session, *, amount_minor: int, direction: str, category: str,
                              description: str = "", user_context: str = "manual") -> FinanceTransaction:
    """Ruční transakce na vestavěném účtu. `amount_minor` je kladná částka v haléřích, směr in/out.
    Kategorie zatím jako text (legacy formulář a Rychlé přidání); mapuje se na vestavěnou kategorii jako ruční volba."""
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
        raise FinanceError(422, "Částka musí být kladná.")
    try:
        signed = signed_minor(amount_minor, direction)
    except MoneyError:
        raise FinanceError(422, "Neplatný směr transakce.") from None
    category_text = clip(" ".join(str(category or "").split()), 100) or "Ostatní"
    connection = db.connection()
    override = builtin_category_id(connection, legacy_category_key(category_text, direction))
    tx = FinanceTransaction(
        account_id=manual_account_id(connection), source="manual", currency="CZK", direction=direction,
        amount_minor=signed, amount=minor_to_legacy(signed), category=category_text,
        description=clip(description or "", DESCRIPTION_MAX), transaction_type="income" if direction == "in" else "expense",
        override_category_id=override, effective_category_id=override, category_source="manual",
    )
    db.add(tx)
    db.flush()
    log_activity(db, "finance", "create", summary_text(tx), entity_type="FinanceTransaction", entity_id=tx.id,
                 delta={"amount_minor": {"old": None, "new": tx.amount_minor},
                        "category": {"old": None, "new": tx.category},
                        "description": {"old": None, "new": tx.description},
                        "direction": {"old": None, "new": tx.direction}},
                 user_context=user_context)
    return tx


def refresh_finance_goals(db: Session, user_context: str = "manual") -> None:
    """Po změně Finance: snímek automatických cílů bilance (dřív kopie v main.py i tools.py). Commituje sám,
    protože běží až po uložení transakce – selhání snímku nesmí vrátit zápis."""
    from goal_history_service import compute_goal_progress_and_value, ensure_goal_progress_snapshot
    from models import Goal

    goals = (db.query(Goal).filter(func.lower(Goal.tracking_type) == "automatic")
             .filter(Goal.source == "finance_balance").all())
    changed = 0
    for g in goals:
        before_pct, _ = compute_goal_progress_and_value(db, g)
        if ensure_goal_progress_snapshot(db, g):
            after_pct, _ = compute_goal_progress_and_value(db, g)
            if before_pct != after_pct:
                log_activity(db, "goals", "snapshot", f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                             entity_type="Goal", entity_id=g.id, user_context=user_context)
            changed += 1
    if changed:
        db.commit()


def void_transaction(db: Session, tx_id: int, *, reason: str = "", user_context: str = "manual") -> FinanceTransaction:
    """MRK-61: místo DELETE. Řádek zůstává (i vazba z práce), jen se přestane počítat, hledat a nabízet.
    Importované řádky nejdou zrušit – patří k výpisu; označí se ke kontrole (review_flag)."""
    tx = db.get(FinanceTransaction, tx_id)
    if tx is None or tx.voided_at is not None:
        raise FinanceError(404, "Transakce neexistuje.")
    if tx.source == "import":
        raise FinanceError(409, "Importovanou transakci nejde smazat; můžeš ji označit ke kontrole.")
    tx.voided_at = utc_now()
    tx.void_reason = clip(" ".join(str(reason or "").split()), VOID_REASON_MAX) or None
    db.flush()
    log_activity(db, "finance", "delete", f"Smazáno: {summary_text(tx)}", entity_type="FinanceTransaction",
                 entity_id=tx.id, delta={"voided_at": {"old": None, "new": tx.voided_at.isoformat()},
                                         "void_reason": {"old": None, "new": tx.void_reason}},
                 user_context=user_context)
    return tx


def transaction_dict(tx: FinanceTransaction) -> dict:
    """Tvar pro REST: nová pole + legacy `amount`/`category`/`transaction_type` (frontend je čte do MRK-65)."""
    return {
        "id": tx.id,
        "amount": minor_to_legacy(tx.amount_minor),
        "amount_minor": tx.amount_minor,
        "currency": tx.currency,
        "direction": tx.direction,
        "category": tx.category,
        "category_id": tx.effective_category_id,
        "description": tx.description,
        "transaction_type": tx.transaction_type,
        "booked_on": tx.booked_on.isoformat() if tx.booked_on else None,
        "account_id": tx.account_id,
        "source": tx.source,
        "created_at": tx.created_at,
    }


def list_transactions(db: Session, limit: int | None = None) -> list[dict]:
    q = active_transactions(db).order_by(FinanceTransaction.booked_on.desc(), FinanceTransaction.created_at.desc(),
                                         FinanceTransaction.id.desc())
    if limit:
        q = q.limit(limit)
    return [transaction_dict(t) for t in q.all()]


def month_totals_minor(db: Session, today: date) -> dict[str, int]:
    start = today.replace(day=1)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    return totals_minor(db, start=start, end=end)
