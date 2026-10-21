"""Synthetic mBank GPC statements for MRK-63 tests – same record layout as a real mBank export, every value invented
(fake accounts, names, document numbers, amounts, symbols, type codes). Never derived from a real statement."""
from __future__ import annotations

from datetime import date

OWN = "0000001000000001"  # smyšlený účet
HOLDER = "SYNTETICKY KLIENT"


def header(own: str = OWN, marker: str = "mBank", statement_no: int = 1) -> str:
    line = ("074" + own + HOLDER.ljust(20)[:20] + "010126" + "0" * 14 + "+" + "0" * 14 + "+" + "0" * 14 + "+"
            + "0" * 14 + "+" + f"{statement_no:03d}" + "311226" + marker.ljust(14)[:14])
    assert len(line) == 128, len(line)
    return line


def tx(doc: int, amount_minor: int, booked: date, *, code: str | None = None, text: str = "PLATBA KARTOU",
       executed: date | None = None, counter: str = "0" * 16, bank: str = "0000", vs: str = "", ks: str = "",
       ss: str = "", type_code: str = "0101", own: str = OWN) -> str:
    code = code or ("2" if amount_minor > 0 else "1")
    executed = executed or booked
    line = ("075" + own + counter + f"{doc:013d}" + f"{abs(amount_minor):012d}" + code + vs.rjust(10, "0")
            + ("00" + bank + ks.rjust(4, "0")) + ss.rjust(10, "0") + booked.strftime("%d%m%y")
            + text.ljust(20)[:20] + "0" + type_code + executed.strftime("%d%m%y"))
    assert len(line) == 128, len(line)
    return line


def statement(*lines: str, own: str = OWN, encoding: str = "cp1250") -> bytes:
    return ("\n".join([header(own), *lines]) + "\n").encode(encoding)


D1, D2, D3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)

# Základní smyšlený výpis: příjem s VS a účtem protistrany, karta s diakritikou, dvě stejné platby téhož dne,
# poplatek a vrácená (stornovaná) platba.
BASIC = [
    tx(1001, 1500000, D1, text="PRICHOZI PLATBA", counter="0000001234567890", bank="0800", vs="1234", ks="308",
       type_code="0202"),
    tx(1002, -18990, D2, text="PLATBA KARTOU Kavárna", executed=D1),
    tx(1003, -5500, D2, text="PLATBA KARTOU Pekárna"),
    tx(1004, -5500, D2, text="PLATBA KARTOU Pekárna"),
    tx(1005, -2900, D3, text="POPLATEK ZA VEDENI", type_code="0303"),
    tx(1006, 18990, D3, code="4", text="STORNO PLATBY KARTOU"),
]
