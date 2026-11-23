"""MRK-135: doménová událost „cíl splněn" (`goals.goal.completed`).

Cíl je splněný, když poprvé dosáhne 100 % nebo stavu `completed`. Událost vzniká ve stejné transakci jako změna
(volající commituje) a Aktivita je její projekcí. Payload nese jen id a předchozí procenta – žádné hodnoty cíle,
takže ani cíle navázané na Finance nic neprozradí (MRK-60).
"""
from __future__ import annotations

from domain_events import ActivityProjection, append_domain_event
from statuses import norm

GOAL_COMPLETED = "goals.goal.completed"
EVENTS = (GOAL_COMPLETED,)


def _done(pct: int | None, status: str | None) -> bool:
    return (pct or 0) >= 100 or norm(status) == "completed"


def goal_reached(before_pct: int | None, before_status: str | None, after_pct: int | None, after_status: str | None) -> bool:
    """Přechod nesplněný → splněný (opakované uložení splněného cíle nic nevyšle)."""
    if norm(after_status) in ("cancelled",):
        return False
    return _done(after_pct, after_status) and not _done(before_pct, before_status)


def emit_goal_completed(db, goal, *, previous_progress: int | None, user_context: str = "manual"):
    return append_domain_event(
        db,
        event_type=GOAL_COMPLETED,
        aggregate_type="goal",
        aggregate_id=goal.id,
        payload={"goal_id": goal.id, "previous_progress": int(previous_progress or 0)},
        activity=ActivityProjection("goals", "complete", f"Cíl '{goal.title}' splněn", entity_type="Goal",
                                    entity_id=goal.id, user_context=user_context),
    )
