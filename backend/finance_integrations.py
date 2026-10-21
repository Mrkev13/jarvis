"""Příspěvky modulu Finance do globálních agregátorů (MRK-20) – přesunuto beze změny chování ze search_service,
main (GET /dashboard „finance") a quick_add_service. AI kontext Finance nemá (MRK-60)."""
from __future__ import annotations

import re
from datetime import date, datetime

import quick_add_text as qt
from goal_history_service import compute_goal_progress_and_value
from models import FinanceTransaction, Goal
from module_contracts import (
    ChangeSource, activity_changes,
    ContextSection, DashboardSection, ModuleIntegrations, QuickAddKind, QuickAddRule, SearchSource,
)
from text_utils import finance_category_label_cz, format_czk_cz, format_date_cz, format_num_cz, join_parts
from time_utils import local_month_bounds_utc, today_local

ROW_LIMIT = 500
MAX_AMOUNT = 10_000_000

# ---------- vyhledávání ----------


def search_finance(db, q):
    for t in db.query(FinanceTransaction).order_by(FinanceTransaction.created_at.desc(), FinanceTransaction.id.desc()).limit(ROW_LIMIT).all():
        kind = "Příjem" if t.transaction_type == "income" else "Výdaj"
        category = finance_category_label_cz(t.category)
        title = t.description or category or kind
        sub = join_parts(kind, format_czk_cz(t.amount), category if t.description else "", format_date_cz(t.created_at) if t.created_at else "")
        yield "transaction", t.id, title, sub, f"{category} {t.category or ''} {kind}", "finance", f"/finance?transaction={t.id}"


# ---------- GET /dashboard: „finance" ----------


def get_finance_with_goal(db, today: date | None = None):
    transactions = db.query(FinanceTransaction).all()
    income = 0.0
    expenses = 0.0
    today = today or today_local()
    # created_at je naive UTC → porovnání s pražským měsícem převedeným do UTC.
    month_start_utc, month_end_utc = local_month_bounds_utc(today)
    this_month_income = 0.0
    this_month_expenses = 0.0
    for t in transactions:
        amt = float(t.amount or 0.0)
        in_this_month = t.created_at is not None and month_start_utc <= t.created_at < month_end_utc
        if (t.transaction_type or "").lower() == "income":
            income += amt
            if in_this_month:
                this_month_income += amt
        else:
            expenses += amt
            if in_this_month:
                this_month_expenses += amt
    goal_row = (
        db.query(Goal)
        .filter(Goal.source == "finance_balance")
        .all()
    )
    active_goal = None
    balance = income - expenses
    for g in goal_row:
        s = (g.status or "").lower()
        if s in ("completed", "cancelled", "paused"):
            continue
        progress, current_value = compute_goal_progress_and_value(db, g, today=today)
        active_goal = {
            "id": g.id,
            "title": g.title,
            "current_value": float(current_value) if current_value is not None else float(balance),
            "target_value": float(g.target_value) if g.target_value is not None else None,
            "progress": progress,
            "target_date": g.target_date.isoformat() if g.target_date else None,
        }
        break
    return {
        "balance": round(balance, 2),
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "this_month_income": round(this_month_income, 2),
        "this_month_expenses": round(this_month_expenses, 2),
        "transactions_count": len(transactions),
        "goal": active_goal,
    }


# ---------- Rychlé přidání ----------

KW_INCOME = re.compile(r"\b(prijem|vyplata|vyplatu|dostal\w*|faktura|fakturu)\b")
KW_EXPENSE = re.compile(r"\b(vydaj|zaplatil\w*|koupil\w*|utratil\w*|platba)\b")

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


def detect_finance(t) -> str | None:
    f = t.f
    if qt.RE_MONEY.search(f) or KW_INCOME.search(f) or KW_EXPENSE.search(f):
        return "high"
    return None


def detect_bare_number(t) -> str | None:
    return "low" if qt.RE_BARE_NUM.search(t.f) else None


def _infer_category(f: str, income: bool) -> tuple[str, str | None]:
    words = set(re.findall(r"[a-z]+", f))
    for cat, keys in INCOME_CATEGORY_RULES if income else CATEGORY_RULES:
        hit = next((k for k in keys if k in words), None)
        if hit:
            return cat, hit
    return ("Příjem" if income else "Ostatní"), None


def validate_finance(f: dict, d):
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


def parse_finance(t, d, now_utc: datetime, ctx: dict):
    income = bool(KW_INCOME.search(t.f))
    m = qt.RE_MONEY.search(t.f)
    amount = None
    if m:
        t.take(m)
        amount = qt.num(m.group(1))
    else:
        b = qt.RE_BARE_NUM.search(t.f)
        if b:
            t.take(b)
            amount = qt.num(b.group(1))
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
    validate_finance(d.fields, d)
    if d.confidence == "low":
        d.confidence = "medium"  # holé číslo: náhled se zeptá na částku


def finance_tool_call(f: dict, d, today, now_utc, db) -> tuple[str, dict]:
    clean = {
        "amount": qt.float_field(f.get("amount"), "amount", d),
        "transaction_type": f.get("transaction_type"),
        "category": str(f.get("category") or "").strip() or "Ostatní",
        "description": str(f.get("description") or "").strip(),
    }
    if clean["amount"] is None and not d.errors:
        d.error("amount", "Doplň částku.")
    validate_finance(clean, d)
    return "add_finance_transaction", clean


def finance_display(f: dict, ctx: dict, today) -> dict:
    income = f.get("transaction_type") == "income"
    amount = format_czk_cz(f["amount"]) if isinstance(f.get("amount"), (int, float)) else "? Kč"
    category = f.get("category") if f.get("category") not in ("Příjem", "Výdaj") else None
    return {"title": f.get("description") or f.get("category") or ("Příjem" if income else "Výdaj"),
            "subtitle": " · ".join(x for x in ("Příjem" if income else "Výdaj", amount, category, "dnes") if x),
            "area": "finance"}


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource("finance", areas=frozenset({"finance"}),
                          from_activity=activity_changes({"finance_transaction": "/finance?transaction={id}"}, "/finance")),),
    search=(SearchSource("finance", 60, search_finance),),
    dashboard=(DashboardSection("finance", lambda db, access: get_finance_with_goal(db)),),
    # MRK-60: jen klíčová slova (bez `build` – žádná data, žádné pokryté tooly). Finanční dotaz se tak pozná jako
    # oblast bez AI toolů a router nesáhne po obecné sadě všech read toolů; Finance do AI nejde (finance_ai_policy.py).
    context=(
        ContextSection("finance", ("penez", "penize", "financ", "vydaj", "prijem", "prijm", "utrat", "bilanc", "uspor",
                                   "setr", "rozpoc", " kc", "korun", "money", "zustatek")),
    ),
    quick_add_rules=(
        QuickAddRule(70, "finance", detect_finance),
        QuickAddRule(80, "finance", detect_bare_number),
    ),
    quick_add_kinds=(QuickAddKind("finance", parse_finance, finance_tool_call, finance_display),),
)
