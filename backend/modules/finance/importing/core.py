"""Import core (MRK-62): validate → deterministic dedupe plan → preview (dry run) → atomic commit.

Dedupe, in file order:
- bank ID → `txn_key = bank:<family>:<id>`; same key + same imported fields = duplicate, different fields =
  correction (update + revision; a manual/legacy category is never touched);
- otherwise a fingerprint (account, day, amount, currency, counterparty account hash, VS/KS/SS, normalized text) with
  the multiset rule: k equal rows in the file vs m in the DB → insert k−m as ordinals m+1…k; never delete when k < m;
- a new row without bank ID that resembles an existing row (same account and amount, ±3 days, different text) is
  inserted with `review_flag` (possible duplicate) – never merged;
- pending/holds are skipped and counted.
The preview never writes ledger rows. Commit writes everything in one DB transaction; a failure rolls it back and marks
the import `failed` in a separate transaction. The raw file is deleted after commit, failure, cancel or TTL.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from domain_events import ActivityProjection, append_domain_event
from models import FinanceTransaction
from modules.finance.importing import storage
from modules.finance.importing.rows import (
    BANK_ID_MAX, COUNTERPARTY_MAX, HEAD_BYTES, REGISTRY, ROW_STATUSES, SYMBOL_RE, ImportAdapter, ImportFailure,
    NormalizedRow, RowError, bank_txn_key, fingerprint, fingerprint_txn_key, sanitize_description,
)
from modules.finance.legacy_compat import builtin_category_id, category_name, minor_to_legacy, search_text_of
from modules.finance.models import FinanceAccount, FinanceImport, FinanceImportIssue, FinanceTransactionRevision
from modules.finance.money import CURRENCIES, MAX_ABS_MINOR
from time_utils import utc_now

log = logging.getLogger(__name__)

NEAR_DUPLICATE_DAYS = 3
MAX_ISSUES_RETURNED = 200
COUNT_KEYS = ("new", "duplicate", "changed", "pending_skipped", "invalid", "possible_duplicate")
# Pole, která import vlastní; oprava se stejným bankovním ID je přepíše (staré hodnoty → revize).
IMPORTED_FIELDS = ("booked_on", "value_on", "amount_minor", "currency", "counterparty_name",
                   "counterparty_account_masked", "counterparty_account_hash", "vs", "ks", "ss", "description")
_KEEP_CATEGORY_SOURCES = frozenset({"manual", "legacy"})

# Kategorizace při importu: (db, řádek, id účtu) → id kategorie nebo None (= Nezařazeno). Pravidla dodá MRK-65.
Categorizer = Callable[[Session, NormalizedRow, int], "int | None"]


def _no_category(db: Session, row: NormalizedRow, account_id: int) -> int | None:
    return None


@dataclass
class Plan:
    adapter: ImportAdapter
    inserts: list[tuple[NormalizedRow, str, str, bool]] = field(default_factory=list)  # row, txn_key, fp, review
    updates: list[tuple[int, NormalizedRow, str]] = field(default_factory=list)  # tx id, row, fingerprint
    issues: list[RowError] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {k: 0 for k in COUNT_KEYS})
    date_from: date | None = None
    date_to: date | None = None


# ---------- validace ----------

def _validate(row, account: FinanceAccount) -> RowError | None:
    """Kontrola výstupu adaptéru (adaptér je kód třetí strany vůči jádru – nevěří se mu)."""
    n = getattr(row, "row_no", 0)
    if not isinstance(row.booked_on, date) or isinstance(row.booked_on, datetime):
        return RowError(n, "date_invalid", "booked_on")
    if row.value_on is not None and (not isinstance(row.value_on, date) or isinstance(row.value_on, datetime)):
        return RowError(n, "date_invalid", "value_on")
    if not isinstance(row.amount_minor, int) or isinstance(row.amount_minor, bool) or row.amount_minor == 0 \
            or abs(row.amount_minor) > MAX_ABS_MINOR:
        return RowError(n, "amount_invalid", "amount")
    if row.currency not in CURRENCIES:
        return RowError(n, "currency_unsupported", "currency")
    if row.currency != account.currency:
        return RowError(n, "currency_mismatch", "currency")
    if row.status not in ROW_STATUSES:
        return RowError(n, "status_invalid", "status")
    if row.bank_txn_id is not None and not (0 < len(str(row.bank_txn_id)) <= BANK_ID_MAX):
        return RowError(n, "bank_id_invalid", "bank_txn_id")
    if row.counterparty_name is not None and len(row.counterparty_name) > COUNTERPARTY_MAX:
        return RowError(n, "text_too_long", "counterparty_name")
    for name in ("vs", "ks", "ss"):
        value = getattr(row, name)
        if value is not None and not SYMBOL_RE.match(str(value)):
            return RowError(n, "symbol_invalid", name)
    return None


# ---------- plán (deterministický, jen čte DB) ----------

def _imported_values(row: NormalizedRow) -> dict:
    return {"booked_on": row.booked_on, "value_on": row.value_on, "amount_minor": row.amount_minor,
            "currency": row.currency, "counterparty_name": row.counterparty_name,
            "counterparty_account_masked": row.counterparty_account_masked,
            "counterparty_account_hash": row.counterparty_account_hash, "vs": row.vs, "ks": row.ks, "ss": row.ss,
            "description": sanitize_description(row.description)}


def build_plan(db: Session, account: FinanceAccount, adapter: ImportAdapter, path: Path) -> Plan:
    plan = Plan(adapter)
    booked: list[NormalizedRow] = []
    with open(path, "rb") as stream:
        for row in adapter.parse(stream):
            if isinstance(row, RowError):
                plan.issues.append(RowError(int(row.row_no), str(row.code)[:40], (str(row.field)[:40] if row.field else None)))
                continue
            error = _validate(row, account)
            if error is not None:
                plan.issues.append(error)
            elif row.status == "pending":
                plan.counts["pending_skipped"] += 1
            else:
                booked.append(row)
    plan.counts["invalid"] = len(plan.issues)
    if booked:
        plan.date_from, plan.date_to = min(r.booked_on for r in booked), max(r.booked_on for r in booked)

    bank_rows = [r for r in booked if r.bank_txn_id]
    fp_rows = [r for r in booked if not r.bank_txn_id]
    keys = [bank_txn_key(adapter.family, str(r.bank_txn_id)) for r in bank_rows]
    existing = {t.txn_key: t for t in _chunked(db, FinanceTransaction.txn_key, keys, account.id)}
    seen_keys: set[str] = set()
    for row, key in zip(bank_rows, keys):
        fp = fingerprint(account.id, row)
        if key in seen_keys:
            plan.counts["duplicate"] += 1  # stejné bankovní ID dvakrát v jednom souboru
            continue
        seen_keys.add(key)
        current = existing.get(key)
        if current is None:
            plan.inserts.append((row, key, fp, False))
            plan.counts["new"] += 1
        elif all(getattr(current, k) == v for k, v in _imported_values(row).items()):
            plan.counts["duplicate"] += 1
        else:
            plan.updates.append((current.id, row, fp))
            plan.counts["changed"] += 1

    fps = [fingerprint(account.id, r) for r in fp_rows]
    in_db = dict(db.query(FinanceTransaction.fingerprint, func.count(FinanceTransaction.id))
                 .filter(FinanceTransaction.account_id == account.id, FinanceTransaction.fingerprint.in_(set(fps)))
                 .group_by(FinanceTransaction.fingerprint).all()) if fps else {}
    seen: dict[str, int] = {}
    for row, fp in zip(fp_rows, fps):
        seen[fp] = seen.get(fp, 0) + 1
        ordinal = seen[fp]
        if ordinal <= in_db.get(fp, 0):
            plan.counts["duplicate"] += 1  # překryv exportů: k-tá stejná platba už v DB je
            continue
        review = _looks_like_existing(db, account.id, row, fp)
        plan.inserts.append((row, fingerprint_txn_key(fp, ordinal), fp, review))
        plan.counts["possible_duplicate" if review else "new"] += 1
    return plan


def _chunked(db: Session, column, values: list[str], account_id: int, size: int = 500):
    for i in range(0, len(values), size):
        yield from db.query(FinanceTransaction).filter(FinanceTransaction.account_id == account_id,
                                                       column.in_(values[i:i + size])).all()


def _looks_like_existing(db: Session, account_id: int, row: NormalizedRow, fp: str) -> bool:
    """Možná duplicita: stejný účet a částka ±3 dny, jiný otisk (text), aktivní řádek. Nikdy se neslučuje."""
    window = timedelta(days=NEAR_DUPLICATE_DAYS)
    return db.query(FinanceTransaction.id).filter(
        FinanceTransaction.account_id == account_id, FinanceTransaction.amount_minor == row.amount_minor,
        FinanceTransaction.booked_on >= row.booked_on - window, FinanceTransaction.booked_on <= row.booked_on + window,
        FinanceTransaction.voided_at.is_(None),
        (FinanceTransaction.fingerprint.is_(None)) | (FinanceTransaction.fingerprint != fp),
    ).first() is not None


# ---------- náhled ----------

def _account(db: Session, account_id: int) -> FinanceAccount:
    account = db.get(FinanceAccount, account_id)
    if account is None or account.archived_at is not None:
        raise ImportFailure(404, "account_not_found")
    return account


def preview_token(imp: FinanceImport) -> str:
    """Úchyt náhledu svázaný s id importu a hashem souboru (ověří se při commitu i proti souboru)."""
    return f"{imp.id}-{imp.file_sha256[:16]}"


def _issues_out(issues: list[RowError]) -> list[dict]:
    return [{"row": i.row_no, "code": i.code, "field": i.field} for i in issues[:MAX_ISSUES_RETURNED]]


def _preview_dict(imp: FinanceImport, plan: Plan | None) -> dict:
    return {
        "preview_token": preview_token(imp), "import_id": imp.id, "account_id": imp.account_id,
        "status": imp.status, "already_imported": imp.status == "committed",
        "adapter": imp.adapter, "adapter_version": imp.adapter_version,
        "date_from": imp.date_from.isoformat() if imp.date_from else None,
        "date_to": imp.date_to.isoformat() if imp.date_to else None,
        "counts": plan.counts if plan else _stored_counts(imp),
        "issues": _issues_out(plan.issues) if plan else [],
        "issues_total": len(plan.issues) if plan else imp.count_rejected,
        "expires_at": (imp.created_at + storage.TTL).isoformat() if imp.status == "previewed" else None,
    }


def _stored_counts(imp: FinanceImport) -> dict[str, int]:
    return {"new": imp.count_new, "duplicate": imp.count_duplicate, "changed": imp.count_changed,
            "pending_skipped": imp.count_pending, "invalid": imp.count_rejected,
            "possible_duplicate": imp.count_possible_duplicate}


def _store_counts(imp: FinanceImport, plan: Plan) -> None:
    c = plan.counts
    imp.count_new, imp.count_duplicate, imp.count_changed = c["new"], c["duplicate"], c["changed"]
    imp.count_pending, imp.count_rejected, imp.count_possible_duplicate = (c["pending_skipped"], c["invalid"],
                                                                          c["possible_duplicate"])
    imp.date_from, imp.date_to = plan.date_from, plan.date_to


def preview_import(db: Session, *, account_id: int, upload: Path, now: datetime | None = None) -> dict:
    """Dry run nad nahraným souborem. Commitne jen záznam náhledu (`finance_imports`, status previewed) – žádné
    transakce. Soubor se přesune pod id importu; při chybě nebo již importovaném souboru se smaže."""
    now = now or utc_now()
    try:
        account = _account(db, account_id)
        with open(upload, "rb") as fh:
            head = fh.read(HEAD_BYTES)
        if not head:
            raise ImportFailure(400, "file_empty")
        adapter = REGISTRY.select(head)
        sha, size = storage.sha256_of(upload), upload.stat().st_size
        imp = db.query(FinanceImport).filter_by(account_id=account.id, file_sha256=sha).one_or_none()
        if imp is not None and imp.status == "committed":
            storage.discard(upload)
            return _preview_dict(imp, None)  # „už importováno“ – 0 nových řádků
        plan = build_plan(db, account, adapter, upload)
        if imp is None:
            imp = FinanceImport(account_id=account.id, file_sha256=sha, size_bytes=size, status="previewed",
                                adapter=adapter.id, adapter_version=adapter.version, created_at=now)
            db.add(imp)
        imp.status, imp.adapter, imp.adapter_version, imp.created_at, imp.finished_at = (
            "previewed", adapter.id, adapter.version, now, None)
        _store_counts(imp, plan)
        db.flush()
        storage.stage(upload, imp.id)
        db.commit()
        return _preview_dict(imp, plan)
    except Exception:
        db.rollback()
        storage.discard(upload)
        raise


# ---------- commit ----------

def _load_preview(db: Session, token: str, now: datetime) -> FinanceImport:
    head, _, sha_prefix = str(token or "").partition("-")
    if not head.isdigit():
        raise ImportFailure(404, "preview_not_found")
    imp = db.get(FinanceImport, int(head))
    if imp is None or not imp.file_sha256.startswith(sha_prefix) or len(sha_prefix) != 16:
        raise ImportFailure(404, "preview_not_found")
    if imp.status == "committed":
        raise ImportFailure(409, "already_imported")
    if imp.status != "previewed":
        raise ImportFailure(409, "preview_not_active")
    if now - imp.created_at > storage.TTL or not storage.staged_path(imp.id).is_file():
        _close(db, imp, "cancelled", now)
        raise ImportFailure(410, "preview_expired")
    return imp


def _close(db: Session, imp: FinanceImport, status: str, now: datetime) -> None:
    storage.discard_import(imp.id)
    imp.status, imp.finished_at = status, now
    db.commit()


def _new_transaction(db: Session, imp: FinanceImport, row: NormalizedRow, key: str, fp: str, review: bool,
                     category_id: int | None) -> FinanceTransaction:
    connection = db.connection()
    system = category_id or builtin_category_id(connection, "uncategorized")
    values = _imported_values(row)
    tx = FinanceTransaction(
        account_id=imp.account_id, import_id=imp.id, source="import", direction=row.direction,
        transaction_type="income" if row.direction == "in" else "expense", amount=minor_to_legacy(row.amount_minor),
        txn_key=key, fingerprint=fp, review_flag=review, extra=json.dumps(dict(row.extra)) if row.extra else None,
        system_category_id=system, effective_category_id=system, category_source="rule" if category_id else "none",
        category=category_name(connection, system) or "Nezařazeno", **values)
    tx.search_text = search_text_of(values["description"], row.counterparty_name, tx.category)
    db.add(tx)
    return tx


def _apply_correction(db: Session, imp: FinanceImport, tx_id: int, row: NormalizedRow, fp: str,
                      categorize: Categorizer) -> None:
    tx = db.get(FinanceTransaction, tx_id)
    new = _imported_values(row)
    old = {k: getattr(tx, k) for k in IMPORTED_FIELDS if getattr(tx, k) != new[k]}
    db.add(FinanceTransactionRevision(transaction_id=tx.id, import_id=imp.id,
                                      changed=json.dumps(old, default=str, ensure_ascii=False)))
    for k, v in new.items():
        setattr(tx, k, v)
    tx.direction, tx.fingerprint, tx.import_id = row.direction, fp, imp.id
    tx.transaction_type = "income" if row.direction == "in" else "expense"
    if tx.category_source not in _KEEP_CATEGORY_SOURCES:  # ruční volba uživatele se nikdy nepřepíše
        system = categorize(db, row, imp.account_id) or builtin_category_id(db.connection(), "uncategorized")
        tx.system_category_id = tx.effective_category_id = system
        tx.category = category_name(db.connection(), system) or tx.category


def commit_import(db: Session, token: str, *, skip_invalid: bool = False, categorize: Categorizer | None = None,
                  now: datetime | None = None) -> dict:
    """Zapíše náhled atomicky. Neplatné řádky bez `skip_invalid` = nic se nezapíše (soubor zůstane do TTL)."""
    now = now or utc_now()
    categorize = categorize or _no_category
    imp = _load_preview(db, token, now)
    path = storage.staged_path(imp.id)
    adapter = REGISTRY.get(imp.adapter)
    if adapter is None or adapter.version != imp.adapter_version:
        _close(db, imp, "cancelled", now)
        raise ImportFailure(409, "adapter_changed")
    if storage.sha256_of(path) != imp.file_sha256:
        _close(db, imp, "cancelled", now)
        raise ImportFailure(409, "file_changed")
    account = _account(db, imp.account_id)
    plan = build_plan(db, account, adapter, path)  # přepočet proti aktuální DB (mezitím mohl proběhnout jiný import)
    if plan.counts["invalid"] and not skip_invalid:
        raise ImportFailure(409, "invalid_rows_need_consent")
    import_id = imp.id
    try:
        for row, key, fp, review in plan.inserts:
            _new_transaction(db, imp, row, key, fp, review, categorize(db, row, account.id))
        for tx_id, row, fp in plan.updates:
            _apply_correction(db, imp, tx_id, row, fp, categorize)
        db.query(FinanceImportIssue).filter_by(import_id=imp.id).delete()
        db.add_all(FinanceImportIssue(import_id=imp.id, row_no=i.row_no, code=i.code, field=i.field)
                   for i in plan.issues)
        _store_counts(imp, plan)
        imp.status, imp.finished_at = "committed", now
        counts = dict(plan.counts)
        append_domain_event(
            db, event_type="finance.import.completed", aggregate_type="import", aggregate_id=imp.id,
            payload={"import_id": imp.id, "account_id": imp.account_id, "counts": counts,
                     "date_from": plan.date_from.isoformat() if plan.date_from else None,
                     "date_to": plan.date_to.isoformat() if plan.date_to else None},
            activity=ActivityProjection(
                "finance", "create",
                f"Import výpisu: {counts['new']} nových, {counts['changed']} opravených, "
                f"{counts['duplicate']} už zapsaných, {counts['possible_duplicate']} ke kontrole",
                "FinanceImport", imp.id, {"status": {"old": "previewed", "new": "committed"}}, "manual"))
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("finance import %s failed (%s)", import_id, type(exc).__name__)  # bez hodnot z výpisu
        _mark_failed(db, import_id, now)
        raise ImportFailure(500, "commit_failed") from None
    finally:
        storage.discard_import(import_id)
    return _preview_dict(imp, plan)


def _mark_failed(db: Session, import_id: int, now: datetime) -> None:
    try:
        imp = db.get(FinanceImport, import_id)
        if imp is not None and imp.status != "committed":
            imp.status, imp.finished_at = "failed", now
            db.commit()
    except Exception:  # noqa: BLE001 – stav „failed“ je jen informace; ledger je už vrácený
        db.rollback()


def cancel_import(db: Session, token: str, now: datetime | None = None) -> dict:
    now = now or utc_now()
    imp = _load_preview(db, token, now)
    _close(db, imp, "cancelled", now)
    return {"import_id": imp.id, "status": imp.status}


def cleanup_expired(db: Session, now: datetime | None = None) -> str:
    """Hodinový krok: propadlé náhledy → cancelled + smazaný soubor; osiřelé soubory po pádech requestů pryč."""
    now = now or utc_now()
    expired = (db.query(FinanceImport).filter(FinanceImport.status == "previewed",
                                              FinanceImport.created_at < now - storage.TTL).all())
    for imp in expired:
        storage.discard_import(imp.id)
        imp.status, imp.finished_at = "cancelled", now
    db.commit()
    return f"expired={len(expired)} files={storage.remove_stale_files()}"


def import_dict(imp: FinanceImport) -> dict:
    return {"import_id": imp.id, "account_id": imp.account_id, "status": imp.status, "adapter": imp.adapter,
            "counts": _stored_counts(imp), "created_at": imp.created_at.isoformat(),
            "finished_at": imp.finished_at.isoformat() if imp.finished_at else None,
            "date_from": imp.date_from.isoformat() if imp.date_from else None,
            "date_to": imp.date_to.isoformat() if imp.date_to else None}


def list_imports(db: Session, limit: int = 50) -> list[dict]:
    return [import_dict(i) for i in db.query(FinanceImport).order_by(FinanceImport.id.desc()).limit(limit)]
