"""Registr AI toolů – jediný zdroj pravdy (Roadmap 3.0 A5).

Každý tool má na jednom místě: jméno, druh (read/write), oblasti (pro routing), JSON schéma pro LLM,
volanou funkci, zda jeho data plně nese CURRENT STATE (covered_by_context) a které tooly potřebuje
mít k dispozici (requires – např. subject_id z get_school_subjects).

ai.py z registru odvozuje TOOLS / READ_TOOLS / WRITE_TOOLS / *_TOOL_FUNCTIONS; tool_router.py z něj
vybírá menší sadu toolů pro konkrétní dotaz.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from tools import get_wot_resources, get_wot_grinds
from tools import get_finance_summary
from tools import get_school_subjects
from tools import get_work_summary
from tools import get_mff_summary, get_mff_characters
from tools import get_goals_summary
from tools import get_memories
from tools import get_notifications, get_notification_summary, get_goal_progress_history
from tools import add_work_session, add_finance_transaction
from tools import add_school_subject, add_school_assignment, add_school_exam
from tools import update_wot_resource, upsert_wot_grind
from tools import upsert_mff_character, upsert_goal
from tools import save_memory
from read_queries import (
    query_finance_transactions,
    query_goals,
    query_recent_activity,
    query_school_assignments,
    query_school_exams,
    query_work_sessions,
)

READ, WRITE = "read", "write"

# Oblasti pro routing (shodné s context_service.classify_areas + intenty routeru).
AREA_FINANCE, AREA_WORK, AREA_SCHOOL, AREA_GOALS = "finance", "work", "school", "goals"
AREA_NOTIFICATIONS, AREA_WOT, AREA_MFF = "notifications", "wot", "mff"
AREA_MEMORY, AREA_ACTIVITY = "memory", "activity"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: str  # READ / WRITE
    areas: tuple[str, ...]
    schema: dict
    func: Callable
    covered_by_context: bool = False  # CURRENT STATE nese stejná data → při pokrytí není třeba ho posílat
    requires: tuple[str, ...] = ()  # tooly, bez kterých tento nejde smysluplně použít
    takes_db: bool = False  # funkce dostane db session AI requestu jako první argument

    @property
    def is_write(self) -> bool:
        return self.kind == WRITE


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    """OpenAI/Groq function tool. Popisy krátké – obecná pravidla (potvrzení, paměť, data) jsou v SYSTEM_PROMPT."""
    parameters: dict = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        parameters["required"] = required
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_PRIORITY = {"type": "string", "enum": ["high", "medium", "low"]}
_MEMORY_CATEGORY = {"type": "string", "enum": ["preference", "decision", "context", "routine", "constraint", "plan"]}
_MEMORY_AREA = {"type": "string", "description": "general, wot, finance, school, work, mff, personal, fitness, hobby, travel"}
# Filtrované read tooly (read_queries.py): výsledek {items,total,returned,truncated}; default 20 položek.
_LIMIT = {"type": "integer", "description": "default 20"}


def _read(name, description, properties=None, required=None, *, func, areas, covered=False, requires=(), takes_db=False):
    return ToolSpec(name, READ, tuple(areas), _tool(name, description, properties, required), func,
                    covered, tuple(requires), takes_db)


def _write(name, description, properties=None, required=None, *, func, areas, requires=()):
    return ToolSpec(name, WRITE, tuple(areas), _tool(name, description, properties, required), func,
                    False, tuple(requires))


TOOL_SPECS: tuple[ToolSpec, ...] = (
    # ===== READ =====
    _read("get_wot_resources", "WoT resources: credits, gold, bonds, free XP.",
          func=get_wot_resources, areas=[AREA_WOT], covered=True),
    _read("get_wot_grinds", "WoT tank grinds: XP remaining, priority, status.",
          func=get_wot_grinds, areas=[AREA_WOT]),
    _read("get_finance_summary", "Finance totals: income, expenses, balance, transaction count.",
          func=get_finance_summary, areas=[AREA_FINANCE]),
    _read(
        "get_finance_transactions",
        "Finance transactions, newest first.",
        {
            "limit": _LIMIT,
            "transaction_type": {"type": "string", "enum": ["income", "expense"]},
            "category": _STR,
            "date_from": _DATE,
            "date_to": _DATE,
        },
        func=query_finance_transactions, areas=[AREA_FINANCE], takes_db=True,
    ),
    _read("get_school_subjects", "School subjects with IDs (source of subject_id).",
          func=get_school_subjects, areas=[AREA_SCHOOL]),
    _read(
        "get_school_assignments",
        "School assignments by due date (default: open only).",
        {
            "limit": _LIMIT,
            "status": {"type": "string", "enum": ["open", "done", "all"]},
            "subject_id": _INT,
            "due_from": _DATE,
            "due_to": _DATE,
        },
        func=query_school_assignments, areas=[AREA_SCHOOL], takes_db=True,
    ),
    _read(
        "get_school_exams",
        "School exams by date (default: open only).",
        {
            "limit": _LIMIT,
            "status": {"type": "string", "enum": ["open", "passed", "failed", "all"]},
            "subject_id": _INT,
            "date_from": _DATE,
            "date_to": _DATE,
        },
        func=query_school_exams, areas=[AREA_SCHOOL], takes_db=True,
    ),
    _read("get_work_summary", "Work hours and earnings: total and current month.",
          func=get_work_summary, areas=[AREA_WORK]),
    _read(
        "get_work_sessions",
        "Work sessions with earnings, newest first.",
        {"limit": _LIMIT, "project": _STR, "date_from": _DATE, "date_to": _DATE},
        func=query_work_sessions, areas=[AREA_WORK], takes_db=True,
    ),
    _read("get_mff_summary", "MFF summary: character counts by tier and priority.",
          func=get_mff_summary, areas=[AREA_MFF]),
    _read("get_mff_characters", "MFF tracked characters with build details.",
          func=get_mff_characters, areas=[AREA_MFF]),
    _read("get_goals_summary", "Goal counts by status.",
          func=get_goals_summary, areas=[AREA_GOALS]),
    _read(
        "get_goals",
        "Goals: area, status, priority, progress, target date.",
        {
            "limit": _LIMIT,
            "area": _STR,
            "status": {"type": "string", "enum": ["all", "open", "paused", "completed"]},
        },
        func=query_goals, areas=[AREA_GOALS], takes_db=True,
    ),
    _read(
        "get_memories",
        "Long-term user memories. Never a source of numbers or dates.",
        {"area": _MEMORY_AREA, "category": _MEMORY_CATEGORY},
        func=get_memories, areas=[AREA_MEMORY],
    ),
    _read(
        "get_notifications",
        "Notifications, optionally filtered.",
        {
            "unread_only": _BOOL,
            "severity": {"type": "string", "enum": ["info", "warning", "important"]},
            "area": _STR,
            "include_resolved": _BOOL,
        },
        func=get_notifications, areas=[AREA_NOTIFICATIONS],
    ),
    _read("get_notification_summary", "Notification counters by severity and unread.",
          func=get_notification_summary, areas=[AREA_NOTIFICATIONS]),
    _read("get_goal_progress_history", "Progress snapshots of one goal.", {"goal_id": _INT}, ["goal_id"],
          func=get_goal_progress_history, areas=[AREA_GOALS], requires=["get_goals"]),
    _read(
        "get_recent_activity",
        "Recent app changes (activity log), newest first.",
        {"limit": _LIMIT, "area": _STR, "days": {"type": "integer", "description": "default 7"}},
        func=query_recent_activity, areas=[AREA_ACTIVITY], takes_db=True,
    ),
    # ===== WRITE (jen příprava pending akce; provedení až po potvrzení v UI) =====
    _write(
        "add_work_session",
        "Add a work session.",
        {
            "date_value": _DATE,
            "hours": _NUM,
            "project": {"type": "string", "description": "project or company"},
            "hourly_rate": {"type": "number", "description": "CZK per hour"},
            "description": _STR,
        },
        ["date_value", "hours", "project", "hourly_rate"],
        func=add_work_session, areas=[AREA_WORK],
    ),
    _write(
        "add_finance_transaction",
        "Add an income or expense; infer the type from context. Unclear expense category: "
        "Doprava, Jídlo, Zábava, else Ostatní.",
        {
            "amount": {"type": "number", "description": "CZK, positive"},
            "category": _STR,
            "transaction_type": {"type": "string", "enum": ["income", "expense"]},
            "description": _STR,
        },
        ["amount", "category", "transaction_type"],
        func=add_finance_transaction, areas=[AREA_FINANCE],
    ),
    _write(
        "add_school_subject",
        "Add a school subject.",
        {
            "name": _STR,
            "code": _STR,
            "semester": {"type": "string", "description": "e.g. ZS 2026/2027"},
            "credits": {"type": "integer", "description": "ECTS"},
            "active": _BOOL,
        },
        ["name"],
        func=add_school_subject, areas=[AREA_SCHOOL],
    ),
    _write(
        "add_school_assignment",
        "Add a school assignment (homework, project). Get subject_id from get_school_subjects.",
        {
            "title": _STR,
            "subject_id": _INT,
            "description": _STR,
            "due_date": _DATE,
            "priority": _PRIORITY,
            "status": {"type": "string", "enum": ["todo", "in_progress", "done", "overdue"]},
        },
        ["title", "subject_id"],
        func=add_school_assignment, areas=[AREA_SCHOOL], requires=["get_school_subjects"],
    ),
    _write(
        "add_school_exam",
        "Add an exam (zkouška, písemka, zápočet). Get subject_id from get_school_subjects.",
        {
            "title": _STR,
            "subject_id": _INT,
            "exam_type": {
                "type": "string",
                "enum": ["exam", "test", "quiz", "paper", "other"],
                "description": "exam=zkouška, test=písemka, paper=zápočet",
            },
            "exam_date": _DATE,
            "status": {"type": "string", "enum": ["upcoming", "passed", "failed", "scheduled"]},
            "notes": _STR,
        },
        ["title", "subject_id"],
        func=add_school_exam, areas=[AREA_SCHOOL], requires=["get_school_subjects"],
    ),
    _write(
        "update_wot_resource",
        "Set the current amount of a WoT resource.",
        {"resource": {"type": "string", "enum": ["credits", "gold", "bonds", "free_xp"]}, "amount": _NUM},
        ["resource", "amount"],
        func=update_wot_resource, areas=[AREA_WOT],
    ),
    _write(
        "upsert_wot_grind",
        "Create or update a WoT tank grind by tank name.",
        {
            "tank": _STR,
            "xp_remaining": _NUM,
            "priority": _PRIORITY,
            "status": {"type": "string", "enum": ["active", "paused", "completed", "planned"]},
        },
        ["tank", "xp_remaining"],
        func=upsert_wot_grind, areas=[AREA_WOT],
    ),
    _write(
        "upsert_mff_character",
        "Create or update an MFF character by unique name. Legacy (avoid): role, team, uru_state. "
        "build_completeness is auto-computed (ignored).",
        {
            "name": _STR,
            "tier": {"type": "string", "enum": ["T1", "T2", "T3", "T4"]},
            "level": _INT,
            "uniform": _STR,
            "ctp": _STR,
            "artifact": _STR,
            "role": _STR,
            "roles": {
                "type": "array",
                "items": {"type": "string", "enum": ["ABX", "ABL", "GBR", "World Boss", "PvP", "Dispatch", "Other"]},
            },
            "team": _STR,
            "team_supports": _STR,
            "uru_state": _STR,
            "uru_slots_total": _INT,
            "uru_slots_filled": _INT,
            "odin_blessings_count": _INT,
            "iso8_set": _STR,
            "build_completeness": _INT,
            "priority": _PRIORITY,
            "status": {"type": "string", "enum": ["built", "building", "planned", "inactive"]},
            "notes": _STR,
        },
        ["name"],
        func=upsert_mff_character, areas=[AREA_MFF],
    ),
    _write(
        "upsert_goal",
        "Create a goal, or update the goal with the given id.",
        {
            "area": {
                "type": "string",
                "enum": ["finance", "school", "work", "wot", "mff", "personal", "travel", "fitness", "hobby"],
            },
            "title": _STR,
            "id": _INT,
            "description": _STR,
            "status": {"type": "string", "enum": ["active", "in_progress", "completed", "paused", "cancelled"]},
            "priority": _PRIORITY,
            "progress": {"type": "integer", "description": "0-100"},
            "target_date": _DATE,
        },
        ["area", "title"],
        func=upsert_goal, areas=[AREA_GOALS], requires=["get_goals"],
    ),
    _write(
        "save_memory",
        "Save a long-term memory the user explicitly asked to remember (see MEMORY rules).",
        {
            "area": _MEMORY_AREA,
            "category": _MEMORY_CATEGORY,
            "content": {"type": "string", "description": "1-3 clear sentences"},
            "importance": {"type": "integer", "description": "1-10, default 5"},
            "active": _BOOL,
        },
        ["content"],
        func=save_memory, areas=[AREA_MEMORY],
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}
READ_SPECS: tuple[ToolSpec, ...] = tuple(s for s in TOOL_SPECS if not s.is_write)
WRITE_SPECS: tuple[ToolSpec, ...] = tuple(s for s in TOOL_SPECS if s.is_write)
ALL_AREAS: frozenset[str] = frozenset(a for s in TOOL_SPECS for a in s.areas)


def schemas(names) -> list[dict]:
    """Schémata pro dané názvy v pořadí registru (stabilní pořadí = stabilní prompt)."""
    wanted = set(names)
    return [s.schema for s in TOOL_SPECS if s.name in wanted]


def _validate() -> None:
    if len(TOOLS_BY_NAME) != len(TOOL_SPECS):
        raise RuntimeError("tool_registry: duplicitní název toolu")
    for spec in TOOL_SPECS:
        if spec.kind not in (READ, WRITE) or spec.schema["function"]["name"] != spec.name:
            raise RuntimeError(f"tool_registry: nekonzistentní spec {spec.name}")
        missing = [r for r in spec.requires if r not in TOOLS_BY_NAME or TOOLS_BY_NAME[r].is_write]
        if missing:
            raise RuntimeError(f"tool_registry: {spec.name} vyžaduje neznámé/zápisové tooly {missing}")


_validate()
