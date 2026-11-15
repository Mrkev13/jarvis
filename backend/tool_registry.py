"""Registr AI toolů – jediný zdroj pravdy (Roadmap 3.0 A5).

Každý tool má na jednom místě: jméno, druh (read/write), oblasti (pro routing), JSON schéma pro LLM,
volanou funkci, zda jeho data plně nese CURRENT STATE (covered_by_context) a které tooly potřebuje
mít k dispozici (requires – např. subject_id z get_school_subjects).

ai.py z registru odvozuje TOOLS / READ_TOOLS / WRITE_TOOLS / *_TOOL_FUNCTIONS; tool_router.py z něj
vybírá menší sadu toolů pro konkrétní dotaz.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Callable

from tools import get_wot_resources, get_wot_grinds
from tools import get_school_subjects
from tools import get_work_summary
from tools import get_mff_summary, get_mff_characters
from tools import get_goals_summary
from tools import get_memories
from tools import get_notifications, get_notification_summary, get_goal_progress_history
from tools import add_work_session, add_finance_transaction
from tools import add_school_subject, add_school_assignment, add_school_exam
from tools import update_wot_resource, upsert_wot_grind
from tools import upsert_mff_character
from goal_ai_tool import prepare_upsert_goal, run_upsert_goal
from tools import save_memory
from mutation_service import (
    ENTITIES as MUTATION_ENTITIES,
    UNDO_AREAS,
    execute_modify_records,
    execute_undo,
    propose_modify_records,
    propose_undo,
)
from reminder_actions import (
    execute_add_reminder,
    execute_manage_reminder,
    propose_add_reminder,
    propose_manage_reminder,
    query_reminders,
)
from finance_ai_policy import is_finance_goal, is_finance_notification
from models import Goal
from modules.school.reading import ReadingError, find_materials, read_material
from read_queries import (
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
AREA_REMINDERS = "reminders"
AREA_SCHOOL_MATERIALS = "school_materials"  # MRK-44: context area of the School module (study materials)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: str  # READ / WRITE
    areas: tuple[str, ...]
    schema: dict
    func: Callable
    # Souhrn, který CURRENT STATE sekce oblasti nahrazuje: router ho nepošle, když kontext oblast pokryl
    # a uživatel se na oblast výslovně neptá (jen implikovaná oblast, např. práce u plánování týdne).
    covered_by_context: bool = False
    requires: tuple[str, ...] = ()  # tooly, bez kterých tento nejde smysluplně použít
    takes_db: bool = False  # funkce dostane db session AI requestu jako první argument
    explicit_only: bool = False  # detailní tool: jen při výslovně zmíněné oblasti (nebo jako requires)
    # Phase B: write tool s resolverem – při návrhu resolver(db, **args) najde cíle a vrátí plán, který se
    # uloží jako pending akce {"plan": ...}; func pak po potvrzení provede právě ten plán.
    resolver: Callable | None = None
    # "create" (nový záznam / nastavení), "mutate" (úprava/mazání/dokončení), "undo" (vrácení provedené změny)
    write_intent: str = "create"

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


def _read(name, description, properties=None, required=None, *, func, areas, covered=False, requires=(),
          takes_db=False, explicit_only=False):
    return ToolSpec(name, READ, tuple(areas), _tool(name, description, properties, required), func,
                    covered, tuple(requires), takes_db, explicit_only)


def _write(name, description, properties=None, required=None, *, func, areas, requires=(), resolver=None,
           write_intent="create"):
    return ToolSpec(name, WRITE, tuple(areas), _tool(name, description, properties, required), func,
                    False, tuple(requires), resolver=resolver, write_intent=write_intent)


def _study_material_tool(func):
    """MRK-44: read tools route by area but are not re-checked against the route when called, so the School gate is
    enforced here too (disabled module → no data). Errors are allowlisted categories, never exception text."""
    @functools.wraps(func)
    def run(db, **arguments):
        from module_registry import current_access  # lazy: the registry imports module providers
        if not current_access().allows_context_area(AREA_SCHOOL_MATERIALS):
            return {"error": "module_unavailable"}
        try:
            return func(db, **arguments)
        except ReadingError as exc:
            return {"error": exc.category}
    return run


def _find_study_materials(db, query: str | None = None, subject_id: int | None = None):
    return find_materials(db, query=query, subject_id=subject_id)


def _read_study_material(db, material_id: int, query: str | None = None):
    return read_material(db, material_id, query=query)


# MRK-60: notifikace a historie cílů, které nesou Finance data, AI nedostane (finance_ai_policy.py).
def _ai_notifications(unread_only: bool = False, severity: str | None = None, area: str | None = None,
                      include_resolved: bool = False):
    rows = get_notifications(unread_only=unread_only, severity=severity, area=area, include_resolved=include_resolved)
    return [n for n in rows if not is_finance_notification(n.get("area"), n.get("notification_type"))]


def _ai_goal_progress_history(db, goal_id: int):
    goal = db.get(Goal, goal_id)
    if goal is not None and is_finance_goal(goal.source):
        return {"error": "not_available", "detail": "Finance data are not available to the assistant."}
    return get_goal_progress_history(goal_id)


TOOL_SPECS: tuple[ToolSpec, ...] = (
    # ===== READ =====
    _read("get_wot_resources", "WoT resources: credits, gold, bonds, free XP.",
          func=get_wot_resources, areas=[AREA_WOT], covered=True),
    _read("get_wot_grinds", "WoT tank grinds: XP remaining, priority, status.",
          func=get_wot_grinds, areas=[AREA_WOT]),
    _read("get_school_subjects", "School subjects with IDs (source of subject_id).",
          func=get_school_subjects, areas=[AREA_SCHOOL], explicit_only=True),
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
    # MRK-44: study materials (Moodle) – ids/metadata, then bounded excerpts of ONE material; never whole documents
    _read(
        "get_study_materials",
        "Study files (Moodle): ids by topic or subject, no text.",
        {"query": _STR, "subject_id": _INT},
        func=_study_material_tool(_find_study_materials), areas=[AREA_SCHOOL_MATERIALS], takes_db=True,
    ),
    _read(
        "get_study_material_text",
        "Bounded excerpts of one study file; query = find relevant parts.",
        {"material_id": _INT, "query": _STR},
        ["material_id"],
        func=_study_material_tool(_read_study_material), areas=[AREA_SCHOOL_MATERIALS], takes_db=True,
        requires=("get_study_materials",),
    ),
    _read("get_work_summary", "Work hours and earnings: total and current month.",
          func=get_work_summary, areas=[AREA_WORK], covered=True),
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
          func=get_goals_summary, areas=[AREA_GOALS], covered=True),
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
        func=_ai_notifications, areas=[AREA_NOTIFICATIONS],
    ),
    _read("get_notification_summary", "Notification counters by severity and unread.",
          func=get_notification_summary, areas=[AREA_NOTIFICATIONS], covered=True),
    _read("get_goal_progress_history", "Progress snapshots of one goal.", {"goal_id": _INT}, ["goal_id"],
          func=_ai_goal_progress_history, areas=[AREA_GOALS], requires=["get_goals"], explicit_only=True,
          takes_db=True),
    _read(
        "get_recent_activity",
        "Recent app changes (activity log), newest first.",
        {"limit": _LIMIT, "area": _STR, "days": {"type": "integer", "description": "default 7"}},
        func=query_recent_activity, areas=[AREA_ACTIVITY], takes_db=True,
    ),
    _read(
        "get_reminders",
        "User reminders with Europe/Prague times (due first).",
        {"status": {"type": "string", "enum": ["active", "all", "done", "cancelled"]}, "limit": _LIMIT},
        func=query_reminders, areas=[AREA_REMINDERS], takes_db=True, covered=True,
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
        "Create a goal, or edit the goal with the given id: only the fields you pass change (area stays).",
        {
            "area": {
                "type": "string",
                "enum": ["school", "work", "wot", "mff", "personal", "travel", "fitness", "hobby"],
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
        func=run_upsert_goal, resolver=prepare_upsert_goal, areas=[AREA_GOALS], requires=["get_goals"],
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
    _write(
        "modify_records",
        "Prepare an edit, deletion or completion of EXISTING records. The server finds them from target and "
        "shows the user a preview to confirm.",
        {
            "entity": {"type": "string", "enum": sorted(MUTATION_ENTITIES)},
            "action": {"type": "string", "enum": ["update", "delete", "complete"]},
            "target": {
                "type": "object",
                "description": "which record(s); id only from tool results",
                "properties": {
                    "id": _INT,
                    "text": {"type": "string", "description": "words from title/description/category/subject"},
                    "type": {"type": "string", "description": "exam type, assignment status, area"},
                    "date": _DATE,
                    "date_from": _DATE,
                    "date_to": _DATE,
                    "latest": {"type": "boolean", "description": "newest match, only if the user said so"},
                    "all_matching": _BOOL,
                },
                "additionalProperties": False,
            },
            "changes": {
                "type": "object",
                "description": "update only. work: date,hours,project,hourly_rate,description; assignment: title,description,due_date,"
                               "priority,status; exam: title,exam_type,exam_date,status,notes; goal: title,"
                               "description,status,priority,progress,target_date; wot_grind: xp_remaining,priority,"
                               "status; memory: content,importance,category,area",
            },
        },
        ["entity", "action", "target"],
        func=execute_modify_records, resolver=propose_modify_records, write_intent="mutate",
        areas=[AREA_WORK, AREA_SCHOOL, AREA_GOALS, AREA_WOT, AREA_MEMORY],
    ),
    _write(
        "add_reminder",
        "Prepare a new reminder (user confirms).",
        {
            "title": _STR,
            "due_local": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
            "in_minutes": _NUM,
            "recurrence": {"type": "string", "enum": ["none", "daily", "weekly"]},
            "weekdays": {"type": "string", "description": "0=Mon … 6=Sun"},
            "time_local": {"type": "string", "description": "HH:MM"},
            "note": _STR,
        },
        ["title"],
        func=execute_add_reminder, resolver=propose_add_reminder, areas=[AREA_REMINDERS],
    ),
    _write(
        "manage_reminder",
        "Prepare edit/snooze/complete/cancel of a reminder (user confirms).",
        {
            "action": {"type": "string", "enum": ["update", "snooze", "complete", "cancel"]},
            "target": {
                "type": "object",
                "description": "id only from tool results",
                "properties": {"id": _INT, "text": _STR, "date": _DATE, "latest": _BOOL},
                "additionalProperties": False,
            },
            "title": _STR,
            "due_local": _STR,
            "shift_minutes": {"type": "number", "description": "'o hodinu' = 60"},
            "snooze_minutes": _NUM,
            "snooze_until_local": _STR,
            "recurrence": {"type": "string", "enum": ["none", "daily", "weekly"]},
            "weekdays": _STR,
            "time_local": _STR,
        },
        ["action", "target"],
        func=execute_manage_reminder, resolver=propose_manage_reminder, write_intent="mutate",
        areas=[AREA_REMINDERS],
    ),
    _write(
        "undo_change",
        "Prepare undoing a recently confirmed edit/delete/completion from stored data (user confirms).",
        {
            "area": {"type": "string", "enum": list(UNDO_AREAS)},
            "action_id": {"type": "string", "description": "only from undo_change candidates"},
            "latest": {"type": "boolean", "description": "most recent, only if the user said so"},
        },
        func=execute_undo, resolver=propose_undo, write_intent="undo",
        areas=[AREA_WORK, AREA_SCHOOL, AREA_GOALS, AREA_WOT, AREA_MEMORY],
    ),
)

# MRK-60: WRITE tooly jen pro ruční zdroje (Rychlé přidání). Model je nevidí (nejsou v TOOL_SPECS → ani ve schématech,
# routeru a TOOLS_BY_NAME) a potvrzení je pustí jen u pending akce s ručním zdrojem (ai.execute_confirm_action).
MANUAL_ONLY_SPECS: tuple[ToolSpec, ...] = (
    _write("add_finance_transaction", "Add an income or expense (manual Quick Add only).",
           func=add_finance_transaction, areas=[AREA_FINANCE]),
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
    if any(spec.name in TOOLS_BY_NAME or not spec.is_write for spec in MANUAL_ONLY_SPECS):
        raise RuntimeError("tool_registry: ruční tool musí být WRITE a mimo AI registr")
    for spec in TOOL_SPECS:
        if spec.kind not in (READ, WRITE) or spec.schema["function"]["name"] != spec.name:
            raise RuntimeError(f"tool_registry: nekonzistentní spec {spec.name}")
        if spec.write_intent not in ("create", "mutate", "undo") or (spec.resolver is not None and not spec.is_write):
            raise RuntimeError(f"tool_registry: neplatný write_intent/resolver u {spec.name}")
        missing = [r for r in spec.requires if r not in TOOLS_BY_NAME or TOOLS_BY_NAME[r].is_write]
        if missing:
            raise RuntimeError(f"tool_registry: {spec.name} vyžaduje neznámé/zápisové tooly {missing}")


_validate()
