import json
import os
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI
from sqlalchemy import update as _sql_update

from tools import get_wot_resources, get_wot_grinds
from tools import get_finance_summary, get_finance_transactions
from tools import get_school_subjects, get_school_assignments, get_school_exams
from tools import get_work_summary, get_work_sessions
from tools import get_mff_summary, get_mff_characters
from tools import get_goals_summary, get_goals
from tools import get_memories
from tools import get_notifications, get_notification_summary, get_goal_progress_history
from tools import add_work_session, add_finance_transaction
from tools import add_school_subject, add_school_assignment, add_school_exam
from tools import update_wot_resource, upsert_wot_grind
from tools import upsert_mff_character, upsert_goal
from tools import save_memory
from activity_service import log_activity, delta_dict
from database import SessionLocal
from models import PendingAction
from time_utils import now_local
from llm_budget import estimate_fixed_overhead
from llm_config import LLM_SETTINGS

load_dotenv()

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url=LLM_SETTINGS.groq_base_url,
)


SYSTEM_PROMPT = """
You are the AI assistant inside Standa Hub, a personal dashboard for: finances, work sessions, school (subjects, assignments, exams), personal goals, World of Tanks (WoT), Marvel Future Fight (MFF) and long-term user memory.

TOOLS
- READ tools (get_*): call freely, they never change data.
- WRITE tools (add_*, update_*, upsert_*, save_memory): they only PREPARE a change; the system returns confirmation_required and the user must confirm it in the UI.
- Call only the tools a request needs. Do not repeat a call with the same arguments in one request unless the user wants fresh data, it failed, or a result requires it. Greetings / chit-chat: no tools.
- Tool results are authoritative for current data.

WRITE SAFETY
- Every write goes through confirmation. Never bypass it.
- Never say "uložil jsem", "změnil jsem", "přidal jsem" or otherwise imply a change happened before confirmation succeeded. After confirmation_required say e.g. "Připravil jsem změnu k potvrzení."
- Use exact argument names. Never guess a missing value that would materially change the record; ask instead.
- Relative dates ("dnes", "zítra", "včera", weekdays) are computed from CURRENT APPLICATION DATE below. Dates are YYYY-MM-DD.

DATA RULES
- Never invent data: game mechanics, currencies, rates, rewards, prices, events, features, deadlines, exam dates, XP, money, hours or goal progress. If information is missing, say so; if current external data would be needed, say it must be checked.
- Numbers: use exact tool values and calculate from them; no estimates unless stated as such.
- Be concise and practical; no generic or unrelated advice.
- Keep conversation context; understand follow-ups ("Jsi si jistý?"). For verification reuse a still-valid result or re-read when fresh data helps.
- Never expose internals: tool-call IDs, raw JSON, hidden arguments, execution metadata (tool names only when useful). Present results as normal Czech text, lists or short tables.

MEMORY
- Memory = long-term context only: preferences, plans, decisions, routines, constraints.
- Memory is NOT authoritative for volatile data (balances, transaction totals, XP, work hours, earnings, deadlines, exam dates, goal progress, WoT resources, MFF state) - always use the module READ tool. If memory conflicts with module data, module data wins.
- Call save_memory only when the user explicitly wants something remembered ("pamatuj si", "zapamatuj si", "ulož si", "do budoucna chci...") and it is long-term. Never save temporary numbers.

PLANNER (what to do today/this week, priorities, focus, stagnating goals, time split)
- Read-only: call get_goals, then get_memories, then only the module tools needed for the relevant areas.
- Priority order: overdue obligations > hard deadlines within 14 days > exams within 14 days > finance constraints / lagging monthly targets > work commitments / lagging hour targets > high-priority goals under 50 % > medium > low > routine tasks.
- Up to 5 actions (3-5 when data supports it, only 1-2 if that is all the data supports). Never invent tasks to fill the plan.
- Each action: specific, actionable now, based on tool data or memory (bad: "Více se učit."; good: "Projít kapitolu 3 z práva před pátečním testem."). No generic filler ("hraj efektivně", "šetři peníze") unless directly supported.
- WoT/MFF progression: stored data + memories, no speculative mechanics.
- The planner never creates or modifies anything by itself; saving an action needs the WRITE tool and confirmation.
- Output: 1-2 short Czech sentences, then exactly one ```json fenced block, no other JSON, never mention the schema:
  {"summary": "...", "actions": [{"priority": 1, "area": "school", "title": "...", "reason": "..."}]}
  area is one of: school, work, finance, wot, mff, personal, fitness, hobby, travel, general. priority starts at 1 and increases by 1. title 5-15 words (max 30), reason max 40 words.

AFFORDABILITY: get current resources, compare with the cost, state the exact surplus or shortfall and give a direct recommendation. Do not invent ways to get the missing amount.

LANGUAGE: the user writes Czech; reply in Czech unless the user switches language.
"""

_CZECH_WEEKDAYS = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")


def build_system_prompt(now: datetime | None = None) -> str:
    """SYSTEM_PROMPT + skutečné pražské datum/čas, aby „dnes/zítra/včera" neodhadoval model."""
    local = now if now is not None else now_local()
    weekday = _CZECH_WEEKDAYS[local.weekday()]
    return (
        f"{SYSTEM_PROMPT}\n"
        "================================================================================\n"
        "CURRENT APPLICATION DATE AND TIME (Europe/Prague)\n\n"
        f"CURRENT APPLICATION DATE: {local.date().isoformat()} ({weekday})\n"
        f"Current local time: {local:%H:%M} {local.tzname()}\n"
        "Use this date for 'dnes', 'zítra', 'včera' and every other relative date.\n"
    )


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


READ_TOOLS = [
    _tool("get_wot_resources", "WoT resources: credits, gold, bonds, free XP."),
    _tool("get_wot_grinds", "WoT tank grinds: XP remaining, priority, status."),
    _tool("get_finance_summary", "Finance totals: income, expenses, balance, transaction count."),
    _tool("get_finance_transactions", "All finance transactions, newest first."),
    _tool("get_school_subjects", "School subjects with IDs (source of subject_id)."),
    _tool("get_school_assignments", "School assignments: due date, priority, status, subject."),
    _tool("get_school_exams", "School exams: date, status, subject."),
    _tool("get_work_summary", "Work hours and earnings: total and current month."),
    _tool("get_work_sessions", "Work sessions with earnings, newest first."),
    _tool("get_mff_summary", "MFF summary: character counts by tier and priority."),
    _tool("get_mff_characters", "MFF tracked characters with build details."),
    _tool("get_goals_summary", "Goal counts by status."),
    _tool("get_goals", "Goals: area, status, priority, progress, target date."),
    _tool(
        "get_memories",
        "Long-term user memories. Never a source of numbers or dates.",
        {"area": _MEMORY_AREA, "category": _MEMORY_CATEGORY},
    ),
    _tool(
        "get_notifications",
        "Notifications, optionally filtered.",
        {
            "unread_only": _BOOL,
            "severity": {"type": "string", "enum": ["info", "warning", "important"]},
            "area": _STR,
            "include_resolved": _BOOL,
        },
    ),
    _tool("get_notification_summary", "Notification counters by severity and unread."),
    _tool("get_goal_progress_history", "Progress snapshots of one goal.", {"goal_id": _INT}, ["goal_id"]),
]


WRITE_TOOLS = [
    _tool(
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
    ),
    _tool(
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
    ),
    _tool(
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
    ),
    _tool(
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
    ),
    _tool(
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
    ),
    _tool(
        "update_wot_resource",
        "Set the current amount of a WoT resource.",
        {"resource": {"type": "string", "enum": ["credits", "gold", "bonds", "free_xp"]}, "amount": _NUM},
        ["resource", "amount"],
    ),
    _tool(
        "upsert_wot_grind",
        "Create or update a WoT tank grind by tank name.",
        {
            "tank": _STR,
            "xp_remaining": _NUM,
            "priority": _PRIORITY,
            "status": {"type": "string", "enum": ["active", "paused", "completed", "planned"]},
        },
        ["tank", "xp_remaining"],
    ),
    _tool(
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
    ),
    _tool(
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
    ),
    _tool(
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
    ),
]


TOOLS = READ_TOOLS + WRITE_TOOLS


READ_TOOL_FUNCTIONS = {
    "get_wot_resources": get_wot_resources,
    "get_wot_grinds": get_wot_grinds,
    "get_finance_summary": get_finance_summary,
    "get_finance_transactions": get_finance_transactions,
    "get_school_subjects": get_school_subjects,
    "get_school_assignments": get_school_assignments,
    "get_school_exams": get_school_exams,
    "get_work_summary": get_work_summary,
    "get_work_sessions": get_work_sessions,
    "get_mff_summary": get_mff_summary,
    "get_mff_characters": get_mff_characters,
    "get_goals_summary": get_goals_summary,
    "get_goals": get_goals,
    "get_memories": get_memories,
    "get_notifications": get_notifications,
    "get_notification_summary": get_notification_summary,
    "get_goal_progress_history": get_goal_progress_history,
}


WRITE_TOOL_FUNCTIONS = {
    "add_work_session": add_work_session,
    "add_finance_transaction": add_finance_transaction,
    "add_school_subject": add_school_subject,
    "add_school_assignment": add_school_assignment,
    "add_school_exam": add_school_exam,
    "update_wot_resource": update_wot_resource,
    "upsert_wot_grind": upsert_wot_grind,
    "upsert_mff_character": upsert_mff_character,
    "upsert_goal": upsert_goal,
    "save_memory": save_memory,
}


TOOL_FUNCTIONS = {**READ_TOOL_FUNCTIONS, **WRITE_TOOL_FUNCTIONS}


WRITE_TOOL_NAMES = set(WRITE_TOOL_FUNCTIONS.keys())


def _store_pending_action(db, tool: str, arguments: dict, *, ttl_minutes: int = 10) -> str:
    created = datetime.utcnow()
    expires = created + timedelta(minutes=ttl_minutes)
    pa = PendingAction(
        tool=tool,
        arguments=json.dumps(arguments, ensure_ascii=False),
        status="pending",
        created_at=created,
        expires_at=expires,
    )
    db.add(pa)
    db.flush()
    db.commit()
    return str(pa.id)


def _get_pending_action(db, pending_id: str) -> dict | None:
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        return None
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa is None:
        return None
    try:
        args = json.loads(pa.arguments) if pa.arguments else {}
    except Exception:
        args = {}
    return {
        "id": str(pa.id),
        "tool": pa.tool,
        "arguments": args,
        "status": pa.status,
        "created_at": pa.created_at,
        "expires_at": pa.expires_at,
    }


def _check_pending_expired(db) -> int:
    now = datetime.utcnow()
    stmt = (
        _sql_update(PendingAction)
        .where(PendingAction.status == "pending")
        .where(PendingAction.expires_at.is_not(None))
        .where(PendingAction.expires_at < now)
        .values(status="expired")
    )
    result = db.execute(stmt)
    affected = int(result.rowcount or 0)
    if affected:
        db.commit()
    return affected


def _confirm_pending_action_atomically(db, pending_id: str) -> dict | None:
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Pending action not found")
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    if pa.status != "pending":
        raise HTTPException(status_code=409, detail="Pending already processed")
    stmt = (
        _sql_update(PendingAction)
        .where(PendingAction.id == pid)
        .where(PendingAction.status == "pending")
        .values(status="executing")
    )
    result = db.execute(stmt)
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pending already processed")
    db.flush()
    db.refresh(pa)
    try:
        args = json.loads(pa.arguments) if pa.arguments else {}
    except Exception:
        args = {}
    return {
        "id": str(pa.id),
        "tool": pa.tool,
        "arguments": args,
        "status": pa.status,
        "created_at": pa.created_at,
        "expires_at": pa.expires_at,
    }


def _finalize_pending_status(db, pending_id: str, new_status: str):
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        return
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa:
        pa.status = new_status
        db.commit()


def reject_pending(db, pending_id: str):
    try:
        pid = int(pending_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Pending action not found")
    pa = db.query(PendingAction).filter(PendingAction.id == pid).first()
    if pa is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    if pa.status != "pending":
        raise HTTPException(status_code=409, detail="Pending already processed")
    pa.status = "rejected"
    db.commit()


def _message_to_dict(m):
    if isinstance(m, dict):
        return m
    return {"role": m.role, "content": m.content}


def _run_tool_calls(db, tool_calls):
    tool_messages = []
    pending_actions = []

    for tc in tool_calls:
        fn_name = tc.function.name
        print(f"[TOOL CALL] {fn_name}")

        try:
            arguments = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
            print(f"  [TOOL ERROR] invalid JSON args: {tc.function.arguments}")

        if fn_name in WRITE_TOOL_NAMES:
            action_id = _store_pending_action(db, fn_name, arguments, ttl_minutes=30)
            pending_info = _get_pending_action(db, action_id)
            expires_at_iso = (
                pending_info["expires_at"].isoformat()
                if pending_info and pending_info.get("expires_at")
                else None
            )
            pending_actions.append({
                "id": action_id,
                "tool": fn_name,
                "arguments": arguments,
                "expires_at": expires_at_iso,
            })

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({
                    "status": "confirmation_required",
                    "id": action_id,
                    "tool": fn_name,
                    "arguments": arguments,
                    "expires_at": expires_at_iso,
                }, ensure_ascii=False),
            })

            continue

        function = READ_TOOL_FUNCTIONS.get(fn_name)

        if function is None:
            result = {
                "error": "unknown_tool",
                "detail": f"Unknown tool: {fn_name}",
            }
        else:
            try:
                result = function(**arguments)
            except Exception as exc:
                result = {
                    "error": "tool_execution_failed",
                    "detail": str(exc),
                }

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False, default=str),
        })

    return tool_messages, pending_actions


def _llm_create_with_retry(
    api_messages: list[dict],
    tools,
    tool_choice: str = "auto",
    temperature: float = 0.2,
    max_retries: int = 2,
):
    """Create chat completion with automatic retry on Groq rate limits (429).

    Groq free tier enforces 8 000 TPM. A Planner request with many read
    tools often triggers 429; the server usually suggests retrying after
    200-2000 ms, so we use a conservative 2.5 s backoff and one retry.
    Other API errors are re-raised as descriptive RuntimeError.
    """
    import openai as _openai

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=LLM_SETTINGS.groq_model,
                messages=api_messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
            )
        except _openai.RateLimitError as exc:
            last_exc = exc
            wait_s = 2.5
            try:
                body = getattr(exc, "response", None)
                if body is not None:
                    try:
                        data = body.json()
                        msg = (data or {}).get("error", {}).get("message", "")
                        m = __import__("re").search(
                            r"Please try again in ([0-9.]+)ms", msg
                        )
                        if m:
                            wait_s = max(0.5, min(5.0, float(m.group(1)) / 1000.0 + 0.3))
                    except Exception:
                        pass
            except Exception:
                pass
            if attempt < max_retries - 1:
                time.sleep(wait_s)
                continue
            raise RuntimeError(
                "AI provider nedisponuje (Rate limit 8 000 tokenů/minutu byl překročen). "
                "Zkus to prosím za 10-20 sekund znovu, nebo zjednoduš otázku."
            ) from last_exc
        except _openai.APIError as exc:
            last_exc = exc
            if attempt < max_retries - 1 and getattr(exc, "status_code", 500) >= 500:
                time.sleep(1.5)
                continue
            raise RuntimeError(
                f"AI provider vrátil chybu ({getattr(exc, 'status_code', '?')}). "
                f"Zkus to prosím později znovu."
            ) from last_exc
        except Exception as exc:
            last_exc = exc
            raise RuntimeError(
                f"Při volání AI došlo k chybě: {exc}"
            ) from last_exc
    raise RuntimeError("AI volání selhalo po několika pokusech.") from last_exc


def _warn_if_fixed_overhead_exceeds_budget(system_prompt: str) -> None:
    overhead = estimate_fixed_overhead(system_prompt, TOOLS)
    if overhead.total > LLM_SETTINGS.max_fixed_tokens:
        print(
            f"[ai] WARNING fixní režie ~{overhead.total} tokenů (prompt {overhead.prompt_tokens} + "
            f"{overhead.tool_count} tool schémat {overhead.tool_tokens}) překračuje "
            f"AI_MAX_FIXED_TOKENS={LLM_SETTINGS.max_fixed_tokens}"
        )


def ask_ai(messages):
    db = SessionLocal()
    try:
        _check_pending_expired(db)

        system_prompt = build_system_prompt()
        _warn_if_fixed_overhead_exceeds_budget(system_prompt)
        api_messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ]

        for message in messages:
            api_messages.append(_message_to_dict(message))

        all_pending_actions = []
        MAX_TOOL_ROUNDS = 10

        for _ in range(MAX_TOOL_ROUNDS):
            response = _llm_create_with_retry(
                api_messages=api_messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_retries=2,
            )

            choice = response.choices[0]
            assistant_msg = choice.message

            if not assistant_msg.tool_calls:
                return {
                    "answer": assistant_msg.content or "",
                    "pending_actions": all_pending_actions,
                }

            api_messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ],
            })

            tool_messages, pending_actions = _run_tool_calls(db, assistant_msg.tool_calls)
            all_pending_actions.extend(pending_actions)
            api_messages.extend(tool_messages)

        return {
            "answer": (
                "Nepodařilo se dokončit požadavek během několika pokusů. "
                "Zkus prosím otázku zjednodušit, nebo požádej o menší rozsah informací."
            ),
            "pending_actions": all_pending_actions,
        }
    finally:
        db.close()


def execute_confirm_action(action_id: str):
    """Actually execute a previously-confirmed WRITE tool call using its stored action_id."""
    db = SessionLocal()
    try:
        _check_pending_expired(db)

        try:
            stored = _confirm_pending_action_atomically(db, action_id)
        except HTTPException as he:
            try:
                log_activity(
                    db, "system", "error",
                    f"Potvrzení akce selhalo: action_id {action_id} - {he.detail}",
                    entity_type="PendingAction",
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass
            if he.status_code == 409:
                return {
                    "ok": False,
                    "error": "action_already_processed",
                    "detail": (
                        "Akce byla už potvrzena, zamítnuta nebo vypršela. "
                        "Zopakujte prosím dotaz v chatu."
                    ),
                }
            return {
                "ok": False,
                "error": "action_not_found_or_expired",
                "detail": (
                    "Akce neexistuje, byla už potvrzena nebo vypršela "
                    "(časový limit 30 min). "
                    "Zopakujte prosím dotaz v chatu."
                ),
            }

        tool_name = stored.get("tool")
        arguments = stored.get("arguments") or {}

        if tool_name not in WRITE_TOOL_FUNCTIONS:
            _finalize_pending_status(db, action_id, "failed")
            try:
                log_activity(
                    db, "system", "error",
                    f"Neznámý write tool: {tool_name}",
                    entity_type="ToolRegistry",
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "error": "unknown_write_tool",
                "detail": f"Tool '{tool_name}' is not a known write tool requiring confirmation.",
            }

        fn = WRITE_TOOL_FUNCTIONS[tool_name]
        try:
            fn_args = dict(arguments)
            fn_args["user_context"] = "ai_confirm"
            try:
                import inspect
                sig = inspect.signature(fn)
                if "user_context" not in sig.parameters:
                    fn_args = dict(arguments)
            except Exception:
                fn_args = dict(arguments)
            result = fn(**fn_args)

            _finalize_pending_status(db, action_id, "executed")

            try:
                args_preview = ", ".join(f"{k}={v}" for k, v in list(arguments.items())[:3])
                if len(arguments) > 3:
                    args_preview += ", ..."
                summary = f"Potvrzena akce {tool_name} ({args_preview})"
                log_activity(
                    db, "ai", "approve", summary,
                    entity_type=tool_name,
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass

            return {
                "ok": True,
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
            }
        except Exception as exc:
            _finalize_pending_status(db, action_id, "failed")
            try:
                log_activity(
                    db, "ai", "reject",
                    f"Chyba při {tool_name}: {type(exc).__name__}: {str(exc)[:120]}",
                    entity_type=tool_name,
                    entity_id=abs(hash(action_id)) % (10**8),
                    user_context="ai_confirm"
                )
                db.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "error": "execution_failed",
                "tool": tool_name,
                "arguments": arguments,
                "detail": str(exc),
            }
    finally:
        db.close()
