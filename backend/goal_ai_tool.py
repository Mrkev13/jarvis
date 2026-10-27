"""MRK-72: AI tool `upsert_goal` – a new goal is created as before; an edit of an existing goal (`id`) becomes a
`modify_records` plan for the `goal` entity.

The old update path overwrote every field the model did not send with its default (description "", status active,
progress 0, no target date). The plan path changes only the fields that were given and differ, shows "old → new" on the
confirmation card, re-checks the goal at confirmation (stale target) and records undo. It also inherits the goal
entity's rules: no manual progress for automatic goals, finance goals invisible to the AI (MRK-60).
"""
from __future__ import annotations

from mutation_service import execute_modify_records, propose_modify_records
from tools import upsert_goal


# `area` is accepted for schema compatibility but never edited: the goal entity has no area field after creation.
def prepare_upsert_goal(db, area=None, title=None, id=None, description=None, status=None, priority=None,
                        progress=None, target_date=None):
    """Resolver: no `id` → None (create: the arguments are stored as they are); `id` → partial update plan."""
    if id is None:
        return None
    given = {"title": title, "description": description, "status": status, "priority": priority,
             "progress": progress, "target_date": target_date}
    # Missing, null or empty means "not mentioned", never "clear it": that is what silently wiped goals before.
    changes = {k: v for k, v in given.items() if v is not None and v != ""}
    return propose_modify_records(db, "goal", "update", {"id": id}, changes)


def run_upsert_goal(plan=None, user_context: str = "manual", **arguments):
    """Executor after confirmation: an edit plan goes through the mutation service, a create through upsert_goal."""
    if plan is not None:
        return execute_modify_records(plan, user_context=user_context)
    return upsert_goal(**arguments, user_context=user_context)
