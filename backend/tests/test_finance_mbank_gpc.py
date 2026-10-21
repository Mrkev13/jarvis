"""MRK-63: mBank GPC adapter + import core. Synthetic statements only (tests/mbank_gpc_fixture.py and the committed
fixtures/finance/mbank-synthetic-statement.gpc, generated from it) – no real statement, no network, no LLM."""
import io
import json
import logging
from datetime import date, datetime
from pathlib import Path

import pytest

from models import DomainEvent, FinanceTransaction
from modules.finance import service as fs
from modules.finance.importing import core, storage
from modules.finance.importing.adapters.mbank_gpc import MbankGpcAdapter
from modules.finance.importing.rows import REGISTRY, ImportFailure, NormalizedRow, RowError
from modules.finance.models import FinanceImport, FinanceImportIssue, FinanceTransactionRevision
from tests.mbank_gpc_fixture import BASIC, D1, D2, D3, statement, tx

FIXTURE = Path(__file__).parent / "fixtures" / "finance" / "mbank-synthetic-statement.gpc"
NOW = datetime(2026, 9, 10, 12, 0)
ADAPTER = MbankGpcAdapter()


def parse(data: bytes):
    return list(ADAPTER.parse(io.BytesIO(data)))


# ---------- adaptér ----------

def test_detects_only_mbank_gpc():
    data = FIXTURE.read_bytes()
    assert ADAPTER.detect(data[:4096])
    assert REGISTRY.select(data[:4096]).id == "mbank_gpc"
    not_mbank = statement(*BASIC).replace(b"mBank", b"OTHER")
    csv_export = "#Klient;\nSYNTETICKY KLIENT;\n\n#Datum zaúčtování transakce;#Datum uskutečnění transakce;\n".encode("cp1250")
    short_header = b"074" + b"1" * 50 + b"mBank\n"
    for data in (not_mbank, csv_export, short_header, b"", b"075" + b"0" * 125):
        assert not ADAPTER.detect(data[:4096])
    with pytest.raises(ImportFailure) as exc:
        REGISTRY.select(csv_export)  # mBank CSV je v1 odložený formát → unknown_format, žádné hádání
    assert exc.value.code == "unknown_format"


def test_committed_fixture_matches_builder_and_is_synthetic():
    rows = parse(FIXTURE.read_bytes())
    assert len(rows) == 7
    assert isinstance(rows[-1], RowError) and (rows[-1].code, rows[-1].field) == ("date_invalid", "booked_on")
    assert FIXTURE.read_bytes().startswith(statement(*BASIC)[:-1])


def test_parses_amounts_signs_dates_symbols_and_text():
    income, card, bakery1, bakery2, fee, reversal = parse(statement(*BASIC))
    assert (income.amount_minor, income.direction, income.booked_on) == (1500000, "in", D1)
    assert (income.vs, income.ks, income.ss) == ("1234", "308", None)
    assert income.counterparty_account_masked == "…7890/0800" and len(income.counterparty_account_hash) == 64
    assert income.bank_txn_id == "1001" and income.status == "booked" and income.currency is None
    assert dict(income.extra) == {"type_code": "0202", "executed_on": "2026-09-01"}
    assert (card.amount_minor, card.booked_on, dict(card.extra)["executed_on"]) == (-18990, D2, "2026-09-01")
    assert card.description == "PLATBA KARTOU Kavárn", "cp1250 diakritika; pole má pevně 20 znaků"
    assert card.counterparty_account_masked is None and card.vs is None
    assert (bakery1.amount_minor, bakery2.amount_minor, bakery1.bank_txn_id, bakery2.bank_txn_id) == (
        -5500, -5500, "1003", "1004")
    assert fee.amount_minor == -2900
    assert (reversal.amount_minor, reversal.direction) == (18990, "in"), "storno debetu = peníze zpět"


def test_storno_credit_is_outgoing():
    [row] = parse(statement(tx(2001, 5000, D1, code="5")))
    assert row.amount_minor == -5000


def test_malformed_records_are_row_errors_without_values():
    good = tx(3001, -100, D1, text="PLATBA KARTOU Tajne")
    cases = [
        (good.replace("075", "099", 1), "record_unknown", None),
        (good + "X", "record_length", None),
        (tx(3002, -100, D1, own="0000009999999999"), "account_mismatch", "account"),
        (tx(0, -100, D1), "bank_id_invalid", "bank_txn_id"),
        (tx(3003, 0, D1, code="1"), "amount_invalid", "amount"),
        (tx(3004, -100, D1, code="9"), "posting_code_invalid", "direction"),
        (good[:91] + "999999" + good[97:], "date_invalid", "booked_on"),
        (good[:122] + "ABCDEF", "date_invalid", "executed_on"),
        (good[:118] + "XXXX" + good[122:], "type_code_invalid", "type_code"),
    ]
    for line, code, field in cases:
        [row] = parse(statement(line))
        assert isinstance(row, RowError) and (row.code, row.field) == (code, field), line[:3]
        assert "Tajne" not in json.dumps(row.__dict__)
    data = statement(good)[:-1] + b"\n075" + b"\x98" * 125 + b"\n"  # 0x98 není v cp1250 definován
    assert [r.code for r in parse(data) if isinstance(r, RowError)] == ["encoding_invalid"]


def test_trimmed_trailing_spaces_and_extension_records():
    line = tx(4001, -100, D1, text="KRATKY")  # konec řádku bez mezer by export mohl ořezat
    data = statement(line, "078" + "volny text".ljust(125))
    rows = parse(data)
    assert len(rows) == 1 and isinstance(rows[0], NormalizedRow)


# ---------- jádro + adaptér ----------

@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base

    monkeypatch.setenv("FINANCE_IMPORT_TMP_DIR", str(tmp_path / "finance-import"))
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def account(db):
    acc = fs.create_account(db, name="mBank běžný", kind="current", institution="mBank")
    db.commit()
    return acc


def run(db, account, data: bytes, **kw):
    upload = storage.new_upload_path()
    upload.write_bytes(data)
    p = core.preview_import(db, account_id=account.id, upload=upload, now=NOW)
    if p["already_imported"]:
        return p
    return core.commit_import(db, p["preview_token"], now=NOW, **kw)


def imported(db):
    return db.query(FinanceTransaction).filter_by(source="import").order_by(FinanceTransaction.id).all()


def test_first_import_same_file_overlap_and_identical_payments(db, account):
    first = run(db, account, FIXTURE.read_bytes(), skip_invalid=True)
    assert first["adapter"] == "mbank_gpc"
    assert first["counts"] == {"new": 6, "duplicate": 0, "changed": 0, "pending_skipped": 0, "invalid": 1,
                               "possible_duplicate": 0}
    rows = imported(db)
    assert len(rows) == 6 and {r.currency for r in rows} == {"CZK"}, "měna účtu"
    assert sorted(r.txn_key for r in rows)[0] == "bank:mbank:1001"
    assert [r.amount_minor for r in rows if r.amount_minor == -5500] == [-5500, -5500], "dvě stejné platby zůstávají"
    assert [(i.row_no, i.code) for i in db.query(FinanceImportIssue)] == [(8, "date_invalid")]
    again = run(db, account, FIXTURE.read_bytes())
    assert again["already_imported"] is True and len(imported(db)) == 6
    # překrývající se další export (jiný soubor): 3 známé řádky + 1 nový
    overlap = run(db, account, statement(BASIC[3], BASIC[4], BASIC[5], tx(1008, -4200, date(2026, 9, 5))))
    assert overlap["counts"]["new"] == 1 and overlap["counts"]["duplicate"] == 3 and len(imported(db)) == 7
    assert list(storage.upload_dir().iterdir()) == [], "surový soubor po commitu neexistuje"


def test_bank_id_correction_keeps_manual_category(db, account):
    run(db, account, statement(*BASIC))
    tx_row = db.query(FinanceTransaction).filter_by(txn_key="bank:mbank:1005").one()
    from modules.finance.models import FinanceCategory
    housing = db.query(FinanceCategory).filter_by(key="housing").one()
    tx_row.override_category_id = tx_row.effective_category_id = housing.id
    tx_row.category_source = "manual"
    db.commit()
    corrected = run(db, account, statement(tx(1005, -3900, D3, text="POPLATEK ZA VEDENI", type_code="0303")))
    assert corrected["counts"]["changed"] == 1
    db.refresh(tx_row)
    assert (tx_row.amount_minor, tx_row.category_source, tx_row.effective_category_id) == (-3900, "manual", housing.id)
    assert json.loads(db.query(FinanceTransactionRevision).one().changed) == {"amount_minor": -2900}


def test_bank_row_resembling_manual_entry_is_flagged_not_merged(db, account):
    manual = fs.create_manual_transaction(db, amount_minor=18990, direction="out", category="Jídlo",
                                          description="kavárna hotově")
    manual.account_id, manual.booked_on = account.id, D1
    db.commit()
    result = run(db, account, statement(*BASIC))
    assert result["counts"]["possible_duplicate"] == 1 and result["counts"]["new"] == 5
    flagged = [r for r in imported(db) if r.review_flag]
    assert [r.txn_key for r in flagged] == ["bank:mbank:1002"]
    assert db.query(FinanceTransaction).count() == 7, "nic se neslučuje"
    # další import téhož banky se k vlastním řádkům nechová jako k možným duplicitám
    later = run(db, account, statement(tx(1009, -18990, D3, text="PLATBA KARTOU Kavárna")))
    assert later["counts"]["possible_duplicate"] == 1, "jen kvůli ručnímu zápisu, ne kvůli importovanému 1002"


def test_other_account_currency_and_privacy(db, account, caplog):
    caplog.set_level(logging.DEBUG)
    eur = fs.create_account(db, name="EUR účet", kind="current", currency="EUR")
    db.commit()
    secret = "KANARKOVA KAVARNA"
    result = run(db, eur, statement(tx(5001, -1000, D1, text=secret[:20]), tx(5002, 2000, D2)))
    assert {r.currency for r in imported(db)} == {"EUR"}
    texts = [json.dumps(result, ensure_ascii=False), caplog.text,
             json.dumps([e.payload for e in db.query(DomainEvent)], ensure_ascii=False)]
    assert all("KANARKOV" not in t for t in texts)
    assert db.query(FinanceImport).one().adapter == "mbank_gpc"


def test_statement_binds_account_and_rejects_other_accounts(db, account):
    """Review MRK-63: formát nemá měnu na řádku → měnu určuje vybraný účet; výpis cizího účtu musí skončit chybou."""
    run(db, account, statement(*BASIC))
    db.refresh(account)
    assert account.masked_identifier == "…0001" and len(account.identifier_hash) == 64
    other_own = "0000009999999999"
    for target, data in ((account, statement(tx(6001, -100, D1, own=other_own), own=other_own)),
                         (fs.create_account(db, name="Jiný", kind="current"), statement(tx(6002, -100, D1)))):
        db.commit()
        with pytest.raises(ImportFailure) as exc:
            run(db, target, data)
        assert exc.value.code == "account_mismatch"
    assert len(imported(db)) == 6 and list(storage.upload_dir().iterdir()) == []


def test_statement_without_own_account_is_refused(db, account):
    zeros = "0" * 16
    with pytest.raises(ImportFailure) as exc:
        run(db, account, statement(tx(7001, -100, D1, own=zeros), own=zeros))
    assert exc.value.code == "statement_account_missing" and imported(db) == []
