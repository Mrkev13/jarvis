"""Sdílené jádro Rychlého přidání (MRK-20) – normalizace, obecné vzory (čísla, peníze, hodiny, datum, čas),
koncept a texty. Žádná znalost modulů: klíčová slova a rozbor jednotlivých druhů dodávají moduly
(`*_integrations.py`, smlouva `module_contracts.QuickAddKind`), pořadí a gating drží quick_add_service.

List grafu importů – nesmí importovat registr modulů ani agregátory.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from text_utils import format_date_cz

MAX_TEXT = 300

WEEKDAYS_CZ = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
_WD_SHORT = ("po", "út", "st", "čt", "pá", "so", "ne")

# ---------- normalizace ----------


def fold(text: str) -> str:
    """Malá písmena bez diakritiky, STEJNÁ délka jako vstup (indexy sedí na originál)."""
    out = []
    for ch in str(text):
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower() if len(base) == 1 else ch.lower())
    return "".join(out)


def num(raw: str) -> float:
    """„1 250,75" / „1.250" / „6,5" → float (desetinná čárka i tečka, mezery jako oddělovač tisíců)."""
    s = raw.replace(" ", " ").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):  # 1.250 = tisíce
        s = s.replace(".", "")
    return float(s.replace(",", "."))


# ---------- vzory (na fold textu) ----------

_NUM = r"-?\d+(?:[  ]\d{3})*(?:[.,]\d{1,2})?"
RE_RATE = re.compile(rf"(?:\bza\s+)?({_NUM})\s*(?:kc|czk)?\s*/\s*(?:h|hod|hodinu)\b")
RE_MONEY = re.compile(rf"(?<![\w/])({_NUM})\s*(?:kc|czk|korun\w*|,-)(?![\w/])")
RE_HOURS = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(?:h|hod|hodin|hodiny|hodinu|hodina)\b(?!\s*/)")
RE_RELATIVE = re.compile(r"\bza\s+(\d+(?:[.,]\d+)?|pul|hodinu|minutu)\s*(minut\w*|min|hodin\w*|hodinu|h)?\b")
# Čas hodin (MRK-11). Předložka + hodina [+ :minuty] [+ „hodin/h"] = ČAS ZAČÁTKU, ne délka:
# „od 14 hodin", „ve 14", „v 10:30", „přednáška od 9", „doktor ve 13:15". Jen u od/v/ve/o/kolem smí za číslem
# stát „hodin/hod/h" (při „na" zůstává „na 4 hodiny" délkou); „o 2 hodiny" / „v 5 hodinách" čas nejsou.
# Délka práce zůstává bez předložky: „4 h", „práce 4 hodiny", „Servind 6h", „14 hodin práce".
RE_TIME = re.compile(
    r"(?:\b(?P<prep>od|v|ve|o|kolem)\s+(?P<h1>\d{1,2})(?:[:.](?P<m1>\d{2}))?(?:\s*(?:hodin|hod|h)\b)?(?!\s*(?:h\b|hod|kc|czk|/|\.)))"
    r"|(?:\bna\s+(?P<h2>\d{1,2})(?:[:.](?P<m2>\d{2}))?\b(?!\s*(?:h\b|hod|kc|czk|/|\.)))"
    r"|(?:\b(?P<h3>\d{1,2}):(?P<m3>\d{2})\b)"
)
RE_DATE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{4}))?")
RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RE_BARE_NUM = re.compile(rf"(?<![\w.,:/-])({_NUM})(?![\w.,:/])")

_WEEKDAY_FORMS = {
    0: ("pondeli",), 1: ("utery",), 2: ("streda", "stredu", "stredy"), 3: ("ctvrtek", "ctvrtka"),
    4: ("patek", "patku"), 5: ("sobota", "sobotu", "soboty"), 6: ("nedele", "nedeli"),
}
RE_WEEKDAY = re.compile(
    r"\b(?:(v|ve|do|na|pristi|tento|tuto|tuhle)\s+)?(?:(pristi)\s+)?("
    + "|".join(f for forms in _WEEKDAY_FORMS.values() for f in forms) + r")\b"
)
RE_DAYWORD = re.compile(r"\b(dnes|dneska|zitra|pozitri|vcera)\b")

FILLER = re.compile(r"\b(mi|me|si|ze|abych|at|prosim|v|ve|do|za|na|o|z|ze|na)\b")

@dataclass
class Draft:
    kind: str = "unknown"
    confidence: str = "high"
    fields: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    needs_input: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def need(self, fld: str, question: str):
        self.needs_input.append({"field": fld, "question": question})

    def error(self, fld: str, message: str):
        self.errors.append({"field": fld, "message": message})


class Text:
    """Originál + fold se stejnými indexy; postupně „spotřebované" úseky se z titulku vynechají."""

    def __init__(self, raw: str):
        self.raw = " ".join(str(raw or "").split())[:MAX_TEXT]
        self.f = fold(self.raw)
        self.used: list[tuple[int, int]] = []

    def take(self, m: re.Match, group: int = 0):
        self.used.append(m.span(group))

    def rest(self, drop: re.Pattern | None = None) -> str:
        chars = list(self.raw)
        for a, b in self.used:
            for i in range(a, b):
                chars[i] = " "
        text = "".join(chars)
        if drop is not None:
            ftext = fold(text)
            for m in drop.finditer(ftext):
                text = text[: m.start()] + " " * (m.end() - m.start()) + text[m.end():]
                ftext = fold(text)
        words = [w for w in text.replace(",", " ").split() if w not in {"-", "·", ":"}]
        # vatová slova na krajích (z, do, v…) pryč, uvnitř zůstávají („test z práva")
        while words and FILLER.fullmatch(fold(words[0])):
            words.pop(0)
        while words and FILLER.fullmatch(fold(words[-1])):
            words.pop()
        out = " ".join(words).strip(" .,;:-")
        return out[:1].upper() + out[1:] if out else ""


# ---------- datum a čas (Praha) ----------


def _weekday_date(today: date, wd: int, prefix: str | None, pristi: bool) -> date:
    if pristi or prefix == "pristi":
        monday_next = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return monday_next + timedelta(days=wd)
    return today + timedelta(days=(wd - today.weekday()) % 7)


def find_date(t: Text, today: date, d: Draft, *, allow_past: bool = False) -> date | None:
    m = RE_ISO.search(t.f)
    if m:
        t.take(m)
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            d.error("date", f"Datum {m.group(0)} neexistuje.")
            return None
    m = RE_DATE.search(t.f)
    if m:
        t.take(m)
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            found = date(year, month, day)
        except ValueError:
            d.error("date", f"Datum {day}. {month}. neexistuje.")
            return None
        if not m.group(3) and found < today and not allow_past:
            found = found.replace(year=year + 1)  # „18. 10." v listopadu = příští rok
        return found
    m = RE_DAYWORD.search(t.f)
    if m:
        t.take(m)
        return today + timedelta(days={"dnes": 0, "dneska": 0, "zitra": 1, "pozitri": 2, "vcera": -1}[m.group(1)])
    m = RE_WEEKDAY.search(t.f)
    if m:
        t.take(m)
        wd = next(i for i, forms in _WEEKDAY_FORMS.items() if m.group(3) in forms)
        return _weekday_date(today, wd, m.group(1), bool(m.group(2)))
    return None


def _clock_spans(f: str) -> list[tuple[int, int]]:
    return [m.span() for m in RE_TIME.finditer(f)]


def duration_matches(f: str) -> list[re.Match]:
    """„4 h", „3 hodiny" – ale ne „14 hodin" uvnitř času („od 14 hodin") ani v relativním čase („za 2 hodiny")."""
    blocked = _clock_spans(f)
    rel = RE_RELATIVE.search(f)
    if rel:
        blocked.append(rel.span())
    return [m for m in RE_HOURS.finditer(f) if not any(a <= m.start() < b for a, b in blocked)]


def find_time(t: Text, d: Draft) -> str | None:
    m = RE_TIME.search(t.f)
    if not m:
        return None
    t.take(m)
    h = int(m.group("h1") or m.group("h2") or m.group("h3"))
    mi = int(m.group("m1") or m.group("m2") or m.group("m3") or 0)
    if h > 23 or mi > 59:
        d.error("time", f"Čas {h}:{mi:02d} neexistuje.")
        return None
    return f"{h:02d}:{mi:02d}"


def when_label(local_dt: datetime, today: date) -> str:
    day = local_dt.date()
    rel = {0: "dnes", 1: "zítra", 2: "pozítří"}.get((day - today).days)
    head = rel or f"{_WD_SHORT[day.weekday()]} {format_date_cz(day)}"
    return f"{head} v {local_dt:%H:%M}"


def float_field(v, fld: str, d: Draft):
    """Číslo z formuláře („6,5" i 6.5); nesmysl = chyba pole, prázdné = None."""
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except (TypeError, ValueError):
        d.error(fld, "Musí to být číslo.")
        return None


def required(f: dict, d: Draft, key: str, message: str):
    """Neprázdná hodnota pole, jinak chyba pole (vrací None)."""
    return str(f.get(key) or "").strip() or d.error(key, message)
