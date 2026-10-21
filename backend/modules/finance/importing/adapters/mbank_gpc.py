"""mBank statement in the GPC/ABO fixed-width format (MRK-63) – the primary mBank format of Finance v1.

Layout as exported by mBank (verified structurally on a real export, no values recorded; see docs/finance.md):
- every record is 128 characters, cp1250, one per line;
- `074` = statement header: own account (4–19), holder name (20–39, **never read**), balances/turnovers, statement
  number; mBank writes its bank name into the trailing filler – that marker is part of the signature;
- `075` = transaction: own account (4–19), counterparty account (20–35, zeros = none), bank document number
  (36–48, unique per transaction → native ID), amount in haléře (49–60), posting code (61: 1 debit, 2 credit,
  4 reversed debit, 5 reversed credit), VS (62–71), counterparty bank code + KS (72–81), SS (82–91),
  **booking date** (92–97, DDMMYY), text (98–117, transaction type + up to 20 chars), `0` (118),
  **mBank transaction type code** (119–122 – mBank puts the type here, *not* a currency), transaction date (123–128);
- `076`/`078`/`079` extension records are skipped (not produced by mBank in the verified export).
The file carries no per-row currency → rows are emitted with `currency=None` and the core uses the account currency.
Nothing here logs or returns values; errors are row number + code + field.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import BinaryIO, Iterator

from modules.finance.importing.rows import NormalizedRow, ParsedRow, RowError
from modules.finance.service import account_identifier

RECORD_LENGTH = 128
ENCODING = "cp1250"
BANK_MARKER = "mbank"
_MARKER_SLICE = slice(100, 128)  # výplň za číslem výpisu, kam mBank píše název banky
_SKIPPED_RECORDS = ("076", "078", "079")
_DIRECTION = {"1": -1, "2": 1, "4": 1, "5": -1}  # debet, kredit, storno debetu (vrácení), storno kreditu


def _decode(raw: bytes) -> str | None:
    try:
        return raw.rstrip(b"\r\n").decode(ENCODING)
    except UnicodeDecodeError:
        return None


def _date(value: str) -> date | None:
    if not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%d%m%y").date()
    except ValueError:
        return None


def _symbol(value: str) -> str | None:
    digits = value.strip().lstrip("0")
    return digits or None


def _counterparty_account(account16: str, bank_ks: str) -> str | None:
    """16 číslic (předčíslí 6 + číslo 10) + kód banky z KS pole → „předčíslí-číslo/banka“; nuly = žádný účet."""
    if not account16.isdigit() or not account16.strip("0"):
        return None
    prefix, number = account16[:6].lstrip("0"), account16[6:].lstrip("0")
    bank = bank_ks[2:6].lstrip("0") if bank_ks.isdigit() else ""
    text = f"{prefix}-{number}" if prefix else number
    return f"{text}/{bank_ks[2:6]}" if bank else text


class MbankGpcAdapter:
    id = "mbank_gpc"
    family = "mbank"
    version = "1"
    extra_allowlist = frozenset({"type_code", "executed_on"})

    def detect(self, head: bytes) -> bool:
        """Podpis: první záznam `074` dlouhý 128 znaků s mBank značkou ve výplni (jiné banky/formáty = neshoda)."""
        first = _decode(head.split(b"\n", 1)[0])
        return bool(first) and len(first) == RECORD_LENGTH and first.startswith("074") \
            and first[3:19].isdigit() and BANK_MARKER in first[_MARKER_SLICE].lower()

    def statement_account(self, head: bytes) -> str | None:
        """Vlastní účet z hlavičky 074 („předčíslí-číslo“) – jádro z něj drží jen masku + otisk."""
        first = _decode(head.split(b"\n", 1)[0]) or ""
        account = first[3:19] if first.startswith("074") else ""
        if not account.isdigit() or not account.strip("0"):
            return None
        prefix, number = account[:6].lstrip("0"), account[6:].lstrip("0")
        return f"{prefix}-{number}" if prefix else number

    def parse(self, stream: BinaryIO) -> Iterator[ParsedRow]:
        own_account = None
        for row_no, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            line = _decode(raw)
            if line is None:
                yield RowError(row_no, "encoding_invalid", None)
                continue
            if len(line) > RECORD_LENGTH:
                yield RowError(row_no, "record_length", None)
                continue
            line = line.ljust(RECORD_LENGTH)  # export může ořezat koncové mezery
            kind = line[:3]
            if kind == "074":
                own_account = line[3:19]
                continue
            if kind in _SKIPPED_RECORDS:
                continue
            if kind != "075":
                yield RowError(row_no, "record_unknown", None)
                continue
            yield self._transaction(row_no, line, own_account)

    def _transaction(self, row_no: int, line: str, own_account: str | None) -> ParsedRow:
        if own_account is None or line[3:19] != own_account:
            return RowError(row_no, "account_mismatch", "account")
        doc_id = line[35:48].strip()
        if not doc_id.isdigit() or not doc_id.strip("0"):
            return RowError(row_no, "bank_id_invalid", "bank_txn_id")
        amount = line[48:60]
        sign = _DIRECTION.get(line[60])
        if not amount.isdigit() or int(amount) == 0:
            return RowError(row_no, "amount_invalid", "amount")
        if sign is None:
            return RowError(row_no, "posting_code_invalid", "direction")
        booked_on, executed_on = _date(line[91:97]), _date(line[122:128])
        if booked_on is None:
            return RowError(row_no, "date_invalid", "booked_on")
        if executed_on is None:
            return RowError(row_no, "date_invalid", "executed_on")
        type_code = line[118:122]
        if not type_code.isdigit():
            return RowError(row_no, "type_code_invalid", "type_code")
        masked, digest = account_identifier(_counterparty_account(line[19:35], line[71:81]))
        return NormalizedRow(
            row_no=row_no, booked_on=booked_on, amount_minor=sign * int(amount), currency=None, status="booked",
            bank_txn_id=doc_id.lstrip("0"), counterparty_account_masked=masked, counterparty_account_hash=digest,
            vs=_symbol(line[61:71]), ks=_symbol(line[77:81]), ss=_symbol(line[81:91]),
            description=line[97:117].strip(),
            extra=(("type_code", type_code), ("executed_on", executed_on.isoformat())))
