"""MRK-72: AI tool `upsert_goal` – a new goal is created as before; an edit of an existing goal (`id`) becomes a
`modify_records` plan for the `goal` entity.

The old update path overwrote every field the model did not send with its default (description "", status active,
progress 0, no target date). The plan path changes only the fields that were given and differ, shows "old → new" on the
confirmation card, re-checks the goal at confirmation (stale target) and records undo. It also inherits the goal
entity's rules: no manual progress for automatic goals, finance goals invisible to the AI (MRK-60).

MRK-71: the AI never creates a goal with area "finance" and never edits a finance goal (area "finance" or computed
from Finance). Checked fail-closed both when the action is prepared and again right before it runs.
"""
from __future__ import annotations

import tools
from finance_ai_policy import FINANCE_AREA, is_finance_goal
from models import Goal
from mutation_service import MutationRefused, execute_modify_records, propose_modify_records

FINANCE_GOAL_REFUSED = ("Finanční cíle Jarvis nevytváří ani neupravuje (Finance do AI nejde). "
                        "Uprav je prosím ručně v aplikaci.")


def _is_finance_area(area) -> bool:
    return (area or "").strip().lower() == FINANCE_AREA


def _refuse_finance(db, area=None, goal_ids=()) -> None:
    """MutationRefused when the call touches Finance: area "finance", or an existing goal that is a finance goal."""
    if _is_finance_area(area):
        raise MutationRefused("finance_goal", FINANCE_GOAL_REFUSED)
    for goal_id in goal_ids:
        goal = db.get(Goal, goal_id) if goal_id is not None else None
        if goal is not None and (_is_finance_area(goal.area) or is_finance_goal(goal.source)):
            raise MutationRefused("finance_goal", FINANCE_GOAL_REFUSED)


# `area` is accepted for schema compatibility but never edited: the goal entity has no area field after creation.
def prepare_upsert_goal(db, area=None, title=None, id=None, description=None, status=None, priority=None,
                        progress=None, target_date=None):
    """Resolver: no `id` → None (create: the arguments are stored as they are); `id` → partial update plan."""
    _refuse_finance(db, area, [id])
    if id is None:
        return None
    given = {"title": title, "description": description, "status": status, "priority": priority,
             "progress": progress, "target_date": target_date}
    # Missing, null or empty means "not mentioned", never "clear it": that is what silently wiped goals before.
    changes = {k: v for k, v in given.items() if v is not None and v != ""}
    return propose_modify_records(db, "goal", "update", {"id": id}, changes)


def run_upsert_goal(plan=None, user_context: str = "manual", **arguments):
    """Executor after confirmation: an edit plan goes through the mutation service, a create through upsert_goal."""
    db = tools.SessionLocal()
    try:  # re-checked at confirmation: an older pending action or a goal moved to Finance meanwhile
        ids = [t.get("id") for t in (plan or {}).get("targets") or []] + [arguments.get("id")]
        _refuse_finance(db, arguments.get("area"), ids)
    finally:
        db.close()
    if plan is not None:
        return execute_modify_records(plan, user_context=user_context)
    return tools.upsert_goal(**arguments, user_context=user_context)
