"""MRK-60 (Finance v1 A): Finance data never reaches an LLM.

Finance has no `ai_context` capability (module_registry), no AI tools, no AI mutation entity and no section in the
daily/weekly snapshot. Other AI-facing surfaces (goals, notifications, activity log) carry Finance data indirectly;
they filter it with the predicates below so the rule lives in one place. Deterministic, non-AI features
(Finance page, Search, dashboard, Quick Add, What Changed) are not affected.
"""
from __future__ import annotations

FINANCE_AREA = "finance"
# Oblasti, které AI záměrně nevidí: dotaz jen na ně nedostane žádné tooly (ani náhradní z jiných oblastí).
AI_EXCLUDED_AREAS = frozenset({FINANCE_AREA})
_FINANCE_ENTITY_TYPES = frozenset({"FinanceTransaction"})
_FINANCE_NOTIFICATION_TYPES = frozenset({"finance_goal_stagnation"})


def is_finance_goal(source: str | None) -> bool:
    """Automatic goal whose value is computed from Finance transactions (finance_balance, finance_month_*)."""
    return (source or "").strip().lower().startswith(FINANCE_AREA)


def finance_goal_ids(db) -> frozenset[int]:
    """Ids of goals computed from Finance. Their Activity rows (edits, progress snapshots "Cíl 'X' 40% → 45%") are
    logged under area "goals", so area alone does not hide them (MRK-71)."""
    from models import Goal  # lazy: keeps this module importable without the ORM
    return frozenset(gid for gid, source in db.query(Goal.id, Goal.source).all() if is_finance_goal(source))


def is_finance_activity(area: str | None, entity_type: str | None = None, entity_id: int | None = None,
                        finance_goals: frozenset[int] = frozenset()) -> bool:
    if (area or "").strip().lower() == FINANCE_AREA or (entity_type or "") in _FINANCE_ENTITY_TYPES:
        return True
    return entity_type == "Goal" and entity_id in finance_goals


def is_finance_notification(area: str | None, notification_type: str | None = None) -> bool:
    return (area or "").strip().lower() == FINANCE_AREA or (notification_type or "") in _FINANCE_NOTIFICATION_TYPES
