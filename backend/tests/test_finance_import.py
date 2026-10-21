"""MRK-62 import core with the synthetic adapter (tests/finance_fakes.py) – no real bank format or data, no network,
no LLM. Covers the dedupe matrix, atomic commit, file cleanup, upload limits and canary leak checks."""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from models import ActivityLog, DomainEvent, FinanceTransaction
from modules.finance import service as fs
from modules.finance.importing import core, storage
from modules.finance.importing.rows import (
    REGISTRY, ImportFailure, NormalizedRow, fingerprint, normalize_description, sanitize_description,
)
from modules.finance.models import FinanceCategory, FinanceImport, FinanceImportIssue, FinanceTransactionRevision
from tests.finance_fakes import SyntheticAdapter, row, statement

NOW = datetime(2026, 10, 20, 12, 0)
CANARY = "CANARY7Q"  # unikátní řetězec v datech řádků – nesmí uniknout do odpovědí, auditu, událostí ani logu


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base

    monkeypatch.setenv("FINANCE_IMPORT_TMP_DIR", str(tmp_path / "finance-import"))
    monkeypatch.delenv("FINANCE_IMPORT_MAX_MB", raising=False)
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    REGISTRY.register(SyntheticAdapter())
    yield session
    REGISTRY.unregister(SyntheticAdapter.id)
    session.close()
    engine.dispose()


@pytest.fixture
def account(db):
    acc = fs.create_account(db, name="Testovací účet", kind="current")
    db.commit()
    return acc


def upload(content: bytes) -> Path:
    path = storage.new_upload_path()
    path.write_bytes(content)
    return path


def preview(db, account, content: bytes, now=NOW):
    return core.preview_import(db, account_id=account.id, upload=upload(content), now=now)


def run_import(db, account, content: bytes, now=NOW, **kw):
    p = preview(db, account, content, now)
    return core.commit_import(db, p["preview_token"], now=now, **kw)


def ledger(db):
    return db.query(FinanceTransaction).filter_by(source="import").order_by(FinanceTransaction.id).all()


def staged_files():
    return sorted(p.name for p in storage.upload_dir().iterdir())


# ---------- normalizace a klíče ----------

def test_description_normalization_and_sanitizing():
    assert normalize_description("  Platba  KARTOU 1234567890123456 Albert ") == "platba kartou albert"
    assert sanitize_description("Platba 1234567890123456 x") == "Platba …3456 x"
    base = NormalizedRow(row_no=2, booked_on=date(2026, 10, 1), amount_minor=-100, currency="CZK", description="A b")
    same = NormalizedRow(row_no=9, booked_on=date(2026, 10, 1), amount_minor=-100, currency="CZK", description=" a  B ")
    other_day = NormalizedRow(row_no=2, booked_on=date(2026, 10, 2), amount_minor=-100, currency="CZK", description="a b")
    assert fingerprint(1, base) == fingerprint(1, same) != fingerprint(1, other_day) != fingerprint(2, base)


# ---------- náhled = dry run ----------

def test_preview_writes_no_ledger_rows_and_reports_counts(db, account):
    p = preview(db, account, statement(row("2026-10-01"), row("2026-10-02", amount="250.00", description="vrácení"),
                                       row("2026-10-03", status="pending"), row("bad-date")))
    assert p["counts"] == {"new": 2, "duplicate": 0, "changed": 0, "pending_skipped": 1, "invalid": 1,
                           "possible_duplicate": 0}
    assert (p["date_from"], p["date_to"]) == ("2026-10-01", "2026-10-02")
    assert p["issues"] == [{"row": 5, "code": "date_invalid", "field": "booked_on"}]
    assert p["adapter"] == "synthetic_v1" and p["status"] == "previewed"
    assert db.query(FinanceTransaction).count() == 0
    assert staged_files() == [f"import-{p['import_id']}.bin"], "jen soubor pod id importu, žádný název souboru"


def test_unknown_format_empty_file_and_unknown_account(db, account):
    with pytest.raises(ImportFailure) as exc:
        preview(db, account, b"date;amount\n2026-10-01;5\n")
    assert (exc.value.status, exc.value.code) == (415, "unknown_format")
    with pytest.raises(ImportFailure) as exc:
        preview(db, account, b"")
    assert exc.value.code == "file_empty"
    with pytest.raises(ImportFailure) as exc:
        core.preview_import(db, account_id=999, upload=upload(statement(row())), now=NOW)
    assert exc.value.code == "account_not_found"
    assert staged_files() == [], "odmítnutý soubor se hned smaže"


def test_two_matching_adapters_are_unknown_format_not_a_guess(db, account):
    class Twin(SyntheticAdapter):
        id = "synthetic_twin"
    REGISTRY.register(Twin())
    try:
        with pytest.raises(ImportFailure) as exc:
            preview(db, account, statement(row()))
        assert exc.value.code == "unknown_format"
    finally:
        REGISTRY.unregister("synthetic_twin")


# ---------- dedupe ----------

def test_same_file_twice_is_already_imported(db, account):
    content = statement(row("2026-10-01"), row("2026-10-02", amount="-20.00"))
    first = run_import(db, account, content)
    assert first["counts"]["new"] == 2 and first["status"] == "committed"
    again = preview(db, account, content)
    assert again["already_imported"] is True and again["counts"]["new"] == 2  # uložené počty původního importu
    with pytest.raises(ImportFailure) as exc:
        core.commit_import(db, again["preview_token"], now=NOW)
    assert exc.value.code == "already_imported"
    assert len(ledger(db)) == 2 and staged_files() == []


def test_overlapping_exports_and_identical_payments(db, account):
    coffee = row("2026-10-03", amount="-55.00", party="Kavárna", description="káva")
    first = run_import(db, account, statement(row("2026-10-01"), coffee, coffee, row("2026-10-04", amount="-9.00")))
    assert first["counts"]["new"] == 4, "dvě stejné kávy téhož dne jsou dvě platby"
    # druhý export se překrývá (3.–4. 10.) a 3. 10. má navíc třetí stejnou kávu
    second = run_import(db, account, statement(coffee, coffee, coffee, row("2026-10-04", amount="-9.00"),
                                               row("2026-10-06", amount="-70.00")))
    assert second["counts"] == {"new": 2, "duplicate": 3, "changed": 0, "pending_skipped": 0, "invalid": 0,
                                "possible_duplicate": 0}
    coffees = [t for t in ledger(db) if t.amount_minor == -5500]
    assert len(coffees) == 3
    assert sorted(t.txn_key.rsplit(":", 1)[1] for t in coffees) == ["1", "2", "3"], "pořadí m+1…k"
    # menší export (k < m) nikdy nic nemaže
    third = run_import(db, account, statement(coffee))
    assert third["counts"]["duplicate"] == 1 and len([t for t in ledger(db) if t.amount_minor == -5500]) == 3


def test_bank_id_duplicate_and_correction_keeps_manual_category(db, account):
    run_import(db, account, statement(row("2026-10-01", amount="-100.00", bank_id="B1", description="nájem"),
                                      row("2026-10-02", bank_id="B2")))
    tx = db.query(FinanceTransaction).filter_by(txn_key="bank:synthetic:B1").one()
    assert tx.category_source == "none" and db.get(FinanceCategory, tx.effective_category_id).key == "uncategorized"
    housing = db.query(FinanceCategory).filter_by(key="housing").one()
    tx.override_category_id = tx.effective_category_id = housing.id
    tx.category_source = "manual"
    db.commit()
    result = run_import(db, account, statement(
        row("2026-10-01", amount="-120.00", bank_id="B1", description="nájem opraveno"),
        row("2026-10-02", bank_id="B2"), row("2026-10-02", bank_id="B2")))  # stejné ID 2× v souboru
    assert result["counts"]["changed"] == 1 and result["counts"]["duplicate"] == 2 and result["counts"]["new"] == 0
    db.refresh(tx)
    assert (tx.amount_minor, tx.description, tx.category_source, tx.effective_category_id) == (
        -12000, "nájem opraveno", "manual", housing.id)
    [rev] = db.query(FinanceTransactionRevision).all()
    old = json.loads(rev.changed)
    assert old == {"amount_minor": -10000, "description": "nájem"} and rev.import_id == result["import_id"]
    assert len(ledger(db)) == 2


def test_near_duplicate_is_flagged_never_merged(db, account):
    manual = fs.create_manual_transaction(db, amount_minor=50000, direction="out", category="Zábava",
                                          description="kino hotově")
    manual.account_id = account.id
    manual.booked_on = date(2026, 10, 3)
    db.commit()
    result = run_import(db, account, statement(row("2026-10-04", amount="-500.00", party="Cinema", description="vstupenky"),
                                               row("2026-10-20", amount="-500.00", description="jiná")))
    assert result["counts"]["possible_duplicate"] == 1 and result["counts"]["new"] == 1
    flagged = [t for t in ledger(db) if t.review_flag]
    assert [t.booked_on for t in flagged] == [date(2026, 10, 4)]
    assert db.query(FinanceTransaction).count() == 3, "nic se neslučuje ani nemaže"


# ---------- neplatné řádky a atomicita ----------

def test_invalid_rows_need_consent(db, account):
    content = statement(row("2026-10-01"), row("2026-10-02", amount="abc"), row("2026-10-03", currency="EUR"))
    p = preview(db, account, content)
    with pytest.raises(ImportFailure) as exc:
        core.commit_import(db, p["preview_token"], now=NOW)
    assert exc.value.code == "invalid_rows_need_consent"
    assert db.query(FinanceTransaction).count() == 0 and staged_files(), "soubor zůstává pro nový pokus"
    result = core.commit_import(db, p["preview_token"], skip_invalid=True, now=NOW)
    assert result["counts"]["new"] == 1 and result["counts"]["invalid"] == 2
    issues = [(i.row_no, i.code, i.field) for i in db.query(FinanceImportIssue).order_by(FinanceImportIssue.row_no)]
    assert issues == [(3, "amount_invalid", "amount"), (4, "currency_mismatch", "currency")]


def test_failure_mid_commit_rolls_back_and_retry_is_safe(db, account):
    content = statement(row("2026-10-01"), row("2026-10-02", amount="-2.00"), row("2026-10-03", amount="-3.00"))
    p = preview(db, account, content)
    original, calls = core._new_transaction, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("simulated DB failure")
        return original(*args, **kwargs)

    with patch.object(core, "_new_transaction", flaky), pytest.raises(ImportFailure) as exc:
        core.commit_import(db, p["preview_token"], now=NOW)
    assert exc.value.code == "commit_failed"
    assert db.query(FinanceTransaction).count() == 0 and db.query(DomainEvent).count() == 0
    assert db.get(FinanceImport, p["import_id"]).status == "failed" and staged_files() == []
    retry = run_import(db, account, content)  # znovu nahrát → stejný záznam importu, žádné duplicity
    assert retry["import_id"] == p["import_id"] and retry["counts"]["new"] == 3 and len(ledger(db)) == 3


# ---------- soubor: úklid, TTL, zrušení ----------

def test_raw_file_removed_after_commit_cancel_and_expiry(db, account):
    run_import(db, account, statement(row("2026-10-01")))
    assert staged_files() == []
    p = preview(db, account, statement(row("2026-10-02")))
    core.cancel_import(db, p["preview_token"], now=NOW)
    assert staged_files() == [] and db.get(FinanceImport, p["import_id"]).status == "cancelled"
    p = preview(db, account, statement(row("2026-10-05")))
    with pytest.raises(ImportFailure) as exc:
        core.commit_import(db, p["preview_token"], now=NOW + storage.TTL + timedelta(minutes=1))
    assert exc.value.code == "preview_expired" and staged_files() == []
    p = preview(db, account, statement(row("2026-10-06")))
    assert core.cleanup_expired(db, now=NOW + timedelta(hours=1)).startswith("expired=1")
    assert staged_files() == [] and db.get(FinanceImport, p["import_id"]).status == "cancelled"


def test_stale_orphan_uploads_are_removed(db):
    old, fresh = storage.new_upload_path(), storage.new_upload_path()
    past = time.time() - storage.TTL.total_seconds() - 60
    os.utime(old, (past, past))
    other = storage.upload_dir() / "keep-me.txt"
    other.write_text("not ours")
    assert storage.remove_stale_files() == 1
    assert not old.exists() and fresh.exists() and other.exists()


def test_tampered_or_unknown_tokens(db, account):
    p = preview(db, account, statement(row()))
    for token in ("abc", f"{p['import_id']}-0000000000000000", "999-0000000000000000"):
        with pytest.raises(ImportFailure) as exc:
            core.commit_import(db, token, now=NOW)
        assert exc.value.code == "preview_not_found"
    storage.staged_path(p["import_id"]).write_bytes(statement(row(amount="-1.00")))
    with pytest.raises(ImportFailure) as exc:
        core.commit_import(db, p["preview_token"], now=NOW)
    assert exc.value.code == "file_changed" and db.query(FinanceTransaction).count() == 0


# ---------- audit, událost, soukromí ----------

def test_event_activity_and_no_row_values_anywhere(db, account, caplog):
    caplog.set_level(logging.DEBUG)
    content = statement(row("2026-10-01", party=f"Firma {CANARY}", party_account=f"{CANARY}-123456789/0100",
                            description=f"platba {CANARY} 1234567890123456"),
                        row("2026-10-02", amount=f"-{CANARY}"), row("2026-10-03", status="pending",
                                                                  description=CANARY))
    p = preview(db, account, content)
    result = core.commit_import(db, p["preview_token"], skip_invalid=True, now=NOW)
    [event] = db.query(DomainEvent).all()
    payload = event.payload
    assert event.event_type == "finance.import.completed"
    assert set(payload) == {"import_id", "account_id", "counts", "date_from", "date_to"}
    [activity] = db.query(ActivityLog).filter_by(entity_type="FinanceImport").all()
    assert activity.summary.startswith("Import výpisu: 1 nových")
    texts = [json.dumps(p, ensure_ascii=False), json.dumps(result, ensure_ascii=False), json.dumps(event.payload),
             activity.summary, activity.delta_json or "", caplog.text,
             json.dumps([(i.code, i.field) for i in db.query(FinanceImportIssue)])]
    for text in texts:
        assert CANARY not in text and "123456789" not in text
    [tx] = ledger(db)
    assert tx.counterparty_account_masked == "…0100" and "123456789" not in (tx.description or "")
    assert tx.description == "platba CANARY7Q …3456"  # uložený popis: dlouhé číslo zamaskované


# ---------- REST ----------

@pytest.fixture
def api(db, monkeypatch):
    from fastapi.testclient import TestClient
    import database
    import main
    from module_registry import ModuleAccess

    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    client = TestClient(main.app)
    with patch.object(main, "auth_enabled", return_value=False), \
            patch.object(main, "current_access", return_value=ModuleAccess({})):
        yield client
    client.close()


def test_rest_preview_commit_limits_and_errors(api, account, monkeypatch):
    headers = {"content-type": "text/csv"}
    r = api.post(f"/finance/imports/preview?account_id={account.id}", content=statement(row()), headers=headers)
    assert r.status_code == 200, r.text
    token = r.json()["preview_token"]
    r = api.post(f"/finance/imports/{token}/commit")
    assert r.status_code == 200 and r.json()["counts"]["new"] == 1
    assert [i["status"] for i in api.get("/finance/imports").json()] == ["committed"]
    r = api.post(f"/finance/imports/preview?account_id={account.id}", content=b"\x00\x01",
                 headers={"content-type": "image/png"})
    assert (r.status_code, r.json()["detail"]) == (415, {"category": "unsupported_media_type"})
    r = api.post(f"/finance/imports/preview?account_id={account.id}", content=b"x;y\n", headers=headers)
    assert (r.status_code, r.json()["detail"]) == (415, {"category": "unknown_format"})
    monkeypatch.setenv("FINANCE_IMPORT_MAX_MB", "1")
    big = statement(*[row(description="x" * 200)] * 6000)
    assert len(big) > 1024 * 1024
    r = api.post(f"/finance/imports/preview?account_id={account.id}", content=big, headers=headers)
    assert (r.status_code, r.json()["detail"]) == (413, {"category": "file_too_large"})
    r = api.post("/finance/imports/preview?account_id=999", content=statement(row()), headers=headers)
    assert (r.status_code, r.json()["detail"]) == (404, {"category": "account_not_found"})
    r = api.post("/finance/imports/999-0000000000000000/commit")
    assert r.status_code == 404
    assert staged_files() == []


# ---------- review hardening (adaptér je kód třetí strany vůči jádru) ----------

def test_adapter_codes_and_extra_are_allowlisted(db, account):
    from modules.finance.importing.rows import RowError

    class Leaky(SyntheticAdapter):
        id, family = "synthetic_leaky", "leaky"

        def detect(self, head):
            return head.startswith(b"#leaky")

        def parse(self, stream):
            stream.read()
            yield RowError(2, f"bad value {CANARY}", f"field {CANARY}")  # chybný adaptér vloží hodnotu do kódu
            yield NormalizedRow(row_no=3, booked_on=date(2026, 10, 1), amount_minor=-100, currency="CZK",
                                extra=(("channel", "card"), ("raw_line", CANARY)))
    REGISTRY.register(Leaky())
    try:
        result = run_import(db, account, b"#leaky\nx\n", skip_invalid=True)
    finally:
        REGISTRY.unregister("synthetic_leaky")
    assert CANARY not in json.dumps(result)
    [issue] = db.query(FinanceImportIssue).all()
    assert (issue.code, issue.field) == ("row_invalid", None)
    [tx] = ledger(db)
    assert json.loads(tx.extra) == {"channel": "card"}


def test_non_ascii_digit_token_is_not_found(db, account):
    with pytest.raises(ImportFailure) as exc:
        core.commit_import(db, "²-0000000000000000", now=NOW)
    assert exc.value.code == "preview_not_found"
