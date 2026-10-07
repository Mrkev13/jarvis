"""Rychlé přidání (Roadmap 4E) – deterministický parser krátkých českých vět, bez LLM a bez zápisu.

parse(text) → náhled {kind, confidence, fields, display, warnings, needs_input, errors, ready}
pro čtyři typy: připomínka, finance, práce, škola (zkouška / úkol). Nic se neuhaduje potichu:
chybějící údaj = `needs_input` (otázka), neplatný = `errors`, odhad = `warnings` (viditelně v náhledu).

prepare(db, kind, fields) znovu ověří (upravená) pole a přes ai.prepare_write_action z nich udělá
BĚŽNOU pending akci existujícího WRITE toolu (add_reminder / add_finance_transaction / add_work_session /
add_school_exam / add_school_assignment) se zdrojem „quick_add". Zápis provede až /actions/confirm –
stejná cesta (atomické potvrzení, audit, vypršení) jako u návrhů AI.

Kalendář je pražský (time_utils), nikdy lokální čas serveru.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from models import Subject
from module_registry import ModuleAccess, current_access
from text_utils import format_czk_cz, format_date_cz, format_hours_cz, format_num_cz
from time_utils import local_to_utc, now_local, utc_now

KINDS = ("reminder", "finance", "work", "exam", "assignment")
MAX_TEXT = 300
MAX_AMOUNT = 10_000_000
MAX_HOURS = 24
MAX_RATE = 100_000
DEFAULT_REMINDER_TIME = "09:00"

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


def _num(raw: str) -> float:
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

KW_REMINDER = re.compile(r"\b(pripomen\w*|pripominka|upozorni\w*|reminder|nezapomen\w*)\b")
KW_WORK = re.compile(r"\b(prace|praci|pracoval\w*|makal\w*|smena|smenu)\b")
KW_EXAM = re.compile(r"\b(test|testu|zkouska|zkousku|zkousky|kviz|zapocet|pisemka|pisemku)\b")
KW_ASSIGNMENT = re.compile(r"\b(ukol|ukolu|deadline|assignment|referat|seminarka|seminarku|odevzdat|odevzdani)\b")
KW_INCOME = re.compile(r"\b(prijem|vyplata|vyplatu|dostal\w*|faktura|fakturu)\b")
KW_EXPENSE = re.compile(r"\b(vydaj|zaplatil\w*|koupil\w*|utratil\w*|platba)\b")
KW_PRIORITY_HIGH = re.compile(r"(\b(dulezit\w*|urgent\w*|priorita\s+vysoka)\b|!!)")
FILLER = re.compile(r"\b(mi|me|si|ze|abych|at|prosim|v|ve|do|za|na|o|z|ze|na)\b")

# Kategorie výdajů jen podle výslovných slov (pravidla jsou vidět v náhledu, žádný odhad navíc).
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Potraviny", ("albert", "lidl", "billa", "tesco", "kaufland", "penny", "globus", "rohlik", "nakup", "potraviny")),
    ("Jídlo", ("obed", "vecere", "snidane", "svacina", "kava", "kafe", "restaurace", "pizza", "bageta", "jidlo")),
    ("Doprava", ("mhd", "jizdenka", "listek", "vlak", "autobus", "bus", "benzin", "nafta", "taxi", "uber", "bolt", "tramvaj")),
    ("Bydlení", ("najem", "energie", "elektrina", "plyn", "internet", "voda")),
    ("Zábava", ("kino", "netflix", "spotify", "steam", "koncert", "divadlo", "hra")),
    ("Zdraví", ("lekarna", "lekar", "doktor", "fyzio", "zubar")),
]
INCOME_CATEGORY_RULES = [("Výplata", ("vyplata", "vyplatu", "plat"))]


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


class _Text:
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


def _find_date(t: _Text, today: date, d: Draft, *, allow_past: bool = False) -> date | None:
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


def _find_time(t: _Text, d: Draft) -> str | None:
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


def _when_label(local_dt: datetime, today: date) -> str:
    day = local_dt.date()
    rel = {0: "dnes", 1: "zítra", 2: "pozítří"}.get((day - today).days)
    head = rel or f"{_WD_SHORT[day.weekday()]} {format_date_cz(day)}"
    return f"{head} v {local_dt:%H:%M}"


# ---------- klasifikace ----------


def classify(t: _Text) -> tuple[str, str]:
    """(druh, jistota) podle pevné priority: výslovná připomínka > škola > práce > relativní čas / čas > peníze."""
    f = t.f
    if KW_REMINDER.search(f):
        return "reminder", "high"
    if KW_EXAM.search(f):
        return "exam", "high"
    if KW_ASSIGNMENT.search(f):
        return "assignment", "high"
    relative = RE_RELATIVE.search(f)
    hours = duration_matches(f)  # čas hodin („od 14 hodin") se jako délka práce nepočítá (MRK-11)
    if KW_WORK.search(f) or RE_RATE.search(f):
        return "work", "high"
    if hours:
        return "work", "medium"  # „2 h Servind" – hodiny bez slova „práce"
    if relative or (RE_TIME.search(f) and not RE_MONEY.search(f)):
        dated = RE_DAYWORD.search(f) or RE_WEEKDAY.search(f) or RE_DATE.search(f) or RE_ISO.search(f)
        return "reminder", "high" if relative or dated else "medium"
    if RE_MONEY.search(f) or KW_INCOME.search(f) or KW_EXPENSE.search(f):
        return "finance", "high"
    if RE_BARE_NUM.search(f):
        return "finance", "low"
    return "unknown", "low"


# ---------- jednotlivé typy ----------


def _parse_reminder(t: _Text, d: Draft, now_utc: datetime):
    local_now = now_local(now_utc)
    today = local_now.date()
    km = KW_REMINDER.search(t.f)
    if km:
        t.take(km)
    rel = RE_RELATIVE.search(t.f)
    due: datetime | None = None
    if rel:
        t.take(rel)
        qty_raw, unit = rel.group(1), (rel.group(2) or "")
        qty = 0.5 if qty_raw == "pul" else 1.0 if qty_raw in ("hodinu", "minutu") else _num(qty_raw)
        minutes = qty if unit.startswith("min") or qty_raw == "minutu" else qty * 60
        if qty_raw == "hodinu" or (qty_raw == "pul" and not unit.startswith("min")):
            minutes = qty * 60
        due = (local_now + timedelta(minutes=minutes)).replace(second=0, microsecond=0, tzinfo=None)
    else:
        day = _find_date(t, today, d)
        starts = RE_TIME.search(t.f)
        tm = _find_time(t, d)
        if tm and not km and starts and starts.group("prep") == "od":
            # událost s časem začátku – samostatný kalendář zatím není, uloží se jako připomínka v čas začátku
            d.warnings.append(f"Začátek v {tm} – uloží se jako připomínka na tento čas.")
        if d.errors:
            pass
        elif day is None and tm is None:
            d.need("due_local", "Kdy ti to mám připomenout?")
        else:
            if tm is None:
                tm = DEFAULT_REMINDER_TIME
                d.warnings.append(f"Čas nezadán – nastaveno {DEFAULT_REMINDER_TIME}.")
            if day is None:
                day = today
                if tm <= f"{local_now:%H:%M}":
                    day = today + timedelta(days=1)
                    d.warnings.append("Ten čas už dnes proběhl – nastaveno na zítra.")
            due = datetime.fromisoformat(f"{day.isoformat()}T{tm}")
    title = t.rest(KW_REMINDER)
    d.fields = {"title": title, "due_local": due.strftime("%Y-%m-%dT%H:%M") if due else ""}
    if not title:
        d.need("title", "Co ti mám připomenout?")
    if due and due <= local_now.replace(tzinfo=None):
        d.error("due_local", "Ten čas už proběhl.")


def _infer_category(f: str, income: bool) -> tuple[str, str | None]:
    words = set(re.findall(r"[a-z]+", f))
    for cat, keys in INCOME_CATEGORY_RULES if income else CATEGORY_RULES:
        hit = next((k for k in keys if k in words), None)
        if hit:
            return cat, hit
    return ("Příjem" if income else "Ostatní"), None


def _parse_finance(t: _Text, d: Draft, now_utc: datetime):
    income = bool(KW_INCOME.search(t.f))
    m = RE_MONEY.search(t.f)
    amount = None
    if m:
        t.take(m)
        amount = _num(m.group(1))
    else:
        b = RE_BARE_NUM.search(t.f)
        if b:
            t.take(b)
            amount = _num(b.group(1))
            d.need("amount", f"Je to {format_num_cz(amount)} Kč?")
        else:
            d.need("amount", "Jaká je částka?")
    for kw in (KW_INCOME, KW_EXPENSE):
        km = kw.search(t.f)
        if km:
            t.take(km)
    category, rule = _infer_category(t.f, income)
    description = t.rest(re.compile(r"\b(kc|czk)\b"))
    d.fields = {
        "transaction_type": "income" if income else "expense",
        "amount": amount,
        "category": category,
        "description": description,
    }
    if rule:
        d.warnings.append(f"Kategorie „{category}“ podle slova „{rule}“.")
    elif not income:
        d.warnings.append("Kategorie neurčena – nastaveno „Ostatní“.")
    _validate_finance(d.fields, d)


def _parse_work(t: _Text, d: Draft, now_utc: datetime, confidence: str):
    today = now_local(now_utc).date()
    rate_m = RE_RATE.search(t.f)
    rate = None
    if rate_m:
        t.take(rate_m)
        rate = _num(rate_m.group(1))
    durations = duration_matches(t.f)
    hm = durations[0] if durations else None
    hours = None
    if hm:
        t.take(hm)
        hours = _num(hm.group(1))
    else:
        d.need("hours", "Kolik hodin?")
    day = _find_date(t, today, d, allow_past=True) or today
    money = RE_MONEY.search(t.f)
    if money and rate is None:
        t.take(money)
        d.warnings.append(f"Částka {format_czk_cz(_num(money.group(1)))} bez „/h“ – nevím, jestli je to sazba; doplň ji.")
    km = KW_WORK.search(t.f)
    if km:
        t.take(km)
    project = t.rest()
    if rate is None:
        d.warnings.append("Bez hodinové sazby – výdělek 0 Kč, do Financí se nic nezapíše.")
    if confidence == "medium":
        d.warnings.append("Rozpoznáno jako práce podle hodin – zkontroluj.")
    d.fields = {
        "date": day.isoformat(),
        "hours": hours,
        "project": project,
        "hourly_rate": rate or 0,
        "sync_to_finance": True,
    }
    _validate_work(d.fields, d, today)


def match_subjects(f: str, subjects: list[dict]) -> tuple[list[dict], list[dict]]:
    """Předmět podle názvu / kódu v textu (bez diakritiky, i skloňovaně: „z práva" → Právo).

    Vrací (kandidáti, podobné): přesná shoda názvu nebo kódu má přednost před shodou kmene prvního slova;
    „podobné" jsou další předměty se stejným kmenem – náhled je ukáže, aby výběr nebyl potichu.
    """
    words = re.findall(r"[a-z0-9]+", f)
    exact, stem_hits = [], []
    for s in subjects:
        name = fold(" ".join(str(s["name"]).split()))
        code = fold(str(s.get("code") or ""))
        if (len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", f)) or (code and code in words):
            exact.append(s)
        first = name.split(" ")[0] if name else ""
        if len(first) >= 4:
            stem = first[: max(4, len(first) - 2)]
            if any(w.startswith(stem) for w in words):
                stem_hits.append(s)
    hits = exact or stem_hits
    similar = [s for s in stem_hits if s not in hits]
    return hits, similar


def _parse_school(t: _Text, d: Draft, now_utc: datetime, kind: str, subjects: list[dict]):
    today = now_local(now_utc).date()
    day = _find_date(t, today, d)
    _find_time(t, Draft())  # čas u zkoušky zatím neukládáme – jen ho vynechat z názvu
    high = KW_PRIORITY_HIGH.search(t.f)
    if high:
        t.take(high)
    hits, similar = match_subjects(t.f, subjects)
    title = t.rest()
    date_key = "exam_date" if kind == "exam" else "due_date"
    d.fields = {"title": title, "subject_id": hits[0]["id"] if len(hits) == 1 else None, date_key: day.isoformat() if day else ""}
    if kind == "exam":
        em = KW_EXAM.search(t.f)
        word = em.group(1) if em else "zkouska"
        d.fields["exam_type"] = "test" if word.startswith(("test", "pisem", "zapoc")) else "quiz" if word == "kviz" else "exam"
    else:
        d.fields["priority"] = "high" if high else "medium"
    if not title:
        d.need("title", "Jak se to jmenuje?")
    if len(hits) != 1:
        d.need("subject_id", "Vyber předmět." if hits else "Ke kterému předmětu to patří?")
        if len(hits) > 1:
            d.warnings.append("Text odpovídá více předmětům – vyber správný.")
    elif similar:
        d.warnings.append("Podobný předmět: " + ", ".join(s["name"] for s in similar[:3]) + " – zkontroluj výběr.")
    if not day and not any(e["field"] == "date" for e in d.errors):
        d.need(date_key, "Kdy je termín?")
    elif day and day < today:
        d.warnings.append("Termín je v minulosti.")


# ---------- validace (parse i prepare – frontendu se nevěří) ----------


def _validate_finance(f: dict, d: Draft):
    a = f.get("amount")
    if a is not None:
        if not isinstance(a, (int, float)) or a <= 0:
            d.error("amount", "Částka musí být kladná.")
        elif a > MAX_AMOUNT:
            d.error("amount", "Částka je nepřiměřeně vysoká.")
    if f.get("transaction_type") not in ("income", "expense"):
        d.error("transaction_type", "Typ musí být příjem nebo výdaj.")
    if len(str(f.get("category") or "")) > 100:
        d.error("category", "Kategorie je moc dlouhá.")
    if len(str(f.get("description") or "")) > 255:
        d.error("description", "Popis je moc dlouhý.")


def _validate_work(f: dict, d: Draft, today: date):
    h = f.get("hours")
    if h is not None and (not isinstance(h, (int, float)) or h <= 0 or h > MAX_HOURS):
        d.error("hours", f"Hodiny musí být mezi 0 a {MAX_HOURS}.")
    r = f.get("hourly_rate")
    if r is not None and (not isinstance(r, (int, float)) or r < 0 or r > MAX_RATE):
        d.error("hourly_rate", "Sazba je mimo rozsah.")
    try:
        day = date.fromisoformat(str(f.get("date")))
        if abs((day - today).days) > 366:
            d.error("date", "Datum je víc než rok od dneška.")
    except ValueError:
        d.error("date", "Neplatné datum.")
    if len(str(f.get("project") or "")) > 150:
        d.error("project", "Název projektu je moc dlouhý.")


# ---------- náhled ----------


def _display(kind: str, f: dict, subjects: dict[int, str], today: date) -> dict:
    if kind == "finance":
        income = f.get("transaction_type") == "income"
        amount = format_czk_cz(f["amount"]) if isinstance(f.get("amount"), (int, float)) else "? Kč"
        category = f.get("category") if f.get("category") not in ("Příjem", "Výdaj") else None
        return {"title": f.get("description") or f.get("category") or ("Příjem" if income else "Výdaj"),
                "subtitle": " · ".join(x for x in ("Příjem" if income else "Výdaj", amount, category, "dnes") if x),
                "area": "finance"}
    if kind == "work":
        parts = [format_hours_cz(f["hours"], 2) if f.get("hours") else "? h"]
        if f.get("hourly_rate"):
            parts.append(f"{format_czk_cz(f['hourly_rate'])}/h")
            if f.get("hours"):
                parts.append(format_czk_cz(round(f["hours"] * f["hourly_rate"], 2)))
        try:
            parts.append(format_date_cz(date.fromisoformat(f["date"])))
        except (KeyError, ValueError):
            pass
        return {"title": f.get("project") or "Práce", "subtitle": " · ".join(parts), "area": "work"}
    if kind == "reminder":
        sub = "Kdy? (doplň)"
        if f.get("due_local"):
            sub = _when_label(datetime.fromisoformat(f["due_local"]), today)
        return {"title": f.get("title") or "Připomínka", "subtitle": sub, "area": "reminders"}
    if kind in ("exam", "assignment"):
        key = "exam_date" if kind == "exam" else "due_date"
        label = {"test": "Test", "quiz": "Kvíz"}.get(f.get("exam_type"), "Zkouška") if kind == "exam" else "Úkol"
        when = format_date_cz(date.fromisoformat(f[key])) if f.get(key) else "termín? (doplň)"
        subj = subjects.get(f.get("subject_id")) or "předmět? (doplň)"
        return {"title": f.get("title") or label, "subtitle": " · ".join((label, subj, when)), "area": "school"}
    return {"title": "", "subtitle": "", "area": None}


def _subjects(db: Session | None) -> list[dict]:
    if db is None:
        return []
    return [{"id": s.id, "name": s.name, "code": s.code or ""} for s in
            db.query(Subject).filter(Subject.active == True).order_by(Subject.name).limit(200).all()]  # noqa: E712


def parse(text: str, *, db: Session | None = None, now_utc: datetime | None = None, subjects: list[dict] | None = None,
          access: ModuleAccess | None = None) -> dict:
    now_utc = now_utc or utc_now()
    t = _Text(text)
    subj = subjects if subjects is not None else _subjects(db)
    d = Draft()
    if len(t.raw) < 2:
        d.kind = "empty"
    else:
        d.kind, d.confidence = classify(t)
        if d.kind in KINDS and not (access or current_access()).allows_quick_add_kind(d.kind):
            # Roadmap 6C: vypnutý modul = jako by druh neexistoval (nic se nepředvyplní ani neuloží).
            d.kind, d.confidence = "unknown", "low"
        if d.kind == "reminder":
            _parse_reminder(t, d, now_utc)
        elif d.kind == "finance":
            _parse_finance(t, d, now_utc)
            if d.confidence == "low":
                d.confidence = "medium"
        elif d.kind == "work":
            _parse_work(t, d, now_utc, d.confidence)
        elif d.kind in ("exam", "assignment"):
            _parse_school(t, d, now_utc, d.kind, subj)
    if (d.needs_input or d.errors) and d.confidence == "high":
        d.confidence = "medium"
    today = now_local(now_utc).date()
    names = {s["id"]: s["name"] for s in subj}
    result = {
        "kind": d.kind,
        "confidence": d.confidence,
        "fields": d.fields,
        "display": _display(d.kind, d.fields, names, today),
        "warnings": d.warnings,
        "needs_input": d.needs_input,
        "errors": d.errors,
        "ready": d.kind in KINDS and not d.needs_input and not d.errors,
    }
    if d.kind in ("exam", "assignment"):
        result["subjects"] = [{"id": s["id"], "name": s["name"]} for s in subj]
    return result


# ---------- příprava zápisu (validace + pending akce) ----------


class QuickAddInvalid(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("invalid")
        self.errors = errors


def _float(v, fld: str, d: Draft):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except (TypeError, ValueError):
        d.error(fld, "Musí to být číslo.")
        return None


def to_tool_call(db: Session, kind: str, fields: dict, now_utc: datetime | None = None, *,
                 access: ModuleAccess | None = None) -> tuple[str, dict]:
    """Ověří pole z náhledu (po úpravách) a vrátí (WRITE tool, argumenty). Chyby → QuickAddInvalid."""
    if kind in KINDS and not (access or current_access()).allows_quick_add_kind(kind):
        # frontend se nikdy nebere za pravdu – ani ručně poslaný druh vypnutého modulu nic nevytvoří
        raise QuickAddInvalid([{"field": "kind", "message": "Tento modul je vypnutý."}])
    now_utc = now_utc or utc_now()
    today = now_local(now_utc).date()
    f = fields if isinstance(fields, dict) else {}
    d = Draft()
    req = lambda key, msg: str(f.get(key) or "").strip() or d.error(key, msg)  # noqa: E731
    if kind == "finance":
        clean = {
            "amount": _float(f.get("amount"), "amount", d),
            "transaction_type": f.get("transaction_type"),
            "category": str(f.get("category") or "").strip() or "Ostatní",
            "description": str(f.get("description") or "").strip(),
        }
        if clean["amount"] is None and not d.errors:
            d.error("amount", "Doplň částku.")
        _validate_finance(clean, d)
        tool, args = "add_finance_transaction", clean
    elif kind == "work":
        clean = {
            "date": str(f.get("date") or ""),
            "hours": _float(f.get("hours"), "hours", d),
            "project": str(f.get("project") or "").strip(),
            "hourly_rate": _float(f.get("hourly_rate"), "hourly_rate", d) or 0.0,
        }
        if clean["hours"] is None and not d.errors:
            d.error("hours", "Doplň hodiny.")
        _validate_work(clean, d, today)
        tool, args = "add_work_session", {
            "date_value": clean["date"], "hours": clean["hours"], "project": clean["project"],
            "hourly_rate": clean["hourly_rate"], "description": "", "sync_to_finance": bool(f.get("sync_to_finance", True)),
        }
    elif kind == "reminder":
        title = req("title", "Doplň, co připomenout.")
        due = req("due_local", "Doplň čas.")
        if due:
            try:
                local_due = datetime.fromisoformat(due[:16])
                if local_to_utc(local_due) <= now_utc:
                    d.error("due_local", "Ten čas už proběhl.")
                elif (local_due.date() - today).days > 366:
                    d.error("due_local", "Víc než rok dopředu.")
            except ValueError:
                d.error("due_local", "Neplatný čas.")
        tool, args = "add_reminder", {"title": title or "", "due_local": (due or "")[:16]}
    elif kind in ("exam", "assignment"):
        title = req("title", "Doplň název.")
        key = "exam_date" if kind == "exam" else "due_date"
        when = req(key, "Doplň termín.")
        if when:
            try:
                if abs((date.fromisoformat(when) - today).days) > 366:
                    d.error(key, "Termín je víc než rok od dneška.")
            except ValueError:
                d.error(key, "Neplatné datum.")
        try:
            sid = int(f.get("subject_id"))
        except (TypeError, ValueError):
            sid = None
        if sid is None or db.query(Subject.id).filter(Subject.id == sid).first() is None:
            d.error("subject_id", "Vyber existující předmět.")
        if title and len(title) > 255:
            d.error("title", "Název je moc dlouhý.")
        if kind == "exam":
            et = f.get("exam_type") if f.get("exam_type") in ("exam", "test", "quiz", "midterm", "oral", "other") else "exam"
            tool, args = "add_school_exam", {"title": title or "", "subject_id": sid, "exam_type": et, "exam_date": when}
        else:
            pr = f.get("priority") if f.get("priority") in ("low", "medium", "high") else "medium"
            tool, args = "add_school_assignment", {"title": title or "", "subject_id": sid, "due_date": when, "priority": pr}
    else:
        d.error("kind", "Neznámý typ záznamu.")
        tool, args = "", {}
    if d.errors:
        raise QuickAddInvalid(d.errors)
    return tool, args
