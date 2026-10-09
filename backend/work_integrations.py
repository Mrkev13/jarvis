"""Příspěvky modulu Práce do globálních agregátorů (MRK-20) – přesunuto beze změny chování ze search_service,
main (GET /dashboard „work"), context_service a quick_add_service."""
from __future__ import annotations

import re
from datetime import date, datetime

import quick_add_text as qt
from context_format import fmt_num, short
from goal_history_service import compute_goal_progress_and_value
from models import Goal, WorkSession
from module_contracts import (
    ChangeSource, activity_changes,
    ContextRequest, ContextSection, DashboardSection, ModuleIntegrations, QuickAddKind, QuickAddRule, SearchSource,
)
from text_utils import format_czk_cz, format_date_cz, format_hours_cz, join_parts
from time_utils import now_local, today_local

ROW_LIMIT = 500
MAX_HOURS = 24
MAX_RATE = 100_000

# ---------- vyhledávání ----------


def search_work(db, q):
    for w in db.query(WorkSession).order_by(WorkSession.date.desc(), WorkSession.id.desc()).limit(ROW_LIMIT).all():
        title = w.project or w.description or "Pracovní záznam"
        sub = join_parts("Práce", format_date_cz(w.date), format_hours_cz(w.hours, 1), w.description if w.project else "")
        yield "work_session", w.id, title, sub, f"{w.description or ''} prace", "work", f"/work?session={w.id}"


# ---------- GET /dashboard: „work" ----------


def get_work_with_goal(db, today: date | None = None):
    today = today or today_local()
    this_month = (today.year, today.month)
    items = db.query(WorkSession).all()
    this_month_hours = 0.0
    this_month_earnings = 0.0
    total_hours = 0.0
    total_earnings = 0.0
    for it in items:
        earn = float(it.hours or 0.0) * float(it.hourly_rate or 0.0)
        total_hours += float(it.hours or 0.0)
        total_earnings += earn
        if (it.date.year, it.date.month) == this_month:
            this_month_hours += float(it.hours or 0.0)
            this_month_earnings += earn
    goal_row = (
        db.query(Goal)
        .filter(Goal.source == "work_month_hours")
        .all()
    )
    active_goal = None
    for g in goal_row:
        s = (g.status or "").lower()
        if s in ("completed", "cancelled", "paused"):
            continue
        progress, current_value = compute_goal_progress_and_value(db, g, today=today)
        active_goal = {
            "id": g.id,
            "title": g.title,
            "current_value": float(current_value) if current_value is not None else float(this_month_hours),
            "target_value": float(g.target_value) if g.target_value is not None else None,
            "progress": progress,
            "target_date": g.target_date.isoformat() if g.target_date else None,
        }
        break
    return {
        "total_hours": round(total_hours, 2),
        "total_earnings": round(total_earnings, 2),
        "this_month_hours": round(this_month_hours, 2),
        "this_month_earnings": round(this_month_earnings, 2),
        "goal": active_goal,
    }


# ---------- AI kontext ----------


def context_work(req: ContextRequest) -> list[str]:
    db, today = req.db, req.today
    month_start = today.replace(day=1)
    sessions = db.query(WorkSession).filter(WorkSession.date >= month_start, WorkSession.date <= today).all()
    hours = sum(float(s.hours or 0) for s in sessions)
    earnings = sum(float(s.hours or 0) * float(s.hourly_rate or 0) for s in sessions)
    last = db.query(WorkSession).order_by(WorkSession.date.desc(), WorkSession.id.desc()).first()
    last_txt = (
        f"; poslední záznam {last.date.isoformat()} {short(last.project or '-', 30)} {fmt_num(float(last.hours or 0))} h"
        if last else "; žádné záznamy"
    )
    return [f"Práce tento měsíc: {fmt_num(hours)} h, {fmt_num(earnings)} Kč{last_txt}"]


def project_names(db):
    """Zmínka názvu projektu („jak jsem na tom se Servindem") = oblast práce."""
    return [p for (p,) in db.query(WorkSession.project).distinct().all() if p]


# ---------- Rychlé přidání ----------

KW_WORK = re.compile(r"\b(prace|praci|pracoval\w*|makal\w*|smena|smenu)\b")


def detect_work_keyword(t) -> str | None:
    return "high" if KW_WORK.search(t.f) or qt.RE_RATE.search(t.f) else None


def detect_work_hours(t) -> str | None:
    # čas hodin („od 14 hodin") ani relativní čas se jako délka práce nepočítá (MRK-11)
    return "medium" if qt.duration_matches(t.f) else None  # „2 h Servind" – hodiny bez slova „práce"


def validate_work(f: dict, d, today: date):
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


def parse_work(t, d, now_utc: datetime, ctx: dict):
    confidence = d.confidence
    today = now_local(now_utc).date()
    rate_m = qt.RE_RATE.search(t.f)
    rate = None
    if rate_m:
        t.take(rate_m)
        rate = qt.num(rate_m.group(1))
    durations = qt.duration_matches(t.f)
    hm = durations[0] if durations else None
    hours = None
    if hm:
        t.take(hm)
        hours = qt.num(hm.group(1))
    else:
        d.need("hours", "Kolik hodin?")
    day = qt.find_date(t, today, d, allow_past=True) or today
    money = qt.RE_MONEY.search(t.f)
    if money and rate is None:
        t.take(money)
        d.warnings.append(f"Částka {format_czk_cz(qt.num(money.group(1)))} bez „/h“ – nevím, jestli je to sazba; doplň ji.")
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
    validate_work(d.fields, d, today)


def work_tool_call(f: dict, d, today, now_utc, db) -> tuple[str, dict]:
    clean = {
        "date": str(f.get("date") or ""),
        "hours": qt.float_field(f.get("hours"), "hours", d),
        "project": str(f.get("project") or "").strip(),
        "hourly_rate": qt.float_field(f.get("hourly_rate"), "hourly_rate", d) or 0.0,
    }
    if clean["hours"] is None and not d.errors:
        d.error("hours", "Doplň hodiny.")
    validate_work(clean, d, today)
    return "add_work_session", {
        "date_value": clean["date"], "hours": clean["hours"], "project": clean["project"],
        "hourly_rate": clean["hourly_rate"], "description": "", "sync_to_finance": bool(f.get("sync_to_finance", True)),
    }


def work_display(f: dict, ctx: dict, today) -> dict:
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


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource("work", areas=frozenset({"work"}),
                          from_activity=activity_changes({"work_session": "/work?session={id}"}, "/work")),),
    search=(SearchSource("work", 50, search_work),),
    dashboard=(DashboardSection("work", lambda db, access: get_work_with_goal(db)),),
    context=(
        ContextSection("work", ("prac", "odprac", "hodin", "smen", "vydelek", "vydelal", "sazb"), order=50,
                       build=context_work, covered_tools=("get_work_summary",), name_hints=project_names),
    ),
    quick_add_rules=(
        QuickAddRule(40, "work", detect_work_keyword),
        QuickAddRule(50, "work", detect_work_hours),
    ),
    quick_add_kinds=(QuickAddKind("work", parse_work, work_tool_call, work_display),),
)
