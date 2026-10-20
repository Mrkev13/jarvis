"""Synthetic statement format for Finance import-core tests (MRK-62). NOT a real bank format and never registered in
production. Line 1 is the signature; then `;`-separated rows:

    booked_on;amount;currency;bank_id;counterparty;counterparty_account;vs;description;status

amount: signed decimal with a dot ("-123.45"); status: booked / pending; empty field = missing value.
"""
from __future__ import annotations

from datetime import date

from modules.finance.importing.rows import NormalizedRow, RowError
from modules.finance.money import MoneyError, parse_minor
from modules.finance.service import account_identifier

SIGNATURE = b"#standa-synthetic-statement v1"


class SyntheticAdapter:
    id = "synthetic_v1"
    family = "synthetic"
    version = "1"
    extra_allowlist = frozenset({"channel"})

    def detect(self, head: bytes) -> bool:
        return head.startswith(SIGNATURE)

    def parse(self, stream):
        for row_no, raw in enumerate(stream.read().decode("utf-8").splitlines()[1:], start=2):
            if not raw.strip():
                continue
            cols = raw.split(";")
            if len(cols) != 9:
                yield RowError(row_no, "column_count", None)
                continue
            booked, amount, currency, bank_id, party, party_account, vs, description, status = cols
            try:
                booked_on = date.fromisoformat(booked)
            except ValueError:
                yield RowError(row_no, "date_invalid", "booked_on")
                continue
            try:
                minor = parse_minor(amount.lstrip("-"))
            except MoneyError:
                yield RowError(row_no, "amount_invalid", "amount")
                continue
            masked, digest = account_identifier(party_account or None)
            yield NormalizedRow(
                row_no=row_no, booked_on=booked_on, amount_minor=-minor if amount.startswith("-") else minor,
                currency=currency, status=status or "booked", bank_txn_id=bank_id or None,
                counterparty_name=party or None, counterparty_account_masked=masked,
                counterparty_account_hash=digest, vs=vs or None, description=description,
                extra=(("channel", "test"),))


def statement(*rows: str) -> bytes:
    return b"\n".join([SIGNATURE, *(r.encode("utf-8") for r in rows)]) + b"\n"


def row(booked_on="2026-10-01", amount="-100.00", bank_id="", party="Obchod", party_account="", vs="",
        description="nákup", status="booked", currency="CZK") -> str:
    return ";".join([booked_on, amount, currency, bank_id, party, party_account, vs, description, status])
