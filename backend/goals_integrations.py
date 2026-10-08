"""Příspěvky modulu Cíle do globálních agregátorů (MRK-20) – přesunuto beze změny chování ze search_service,
main (GET /dashboard „goals"), context_service, today_service (odkaz z plánu) a scheduler_service (snímky)."""
from __future__ import annotations

from datetime import date

from context_format import MAX_ITEMS, PRIORITY_RANK, fmt_num, list_or_none, short
from goal_history_service import compute_goal_progress_and_value, ensure_goal_progress_snapshot_for_all_active_automatic_goals
from models import Goal
from module_contracts import (
    ChangeSource, activity_changes,
    ContextRequest, ContextSection, DashboardSection, EntityRef, ModuleIntegrations, ScheduledStep, SearchSource,
)
from statuses import GOAL_INACTIVE_STATUSES
from text_utils import format_date_cz, join_parts
from time_utils import today_local

ROW_LIMIT = 500
_GOAL_STATUS = {"active": "aktivní", "in_progress": "rozpracovaný", "completed": "splněný", "paused": "pozastavený", "cancelled": "zrušený"}

# ---------- vyhledávání ----------


def search_goals(db, q):
    for g in db.query(Goal).limit(ROW_LIMIT).all():
        # stejné procento jako stránka Cíle – automatické cíle mají `progress` ve sloupci 0, hodnota se počítá
        pct, _ = compute_goal_progress_and_value(db, g)
        sub = join_parts("Cíl", _GOAL_STATUS.get((g.status or "").lower(), ""), f"{pct} %", f"do {format_date_cz(g.target_date)}" if g.target_date else "")
        yield "goal", g.id, g.title, sub, f"{g.description or ''} cil", "goals", f"/goals?goal={g.id}"


# ---------- GET /dashboard: „goals" ----------


def top_active_goals(db, limit: int = 3):

    today = today_local()
    rows = db.query(Goal).all()
    enriched: list[dict] = []
    for g in rows:
        status = (g.status or "").lower()
        if status in GOAL_INACTIVE_STATUSES:
            continue
        progress, current_value = compute_goal_progress_and_value(db, g, today=today)
        enriched.append({
            "id": g.id,
            "title": g.title,
            "area": g.area or "general",
            "priority": g.priority or "medium",
            "progress": progress,
            "current_value": float(current_value) if current_value is not None else None,
            "target_value": float(g.target_value) if g.target_value is not None else None,
            "target_date": g.target_date.isoformat() if g.target_date else None,
            "tracking_type": (g.tracking_type or "manual").lower(),
            "source": g.source,
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}

    def sort_key(g):
        td = g.get("target_date")
        td_delta = 999_999 if not td else 0
        try:
            if td:
                from datetime import date as _d
                delta = (_d.fromisoformat(td) - today).days
                td_delta = delta
        except Exception:
            pass
        return (
            priority_order.get((g["priority"] or "").lower(), 3),
            td_delta,
            int(g.get("progress") or 0),
        )

    enriched.sort(key=sort_key)
    return enriched[:max(0, int(limit))]


def dashboard_goals(db, access):
    goals_list = top_active_goals(db, limit=3)
    return {
        "top": goals_list,
        "count": len(goals_list),
    }


# ---------- AI kontext ----------


def context_goals(req: ContextRequest) -> list[str]:
    db, today = req.db, req.today
    goals = [g for g in db.query(Goal).all() if (g.status or "").strip().lower() not in GOAL_INACTIVE_STATUSES]
    goals.sort(key=lambda g: (PRIORITY_RANK.get((g.priority or "").lower(), 3), g.target_date or date.max))
    items = []
    for g in goals[:MAX_ITEMS]:
        progress, current = compute_goal_progress_and_value(db, g, today=today)
        value = ""
        if current is not None and g.target_value:
            value = f" ({fmt_num(current)} / {fmt_num(float(g.target_value))})"
        deadline = f", do {g.target_date.isoformat()}" if g.target_date else ""
        items.append(f"\"{short(g.title, 50)}\" {progress} %{value}{deadline}")
    return [f"Aktivní cíle: {list_or_none(items, len(goals))}"]


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource("goals", areas=frozenset({"goals"}),
                          from_activity=activity_changes({"goal": "/goals?goal={id}"}, "/goals")),),
    search=(SearchSource("goals", 70, search_goals),),
    entity_refs=(EntityRef("goal", "/goals?goal={id}", notification_source=True),),
    dashboard=(DashboardSection("goals", dashboard_goals),),
    context=(
        ContextSection("goals", ("cil", "cile", "goal", "progres"), order=40, build=context_goals,
                       covered_tools=("get_goals", "get_goals_summary")),
    ),
    hourly=(ScheduledStep("goal snapshots", ensure_goal_progress_snapshot_for_all_active_automatic_goals),),
)
