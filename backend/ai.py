import json
import zlib
import os
import time
import types
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI
from sqlalchemy import update as _sql_update

from tool_registry import READ_SPECS, TOOL_SPECS, TOOLS_BY_NAME, WRITE_SPECS
from activity_service import log_activity
from database import SessionLocal
from models import PendingAction
from time_utils import now_local
from text_utils import WEEKDAYS_CZ, ai_action_label, ai_action_summary
from context_service import CurrentContext, build_current_context
from llm_budget import estimate_fixed_overhead, estimate_tool_schema_tokens
from llm_config import LLM_SETTINGS
from llm_usage import (
    LLMCallRecord,
    log_call,
    log_request_summary,
    log_retry,
    rate_limit_kind,
    ratelimit_remaining_tokens,
    retry_wait_seconds,
)
from mutation_service import MutationRefused
from tool_router import REASON_FALLBACK, ToolRoute, route_tools, widen_route
from planner_guard import (
    build_evidence,
    find_planner_block,
    ground_planner_answer,
    missing_planner_tools,
    planner_tools_nudge,
)

load_dotenv()

client = OpenAI(
    # Groq klíč: GROQ_API_KEY, jinak OPENAI_API_KEY (dosavadní chování – SDK fallback, nyní explicitně).
    api_key=os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY"),
    base_url=LLM_SETTINGS.groq_base_url,
    max_retries=LLM_SETTINGS.sdk_max_retries,
)


SYSTEM_PROMPT = """
You are the AI assistant inside Standa Hub, a personal dashboard: finances, work, school, goals, World of Tanks (WoT), Marvel Future Fight (MFF), long-term memory.

TOOLS
- READ tools (get_*) never change data. WRITE tools (add_*, update_*, upsert_*, save_memory, modify_records, undo_change, manage_reminder): they only PREPARE a change; the system returns confirmation_required and the user must confirm it in the UI.
- CURRENT STATE (system message) is live module data: if it answers the question, answer directly. Never re-fetch what it contains; call READ tools only for missing data, all needed ones in one turn. No identical repeated calls.
- Tool results are authoritative for current data, like CURRENT STATE. RELEVANT MEMORY is context only.

WRITE SAFETY
- Every write goes through confirmation. Never bypass it.
- Never say "uložil jsem", "změnil jsem", "přidal jsem" or otherwise imply a change happened before confirmation succeeded. After confirmation_required say e.g. "Připravil jsem změnu k potvrzení."
- Use exact argument names. Never guess a missing value that would materially change the record; ask instead.
- Relative dates ("dnes", "zítra", "včera", weekdays) are computed from CURRENT APPLICATION DATE below. Dates are YYYY-MM-DD.
- Reminders: add_reminder / manage_reminder, Europe/Prague times; "za X" → in_minutes, a time → due_local, repeats → recurrence + time_local.
- Edit/delete/complete existing records only via modify_records: describe the target from the user's words (latest only if they said "poslední"; all_matching only if they said all). Never guess ids. not_prepared (ambiguous_target, target_not_found…) → ask the user which record; never retry with guesses. Undo confirmed changes only via undo_change (latest only if they said "poslední"). An unconfirmed proposal is not a record: to cancel it the user presses Zrušit on its card.

DATA RULES
- Never invent data: game mechanics, currencies, rates, rewards, prices, events, features, deadlines, exam dates, XP, money, hours or goal progress. If information is missing, say so; if current external data would be needed, say it must be checked.
- Numbers: use exact tool values and calculate from them; no estimates unless stated as such.
- Be concise and practical; no generic or unrelated advice.
- Keep conversation context; understand follow-ups ("Jsi si jistý?"). For verification reuse a still-valid result or re-read when fresh data helps.
- Never expose internals: tool-call IDs, raw JSON, hidden arguments, execution metadata (tool names only when useful). Present results as normal Czech text, lists or short tables.

MEMORY
- Memory = long-term context only: preferences, plans, decisions, routines, constraints.
- Memory is NOT authoritative for volatile data (balances, totals, XP, work hours, earnings, deadlines, exam dates, goal progress, WoT/MFF state) - use CURRENT STATE or a READ tool. If memory conflicts with module data, module data wins.
- Call save_memory only when the user explicitly wants something remembered ("pamatuj si", "zapamatuj si", "ulož si", "do budoucna chci...") and it is long-term. Never save temporary numbers.

PLANNER (what to do today/this week, priorities, focus, stagnating goals, time split)
- Read-only. Goals and memories come from CURRENT STATE / RELEVANT MEMORY; only if missing call get_goals AND get_memories (together), then only tools for data still missing.
- Priority order: overdue obligations > hard deadlines within 14 days > exams within 14 days > finance constraints / lagging monthly targets > work commitments / lagging hour targets > high-priority goals under 50 % > medium > low > routine tasks.
- GROUNDING: project names, amounts, dates, deadlines and targets only if they appear in tool results or the current context. Missing value: omit it, never invent it. Up to 5 actions; fewer grounded actions beat speculative ones.
- Each action: specific, actionable now (bad: "Více se učit."). No generic filler ("šetři peníze") unless directly supported. WoT/MFF: no speculative mechanics.
- The planner never creates or modifies anything by itself; saving an action needs the WRITE tool and confirmation.
- Output: 1-2 short Czech sentences, then exactly one ```json fenced block, no other JSON, never mention the schema:
  {"summary": "...", "actions": [{"priority": 1, "area": "school", "title": "...", "reason": "..."}]}
  area is one of: school, work, finance, wot, mff, personal, fitness, hobby, travel, general. priority starts at 1 and increases by 1. title 5-15 words (max 30), reason max 40 words.

AFFORDABILITY: get current resources, compare with the cost, state the exact surplus or shortfall and give a direct recommendation. Do not invent ways to get the missing amount.

LANGUAGE: the user writes Czech; reply in Czech unless the user switches language.
"""

_CZECH_WEEKDAYS = WEEKDAYS_CZ


def current_date_block(now: datetime | None = None) -> str:
    """Aktuální pražské datum/čas pro model (součást „current context" pro planner grounding)."""
    local = now if now is not None else now_local()
    weekday = _CZECH_WEEKDAYS[local.weekday()]
    return (
        "================================================================================\n"
        "CURRENT APPLICATION DATE AND TIME (Europe/Prague)\n\n"
        f"CURRENT APPLICATION DATE: {local.date().isoformat()} ({weekday})\n"
        f"Current local time: {local:%H:%M} {local.tzname()}\n"
        "Use this date for 'dnes', 'zítra', 'včera' and every other relative date.\n"
    )


def build_system_prompt(now: datetime | None = None) -> str:
    """SYSTEM_PROMPT + skutečné pražské datum/čas, aby „dnes/zítra/včera" neodhadoval model."""
    return f"{SYSTEM_PROMPT}\n{current_date_block(now)}"


# Definice toolů (schéma, funkce, oblasti) žijí v tool_registry.py – jediný zdroj pravdy (A5).
READ_TOOLS = [s.schema for s in READ_SPECS]
WRITE_TOOLS = [s.schema for s in WRITE_SPECS]
TOOLS = [s.schema for s in TOOL_SPECS]

READ_TOOL_FUNCTIONS = {s.name: s.func for s in READ_SPECS}
WRITE_TOOL_FUNCTIONS = {s.name: s.func for s in WRITE_SPECS}
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


def _audit_entity_id(action_id) -> int:
    """Stabilní id pro audit: id PendingAction. (Dřív hash() – v Pythonu se mění s každým startem.)"""
    try:
        return int(action_id)
    except (TypeError, ValueError):
        return zlib.crc32(str(action_id).encode("utf-8")) % (10**8)


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
    # Claim se commitne hned (AGENTS.md §4.2): executor zapisuje ve vlastní session; kdyby proces spadl
    # uprostřed, zůstane „executing" a start ho označí jako failed – akce se nedá potvrdit podruhé.
    db.commit()
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


def _finalize_executed_with_undo(db, pending_id: str, undo_record: dict) -> None:
    pa = db.query(PendingAction).filter(PendingAction.id == int(pending_id)).first()
    if pa is None:
        return
    try:
        args = json.loads(pa.arguments) if pa.arguments else {}
    except json.JSONDecodeError:
        args = {}
    args["undo"] = undo_record
    pa.arguments = json.dumps(args, ensure_ascii=False, default=str)
    pa.status = "executed"
    db.commit()


def propose_undo_action(action_id: str) -> dict:
    """Tlačítko „Vrátit" v UI: z provedené akce udělá undo pending akci (stejné potvrzení jako ostatní)."""
    db = SessionLocal()
    try:
        _check_pending_expired(db)
        try:
            plan = TOOLS_BY_NAME["undo_change"].resolver(db, action_id=action_id)
        except MutationRefused as refused:
            return {"ok": False, "error": refused.code, "detail": refused.detail}
        stored = {"plan": plan}
        pending_id = _store_pending_action(db, "undo_change", stored, ttl_minutes=30)
        info = _get_pending_action(db, pending_id)
        return {
            "ok": True,
            "pending_action": {
                "id": pending_id,
                "tool": "undo_change",
                "arguments": stored,
                "preview": plan["preview"],
                "expires_at": info["expires_at"].isoformat() if info and info.get("expires_at") else None,
            },
        }
    finally:
        db.close()


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


# Zdroje pending akcí (kdo akci navrhl). Bez klíče = AI (dosavadní chování); Rychlé přidání (Roadmap 4E)
# ukládá `_source` do argumentů, executor ho před voláním toolu odebere a použije jako user_context.
PENDING_SOURCE_KEY = "_source"

QUICK_ADD_SOURCE = "quick_add"


def prepare_write_action(db, fn_name: str, arguments: dict, *, source: str | None = None) -> dict:
    """Z WRITE toolu udělá pending akci (jediná cesta pro AI i Rychlé přidání – nic se neprovede).

    Tool s resolverem (úpravy, připomínky, vrácení) dostane plán s náhledem ověřeným proti DB;
    MutationRefused / TypeError z resolveru se propouští volajícímu.
    """
    stored_arguments = arguments
    preview = None
    spec = TOOLS_BY_NAME.get(fn_name)
    if spec is not None and spec.resolver is not None:
        plan = spec.resolver(db, **arguments)
        stored_arguments = {"plan": plan}
        preview = plan.get("preview")
    if source:
        stored_arguments = {**stored_arguments, PENDING_SOURCE_KEY: source}
    action_id = _store_pending_action(db, fn_name, stored_arguments, ttl_minutes=30)
    pending_info = _get_pending_action(db, action_id)
    expires_at_iso = (
        pending_info["expires_at"].isoformat() if pending_info and pending_info.get("expires_at") else None
    )
    item = {"id": action_id, "tool": fn_name, "arguments": stored_arguments, "expires_at": expires_at_iso}
    if preview is not None:
        item["preview"] = preview
    return item


def _run_tool_calls(db, tool_calls, route: ToolRoute | None = None):
    """Provede read tooly a z write toolů udělá pending akce.

    route (A5): write tool, který routing v tomto requestu nevystavil (žádný write záměr), se NEPROVEDE
    ani nepřipraví – model dostane chybu. Read tooly mimo route se provedou (jen čtou data).
    """
    tool_messages = []
    pending_actions = []

    for tc in tool_calls:
        fn_name = tc.function.name
        print(f"[TOOL CALL] {fn_name}")

        try:
            arguments = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
            # Bez obsahu argumentů (mohou obsahovat uživatelská data).
            print(f"  [TOOL ERROR] invalid JSON args for {fn_name}")

        if fn_name in WRITE_TOOL_NAMES and route is not None and not route.allows(fn_name):
            print(f"  [TOOL BLOCKED] write tool {fn_name} not routed for this request")
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({
                    "error": "write_not_available",
                    "detail": "No change was prepared. Ask the user to state the change explicitly.",
                }, ensure_ascii=False),
            })
            continue

        if fn_name in WRITE_TOOL_NAMES:
            # Phase B: cíle se dohledají v DB TEĎ; nejednoznačný / neplatný cíl = žádná pending akce.
            try:
                pending_item = prepare_write_action(db, fn_name, arguments)
            except MutationRefused as refused:
                print(f"  [TOOL REFUSED] {fn_name}: {refused.code}")
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(refused.as_tool_result(), ensure_ascii=False, default=str),
                })
                continue
            except TypeError as exc:
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"status": "not_prepared", "error": "invalid_arguments",
                                           "detail": str(exc)}, ensure_ascii=False),
                })
                continue
            tool_result = {
                "status": "confirmation_required",
                "id": pending_item["id"],
                "tool": fn_name,
                "arguments": arguments,
                "expires_at": pending_item["expires_at"],
            }
            if "preview" in pending_item:
                tool_result["preview"] = pending_item["preview"]
            pending_actions.append(pending_item)

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result, ensure_ascii=False, default=str),
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
                spec = TOOLS_BY_NAME.get(fn_name)
                result = function(db, **arguments) if spec is not None and spec.takes_db else function(**arguments)
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


# Odpověď, když request připravil pending akci: deterministicky, nezávisle na textu modelu.
PENDING_CONFIRMATION_ANSWER = "Připravil jsem změnu k potvrzení."

DAILY_LIMIT_KINDS = frozenset({"TPD", "RPD"})


class LLMRateLimitError(RuntimeError):
    """Provider odmítl kvůli limitu (429). Volající rozhodují podle typu, ne podle textu zprávy."""


class DailyLimitError(LLMRateLimitError):
    """Vyčerpaný denní limit (TPD/RPD) – krátké čekání nepomůže; /chat podle typu volí text pro uživatele."""


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _llm_create_with_retry(
    api_messages: list[dict],
    tools,
    tool_choice: str = "auto",
    temperature: float = 0.2,
    max_retries: int | None = None,
    call_log: list[LLMCallRecord] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    extra_params: dict | None = None,
):
    """Chat completion s aplikačním retry (SDK retry je vypnuté → každý 429/5xx je vidět v logu).

    max_retries = celkový počet pokusů (default LLM_SETTINGS.llm_max_attempts). Po 429 se čeká dle
    hlavičky retry-after / textu „try again in …" (max AI_LLM_RETRY_MAX_WAIT_SECONDS). Každý pokus
    se zapíše do call_log (jen čísla) a zaloguje bez obsahu zpráv. tools=None → volání bez toolů
    (např. shrnutí konverzace); model default LLM_SETTINGS.groq_model. extra_params = další parametry jen
    pro konkrétního volajícího (např. Denní přehled: response_format, reasoning_effort, max_completion_tokens);
    běžný chat je neposílá.
    """
    import openai as _openai

    attempts = max_retries or LLM_SETTINGS.llm_max_attempts
    log_enabled = LLM_SETTINGS.usage_logging
    records = call_log if call_log is not None else []
    request_kwargs: dict = {
        "model": model or LLM_SETTINGS.groq_model,
        "messages": api_messages,
        "temperature": temperature,
    }
    if tools:
        request_kwargs.update(tools=tools, tool_choice=tool_choice)
    if max_tokens is not None:
        request_kwargs["max_tokens"] = max_tokens
    if extra_params:
        request_kwargs.update(extra_params)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            raw = client.chat.completions.with_raw_response.create(**request_kwargs)
            response = raw.parse()
        except _openai.RateLimitError as exc:
            last_exc = exc
            headers = getattr(getattr(exc, "response", None), "headers", None)
            record = LLMCallRecord(
                attempt=attempt, latency_ms=_elapsed_ms(started), rate_limited=True,
                ratelimit_remaining_tokens=ratelimit_remaining_tokens(headers),
                limit_kind=rate_limit_kind(exc),
            )
            records.append(record)
            log_call(record, log_enabled)
            if record.limit_kind in DAILY_LIMIT_KINDS:
                # Denní limit: čekání v řádu sekund nepomůže – neretryovat, říct pravdu.
                raise DailyLimitError(
                    "AI provider má vyčerpaný denní limit (rate limit tokenů/požadavků za den byl překročen). "
                    "Zkus to prosím později – limit se průběžně obnovuje."
                ) from last_exc
            if attempt < attempts:
                wait_s = retry_wait_seconds(exc, LLM_SETTINGS.retry_max_wait_seconds)
                log_retry(attempt, attempts, wait_s, "429", log_enabled)
                time.sleep(wait_s)
                continue
            raise LLMRateLimitError(
                "AI provider nedisponuje (Rate limit 8 000 tokenů/minutu byl překročen). "
                "Zkus to prosím za 10-20 sekund znovu, nebo zjednoduš otázku."
            ) from last_exc
        except _openai.APIError as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            record = LLMCallRecord(attempt=attempt, latency_ms=_elapsed_ms(started), error_status=status or 0)
            records.append(record)
            log_call(record, log_enabled)
            if attempt < attempts and (status or 500) >= 500:
                log_retry(attempt, attempts, 1.5, f"api_error {status}", log_enabled)
                time.sleep(1.5)
                continue
            raise RuntimeError(
                f"AI provider vrátil chybu ({status if status is not None else '?'}). "
                f"Zkus to prosím později znovu."
            ) from last_exc
        except Exception as exc:
            last_exc = exc
            raise RuntimeError(
                f"Při volání AI došlo k chybě: {exc}"
            ) from last_exc

        usage = getattr(response, "usage", None)
        message = response.choices[0].message
        record = LLMCallRecord(
            attempt=attempt,
            latency_ms=_elapsed_ms(started),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            ratelimit_remaining_tokens=ratelimit_remaining_tokens(raw.headers),
            tool_calls=len(message.tool_calls or []),
        )
        records.append(record)
        log_call(record, log_enabled)
        return response
    raise RuntimeError("AI volání selhalo po několika pokusech.") from last_exc


def _warn_if_fixed_overhead_exceeds_budget(system_prompt: str, tools: list[dict] | None = None) -> None:
    overhead = estimate_fixed_overhead(system_prompt, TOOLS if tools is None else tools)
    if overhead.total > LLM_SETTINGS.max_fixed_tokens:
        print(
            f"[ai] WARNING fixní režie ~{overhead.total} tokenů (prompt {overhead.prompt_tokens} + "
            f"{overhead.tool_count} tool schémat {overhead.tool_tokens}) překračuje "
            f"AI_MAX_FIXED_TOKENS={LLM_SETTINGS.max_fixed_tokens}"
        )


AUTO_MEMORIES_CALL_ID = "auto_get_memories"


def _is_tool_validation_error(exc: Exception) -> bool:
    """Groq 400 „tool call validation failed" (např. volání toolu, který request neobsahoval)."""
    import openai as _openai

    cause = exc.__cause__
    return isinstance(cause, _openai.BadRequestError) and "tool" in str(cause).lower()


def _route_for_request(user_texts: list[str], context: CurrentContext | None) -> ToolRoute:
    return route_tools(
        user_texts,
        enabled=LLM_SETTINGS.tool_routing,
        context_areas=context.areas if context is not None else frozenset(),
        covered_tools=context.covered_tools if context is not None else frozenset(),
        named_areas=context.named_areas if context is not None else frozenset(),
    )


def _route_tool_param(route: ToolRoute) -> list[dict] | None:
    """Tooly pro LLM request: kill switch = přesně TOOLS (dřívější chování), prázdná sada = bez toolů."""
    if not route.routed:
        return TOOLS
    return route.schemas or None


def _route_schema_tokens(route: ToolRoute | None) -> int:
    tools = _route_tool_param(route) if route is not None else None
    return estimate_tool_schema_tokens(tools) if tools else 0


def _with_planner_memories(round_calls: list, called_tools: set[str]) -> list:
    """Planner začíná get_goals; chybí-li get_memories, přidá ho server do STEJNÉHO kola.

    Model get_memories často vynechá; připomínka by stála celé další LLM kolo (~3k tokenů) a v reálném
    běhu přetáhla TPM limit. Takhle model data z paměti dostane bez dalšího volání.
    """
    names = {tc.function.name for tc in round_calls}
    if "get_goals" not in names or "get_memories" in names or "get_memories" in called_tools:
        return round_calls
    synthetic = types.SimpleNamespace(
        id=AUTO_MEMORIES_CALL_ID, function=types.SimpleNamespace(name="get_memories", arguments="{}"),
    )
    return [*round_calls, synthetic]


def _build_context_safely(db, last_user_message: str) -> CurrentContext | None:
    """CURRENT STATE prefetch; chyba nesmí shodit chat (model si data načte tooly jako dřív)."""
    try:
        return build_current_context(
            db,
            last_user_message,
            target_tokens=LLM_SETTINGS.context_target_tokens,
            max_tokens=LLM_SETTINGS.max_context_tokens,
        )
    except Exception as exc:  # noqa: BLE001 - kontext je optimalizace, ne podmínka odpovědi
        db.rollback()
        print(f"[ai] WARNING context prefetch selhal ({type(exc).__name__}) – pokračuji bez kontextu")
        return None


def _finalize_planner_answer(
    answer: str, evidence_texts: list[str], memory_texts: tuple[str, ...] = (),
) -> tuple[str, int]:
    """Odstraní z planner JSON bloku akce s nepodloženými projekty/částkami/daty/cíli.

    memory_texts (RELEVANT MEMORY) ověřují jen jména/plány, nikdy čísla – paměť není autorita pro data.
    """
    result = ground_planner_answer(answer, build_evidence(evidence_texts, memory_texts))
    return result.answer, result.removed_actions


SUMMARY_SYSTEM_PROMPT = (
    "Shrň starší část konverzace uživatele s asistentem Standa Hub tak, aby šlo v rozhovoru plynule "
    "pokračovat. Zapracuj dosavadní shrnutí (pokud je) a nové zprávy do JEDNOHO aktualizovaného shrnutí.\n"
    "Zachovej: rozhodnutí a preference uživatele vyslovené v konverzaci; nevyřešené úkoly a otevřené otázky; "
    "důležitá fakta a dohody; odkazy potřebné k navázání (o čem se mluvilo, na co se uživatel odkazuje).\n"
    "Vynech: small talk, pozdravy, opakování, doslovné formulace, přesná aktuální čísla z modulů "
    "(finance, hodiny, XP, progres – ta se vždy čtou živě).\n"
    "Nic nevymýšlej. Česky, stručné odrážky, nejvýše {max_words} slov."
)


def summarize_conversation(previous_summary: str | None, messages: list[dict]) -> str:
    """Jedno LLM volání (GROQ_SUMMARY_MODEL, bez toolů) → aktualizované shrnutí starší historie."""
    transcript = "\n".join(
        f"{'Uživatel' if m.get('role') == 'user' else 'Asistent'}: {m.get('content') or ''}" for m in messages
    )
    user_content = (f"Dosavadní shrnutí:\n{previous_summary}\n\n" if previous_summary else "") + (
        f"Nové starší zprávy k zapracování:\n{transcript}"
    )
    max_tokens = LLM_SETTINGS.max_summary_tokens
    response = _llm_create_with_retry(
        api_messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT.format(max_words=max(40, int(max_tokens * 0.6)))},
            {"role": "user", "content": user_content},
        ],
        tools=None,
        temperature=0.1,
        model=LLM_SETTINGS.groq_summary_model,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def ask_ai(messages):
    db = SessionLocal()
    request_started = time.monotonic()
    call_log: list[LLMCallRecord] = []
    tool_rounds = 0
    planner_nudged = False
    planner_memories_autoloaded = False
    planner_actions_removed = 0
    context_tokens = 0
    context_sections = 0
    tool_route: ToolRoute | None = None
    route_widened = False
    try:
        _check_pending_expired(db)

        now = now_local()
        date_block = current_date_block(now)
        system_prompt = build_system_prompt(now)
        api_messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ]

        for message in messages:
            api_messages.append(_message_to_dict(message))

        # „Evidence" pro planner grounding: co model v tomto requestu skutečně viděl jako data.
        user_texts = [str(m.get("content") or "") for m in api_messages[1:] if m.get("role") == "user"]
        evidence_texts = [date_block, *user_texts]
        # Planner pravidla: data, která už nese CURRENT STATE, se počítají jako „načtená".
        called_tools: set[str] = set()
        memory_evidence: tuple[str, ...] = ()

        context = _build_context_safely(db, user_texts[-1] if user_texts else "")
        if context is not None:
            context_tokens, context_sections = context.estimated_tokens, len(context.sections)
            # Hned za system prompt, před historii – kontext popisuje stav TEĎ.
            api_messages.insert(1, {"role": "system", "content": context.text})
            evidence_texts.append(context.text[: len(context.text) - len(context.memory_text)])
            memory_evidence = (context.memory_text,) if context.memory_text else ()
            called_tools |= context.covered_tools
        # A5: sada toolů se vybere jednou před prvním voláním a platí pro všechna kola requestu.
        tool_route = _route_for_request(user_texts, context)
        _warn_if_fixed_overhead_exceeds_budget(system_prompt, _route_tool_param(tool_route) or [])
        all_pending_actions = []
        MAX_TOOL_ROUNDS = 10

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = _llm_create_with_retry(
                    api_messages=api_messages,
                    tools=_route_tool_param(tool_route),
                    tool_choice="auto",
                    temperature=0.2,
                    call_log=call_log,
                )
            except RuntimeError as exc:
                # Model chtěl tool mimo routovanou sadu → jednou rozšířit (všechny READ, WRITE jen při
                # write záměru) a kolo zopakovat; když ani to neprojde, poslední pokus bez toolů (textová
                # odpověď místo chyby). WRITE tooly bez write záměru se nikdy nevystaví.
                if not tool_route.routed or tool_route.reason == REASON_FALLBACK or not _is_tool_validation_error(exc):
                    raise
                tool_route, route_widened = widen_route(tool_route), True
                try:
                    response = _llm_create_with_retry(
                        api_messages=api_messages,
                        tools=_route_tool_param(tool_route),
                        tool_choice="auto",
                        temperature=0.2,
                        call_log=call_log,
                    )
                except RuntimeError as exc2:
                    if not _is_tool_validation_error(exc2):
                        raise
                    response = _llm_create_with_retry(
                        api_messages=api_messages, tools=None, temperature=0.2, call_log=call_log,
                    )

            choice = response.choices[0]
            assistant_msg = choice.message

            if not assistant_msg.tool_calls:
                answer = assistant_msg.content or ""
                if find_planner_block(answer) is not None:
                    # Připomínat jen tooly, které model v tomto requestu opravdu má k dispozici.
                    missing = [t for t in missing_planner_tools(called_tools) if tool_route.allows(t)]
                    if missing and not planner_nudged:
                        # Planner přeskočil povinné tooly → jednou připomenout a nechat model pokračovat.
                        planner_nudged = True
                        api_messages.append({"role": "system", "content": planner_tools_nudge(missing)})
                        continue
                    answer, planner_actions_removed = _finalize_planner_answer(answer, evidence_texts, memory_evidence)
                if all_pending_actions:
                    # Změna jen čeká na potvrzení – text modelu („byl označen jako hotový") by mohl tvrdit
                    # opak (reálný případ). Detail změny ukazuje karta s náhledem.
                    answer = PENDING_CONFIRMATION_ANSWER
                return {
                    "answer": answer,
                    "pending_actions": all_pending_actions,
                }

            round_calls = _with_planner_memories(list(assistant_msg.tool_calls), called_tools)
            planner_memories_autoloaded = planner_memories_autoloaded or len(round_calls) > len(assistant_msg.tool_calls)
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
                    for tc in round_calls
                ],
            })

            tool_rounds += 1
            called_tools.update(tc.function.name for tc in round_calls)
            tool_messages, pending_actions = _run_tool_calls(db, round_calls, tool_route)
            all_pending_actions.extend(pending_actions)
            api_messages.extend(tool_messages)
            evidence_texts.extend(m["content"] for m in tool_messages)

        return {
            "answer": (
                "Nepodařilo se dokončit požadavek během několika pokusů. "
                "Zkus prosím otázku zjednodušit, nebo požádej o menší rozsah informací."
            ),
            "pending_actions": all_pending_actions,
        }
    finally:
        log_request_summary(
            call_log, tool_rounds, _elapsed_ms(request_started),
            planner_actions_removed=planner_actions_removed, planner_nudged=planner_nudged,
            planner_memories_autoloaded=planner_memories_autoloaded,
            context_tokens=context_tokens, context_sections=context_sections,
            tools_exposed=len(tool_route.names) if tool_route is not None else 0,
            tool_schema_tokens=_route_schema_tokens(tool_route),
            tool_route=tool_route.reason if tool_route is not None else "",
            route_widened=route_widened,
            enabled=LLM_SETTINGS.usage_logging,
        )
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
                    f"Potvrzení akce AI #{action_id} selhalo: {he.detail}",
                    entity_type="PendingAction",
                    entity_id=_audit_entity_id(action_id),
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
        arguments = dict(stored.get("arguments") or {})
        # Roadmap 4E: kdo akci navrhl (AI / Rychlé přidání) – klíč se toolu nepředává.
        source = arguments.pop(PENDING_SOURCE_KEY, None)
        quick_add = source == QUICK_ADD_SOURCE
        user_context = "quick_add" if quick_add else "ai_confirm"

        if tool_name not in WRITE_TOOL_FUNCTIONS:
            _finalize_pending_status(db, action_id, "failed")
            try:
                log_activity(
                    db, "system", "error",
                    f"Neznámý write tool: {tool_name}",
                    entity_type="ToolRegistry",
                    entity_id=_audit_entity_id(action_id),
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
            fn_args["user_context"] = user_context
            try:
                import inspect
                sig = inspect.signature(fn)
                if "user_context" not in sig.parameters:
                    fn_args = dict(arguments)
            except Exception:
                fn_args = dict(arguments)
            result = fn(**fn_args)

            undo_record = result.pop("undo", None) if isinstance(result, dict) else None
            if undo_record is not None:
                # Phase C: data pro vrácení se uloží do původní akce ve stejném commitu jako stav executed.
                _finalize_executed_with_undo(db, action_id, undo_record)
                result["undo_available"] = bool(undo_record.get("supported"))
            else:
                _finalize_pending_status(db, action_id, "executed")

            # Rychlé přidání: záznam do Aktivity zapsal sám tool (user_context=quick_add) – není to akce AI.
            if not quick_add:
                try:
                    # Roadmap 4C: lidský text místo „Potvrzena akce add_work_session (date_value=…)".
                    summary = ai_action_summary(tool_name, arguments)[:480]
                    log_activity(
                        db, "ai", "approve", summary,
                        entity_type=tool_name,
                        entity_id=_audit_entity_id(action_id),
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
                    db, "system" if quick_add else "ai", "error" if quick_add else "reject",
                    (f"Rychlé přidání se nepodařilo – {ai_action_label(tool_name)}: {str(exc)[:120]}" if quick_add
                     else f"Akci AI se nepodařilo provést – {ai_action_label(tool_name)}: {str(exc)[:120]}"),
                    entity_type=tool_name,
                    entity_id=_audit_entity_id(action_id),
                    user_context=user_context
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
