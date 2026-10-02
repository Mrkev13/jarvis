import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import date, datetime, timedelta

from database import Base, engine
from database import SessionLocal
from models import WotResource, WotGrind, FinanceTransaction, Subject, Assignment, Exam, WorkSession, MffCharacter, Goal, Memory, Conversation, Message, Notification, GoalProgressHistory, PlannerRecommendationHistory, ActivityLog, PendingAction, BackupLog, AuthSession
from tools import get_wot_resources, get_wot_grinds, get_finance_summary

from auth_service import (
    auth_enabled,
    authenticate_pin_and_create_session,
    validate_session_token,
    revoke_session_token,
    cookie_params,
    AUTH_COOKIE_NAME,
)
from tools import get_finance_transactions
from tools import get_school_subjects, get_school_assignments, get_school_exams
from tools import get_work_sessions, get_work_summary
from tools import get_mff_characters, get_mff_summary, upsert_mff_character
from tools import get_goals, get_goals_summary

from fastapi.middleware.cors import CORSMiddleware


from ai import ask_ai, execute_confirm_action, reject_pending, _get_pending_action, _check_pending_expired

from goal_history_service import ensure_goal_progress_snapshot, compute_goal_progress_and_value
from notifications_service import generate_notifications, list_notifications, notifications_summary, mark_read, mark_all_read, resolve
from planner_service import generate_plan
from activity_service import log_activity, delta_dict


PLANNER_MODE_DAILY = "daily"
PLANNER_MODE_WEEKLY = "weekly"
PLANNER_MODE_GOAL_REVIEW = "goal_review"


def detect_planner_intent(prompt: str) -> tuple[str, str] | None:
    if not prompt:
        return None
    t = (prompt or "").strip().lower()
    t_norm = re.sub(r"\s+", " ", t)

    def has(*words):
        return any(w in t_norm for w in words)

    goal_review_signals = (
        has("cíl", "cíle", "cil", "cile", "goal", "goals")
        and (
            has("přehled", "prehled", "review", "stav", "progres", "progress", "vedu", "vedou", "jak")
            or has("plním", "plnim", "splňuji", "splnuju")
            or has("stagn", "zastavil", "zastavilo")
        )
    )
    if goal_review_signals:
        return PLANNER_MODE_GOAL_REVIEW, "Níže je přehled stavu cílů a jejich pokroku."

    daily_signals_raw = [
        (["dnes", "dneska", "dnes večer", "dneska večer"], ["dělat", "udělat", "udělej", "uplatnit", "plán", "plan", "priority", "priorita", "co"]),
        (["co mám dělat", "co budu dělat", "co dnes dělat"],),
        (["daily", "denní plán", "denni plan", "dnešní plán", "dnesní plan"],),
        (["co je na programu", "program na dnes", "agenda dnes", "agenda na dnes"],),
    ]
    for sigs in daily_signals_raw:
        if all(has(*s) for s in sigs):
            return PLANNER_MODE_DAILY, "Níže je plán na dnes s nejdůležitějšími akcemi."

    weekly_signals_raw = [
        (["tento týden", "tenhle týden", "tento tyden", "tenhle tyden", "týden", "tyden", "weekly"],
         ["plán", "plan", "priority", "priorit", "dělat", "co"]),
        (["týdenní plán", "tydenni plan", "weekly plan"],),
        (["co tento týden", "co tenhle týden", "co na tento týden"],),
    ]
    for sigs in weekly_signals_raw:
        if all(has(*s) for s in sigs):
            return PLANNER_MODE_WEEKLY, "Níže je plán na tento týden s prioritami."

    if has("plán", "plan", "planner") and has("goal", "cíl", "cil", "cíle", "cile"):
        return PLANNER_MODE_GOAL_REVIEW, "Níže je přehled cílů."

    if has("dnes") and (has("co", "dělat", "udělat") or len(t_norm.split()) <= 8):
        return PLANNER_MODE_DAILY, "Plán na dnes:"

    if (has("týden"  , "tyden") or has("tento týden", "tenhle týden")) and len(t_norm.split()) <= 10:
        return PLANNER_MODE_WEEKLY, "Plán na tento týden:"

    return None

Base.metadata.create_all(bind=engine)


def _derive_conversation_title(prompt: str) -> str:
    text = (prompt or "").strip()
    if not text:
        return "Nový chat"

    lowered = text.lower()

    if "tento týden" in lowered or "tenhle týden" in lowered:
        if "priorit" in lowered:
            return "Týdenní priority"
        if "plán" in lowered:
            return "Týdenní plán"

    if re.search(r"\bvz\.?\s*55\b", lowered):
        return "WoT – VZ.55 postup"

    if "bilanc" in lowered or "výdaj" in lowered or "příjem" in lowered:
        return "Finance"

    if "úkol" in lowered or "deadline" in lowered or "assignment" in lowered or "škola" in lowered:
        return "Škola"

    if "práce" in lowered or "work" in lowered or "odprac" in lowered:
        return "Work"

    first_line = text.splitlines()[0].strip()
    cleaned = re.sub(r"\s+", " ", first_line).strip()
    cleaned = cleaned.rstrip("?.! ")
    if len(cleaned) > 48:
        cleaned = cleaned[:48].rstrip() + "…"
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Nový chat"


def _seed_default_subjects():
    db = SessionLocal()
    try:
        count = db.query(Subject).count()
        if count == 0:
            defaults = [
                Subject(name="English in IT", code="", semester="", credits=0, active=True),
                Subject(name="Intro to Study", code="", semester="", credits=0, active=True),
                Subject(name="Foundations of Law", code="", semester="", credits=0, active=True),
                Subject(name="Physical Education", code="", semester="", credits=0, active=True),
            ]
            db.add_all(defaults)
            db.commit()
    finally:
        db.close()


_seed_default_subjects()


RUN_ALEMBIC_UPGRADE_AT_STARTUP = (os.environ.get("RUN_ALEMBIC_UPGRADE_AT_STARTUP", "true").lower() in ("1", "true", "yes"))
if RUN_ALEMBIC_UPGRADE_AT_STARTUP:
    try:
        from alembic.config import Config as _AlembicCfg
        from alembic import command as _alembic_cmd
        _alembic_ini = str(Path(__file__).parent / "alembic.ini")
        if Path(_alembic_ini).exists():
            _cfg = _AlembicCfg(_alembic_ini)
            _alembic_cmd.upgrade(_cfg, "head")
    except Exception as _alembic_err:
        import warnings as _w
        _w.warn(f"Alembic startup upgrade selhalo: {_alembic_err}")

try:
    _recovery_db = SessionLocal()
    expired_count = _check_pending_expired(_recovery_db)
    if expired_count:
        print(f"[recovery] {expired_count} pending označen jako expired při startu")
    from models import PendingAction as _PA
    from sqlalchemy import update as _upd
    _cutoff = datetime.utcnow() - timedelta(minutes=15)
    _stuck = _recovery_db.execute(
        _upd(_PA).where(_PA.status == "executing").where(_PA.created_at < _cutoff).values(status="failed")
    )
    if _stuck.rowcount:
        _recovery_db.commit()
        print(f"[recovery] {_stuck.rowcount} executing označen jako failed")
    _recovery_db.close()
except Exception as _rec_err:
    pass


from scheduler_service import start_scheduler
start_scheduler()


frontend_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
allowed_origins = [
    origin.strip()
    for origin in frontend_origins.split(",")
    if origin.strip()
]

app = FastAPI(title="Standa Hub API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",", 1)[0].strip()
    if hasattr(request.client, "host"):
        try:
            return request.client.host
        except Exception:
            return "unknown"
    return "unknown"


def require_auth(request: Request) -> dict:
    """FastAPI dependency. Pokud auth_enabled a žádná platná session → 401."""
    if not auth_enabled():
        return {"is_authenticated": True, "auth_disabled": True}
    token = request.cookies.get(AUTH_COOKIE_NAME)
    info = validate_session_token(token)
    if not info or not info.get("is_authenticated"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return info


class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str | None = None
    messages: list[ChatMessage] | None = None

class WotResourceRequest(BaseModel):
    resource: str
    amount: float

class WotGrindRequest(BaseModel):
    tank: str
    xp_remaining: float
    priority: str = "medium"
    status: str = "active"

class FinanceTransactionRequest(BaseModel):
    amount: float
    category: str
    description: str = ""
    transaction_type: str

class SubjectRequest(BaseModel):
    name: str
    code: str = ""
    semester: str = ""
    credits: int = 0
    active: bool = True

class AssignmentRequest(BaseModel):
    title: str
    description: str = ""
    due_date: date | None = None
    priority: str = "medium"
    status: str = "todo"
    subject_id: int

class ExamRequest(BaseModel):
    title: str
    exam_type: str = "exam"
    exam_date: date | None = None
    status: str = "upcoming"
    notes: str = ""
    subject_id: int

class WorkSessionRequest(BaseModel):
    date: date
    hours: float
    project: str = ""
    description: str = ""
    hourly_rate: float = 0
    sync_to_finance: bool = True

class MffCharacterRequest(BaseModel):
    name: str
    tier: str = "T3"
    level: int = 80
    uniform: str = ""
    ctp: str = ""
    artifact: str = ""
    priority: str = "medium"
    status: str = "built"
    notes: str = ""
    role: str = ""
    team: str = ""
    uru_state: str = ""
    iso8_set: str = ""
    build_completeness: int = 0
    roles: list[str] | None = None
    team_supports: str = ""
    uru_slots_total: int | None = None
    uru_slots_filled: int | None = None
    odin_blessings_count: int | None = None

class GoalRequest(BaseModel):
    id: int | None = None
    area: str
    title: str
    description: str = ""
    status: str = "active"
    priority: str = "medium"
    progress: int = 0
    tracking_type: str = "manual"
    target_value: float | None = None
    source: str | None = None
    target_date: date | None = None

class MemoryRequest(BaseModel):
    area: str = "general"
    category: str = "context"
    content: str
    importance: int = 5
    active: bool = True


class MemoryUpdateRequest(BaseModel):
    area: str | None = None
    category: str | None = None
    content: str | None = None
    importance: int | None = None
    active: bool | None = None


class ConversationCreateRequest(BaseModel):
    title: str | None = None


class ConversationUpdateRequest(BaseModel):
    title: str


class AppendMessageRequest(BaseModel):
    role: str
    content: str


class ConfirmActionRequest(BaseModel):
    action_id: str


class ExecutePendingRequest(BaseModel):
    pending_id: str


@app.get("/")
def root():
    return {
        "status": "ok",
        "app": "Standa Hub"
    }


@app.post("/chat")
def chat(request: ChatRequest):
    conversation_id = request.conversation_id
    prompt = (request.message or "").strip()
    if not prompt and request.messages:
        for m in reversed(request.messages):
            if m.role == "user" and m.content.strip():
                prompt = m.content.strip()
                break

    if conversation_id is not None:
        if not prompt:
            raise HTTPException(status_code=400, detail="missing_message")

        db = SessionLocal()
        try:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == conversation_id)
                .first()
            )
            if not conv:
                raise HTTPException(status_code=404, detail="conversation_not_found")

            existing_count = (
                db.query(Message.id)
                .filter(Message.conversation_id == conv.id)
                .count()
            )

            db.add(Message(conversation_id=conv.id, role="user", content=prompt))

            if existing_count == 0:
                current_title = (conv.title or "").strip()
                if not current_title or current_title == "Nový chat":
                    conv.title = _derive_conversation_title(prompt)

            conv.updated_at = datetime.utcnow()
            db.commit()

            db_messages = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
                .all()
            )
            messages_for_ai = [
                {"role": m.role, "content": m.content}
                for m in db_messages
            ]
        finally:
            db.close()
    else:
        if not request.messages:
            raise HTTPException(status_code=400, detail="missing_messages")
        messages_for_ai = request.messages

    planner_intent = detect_planner_intent(prompt)
    if planner_intent is not None:
        planner_mode, planner_summary_intro = planner_intent
        planner_db = SessionLocal()
        try:
            plan_payload = generate_plan(planner_db, mode=planner_mode)
            planner_db.commit()
            card_type = (
                "goal_review" if planner_mode == PLANNER_MODE_GOAL_REVIEW
                else "daily" if planner_mode == PLANNER_MODE_DAILY
                else "weekly"
            )
            answer_lines = [planner_summary_intro, ""]
            if card_type == "goal_review":
                goals = plan_payload.get("goals") or []
                answer_lines.append(
                    f"Aktivních cílů: {len(goals)}. "
                    "Podrobnosti (progress, stagnace, on-track) viz níže v Goal Review kartě."
                )
            else:
                actions = plan_payload.get("actions") or []
                answer_lines.append(plan_payload.get("summary") or "")
                answer_lines.append("")
                for idx, a in enumerate(actions[:5], start=1):
                    answer_lines.append(f"{idx}. [{a.get('area','')}] {a.get('title','')}")
                    if a.get("reason"):
                        answer_lines.append(f"   → {a['reason']}")
            answer_text = "\n".join(answer_lines).strip()
            if conversation_id is not None and answer_text:
                save_db = SessionLocal()
                try:
                    conv = (
                        save_db.query(Conversation)
                        .filter(Conversation.id == conversation_id)
                        .first()
                    )
                    if conv:
                        save_db.add(Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=answer_text,
                        ))
                        conv.updated_at = datetime.utcnow()
                        save_db.commit()
                finally:
                    save_db.close()
            return {
                "answer": answer_text,
                "pending_actions": [],
                "planner_result": {
                    "card_type": card_type,
                    "payload": plan_payload,
                },
            }
        except Exception as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={
                    "error": f"Planner chyba: {exc}",
                    "answer": "⚠️ Planner dočasně nefunguje. Zkus klasickou otázku nebo stránku /planner.",
                    "pending_actions": [],
                },
            )
        finally:
            planner_db.close()

    try:
        result = ask_ai(messages_for_ai)
        if conversation_id is not None and isinstance(result, dict) and "answer" in result:
            db = SessionLocal()
            try:
                conv = (
                    db.query(Conversation)
                    .filter(Conversation.id == conversation_id)
                    .first()
                )
                if conv:
                    db.add(
                        Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=str(result.get("answer") or ""),
                        )
                    )
                    conv.updated_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()
        return result
    except RuntimeError as exc:
        from fastapi.responses import JSONResponse
        msg = str(exc)
        status = 503
        if "Rate limit" in msg or "překročen" in msg:
            status = 429
        return JSONResponse(
            status_code=status,
            content={
                "error": msg,
                "answer": (
                    f"⚠️ {msg}\n\n"
                    "Uložila jsem kontext, můžeš klidně pokládat otázky pokračovat. "
                    "Za 10 sekund by to mělo zase fungovat."
                ),
                "pending_actions": [],
            },
        )
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Interní chyba: {exc}",
                "answer": (
                    "⚠️ Stala se neočekávaná chyba při volání AI. "
                    "Zkus to prosím za chvíli znovu – pokud potíže přetrvají, restartuj backend."
                ),
                "pending_actions": [],
            },
        )


@app.get("/conversations")
def list_conversations():
    db = SessionLocal()
    try:
        items = (
            db.query(Conversation)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .all()
        )
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            }
            for c in items
        ]
    finally:
        db.close()


@app.post("/conversations")
def create_conversation(request: ConversationCreateRequest):
    title = (request.title or "").strip()
    db = SessionLocal()
    try:
        conv = Conversation(title=title or "Nový chat")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
        }
    finally:
        db.close()


@app.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, request: ConversationUpdateRequest):
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="missing_title")
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        conv.title = title
        conv.updated_at = datetime.utcnow()
        db.commit()
        return {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
        }
    finally:
        db.close()


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int):
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        db.delete(conv)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int):
    db = SessionLocal()
    try:
        exists = (
            db.query(Conversation.id)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if not exists:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        items = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )
        return [
            {
                "id": m.id,
                "conversation_id": m.conversation_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in items
        ]
    finally:
        db.close()


@app.post("/conversations/{conversation_id}/messages")
def append_message(conversation_id: int, request: AppendMessageRequest):
    role = request.role.strip()
    content = request.content
    if not role or not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="missing_message_fields")
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation_not_found")
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        db.add(msg)
        conv.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(msg)
        return {
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at,
        }
    finally:
        db.close()


@app.post("/actions/confirm")
def confirm_action(request: ConfirmActionRequest):
    return execute_confirm_action(request.action_id)


@app.get("/ai/confirm/{pending_id}")
def ai_confirm_get(pending_id: str):
    db = SessionLocal()
    try:
        _check_pending_expired(db)
        pa = _get_pending_action(db, pending_id)
        if pa is None:
            raise HTTPException(status_code=404, detail="Pending action not found")
        if pa["status"] in ("rejected", "expired", "executed", "failed"):
            return {
                "id": pa["id"],
                "tool": pa["tool"],
                "arguments": pa["arguments"],
                "status": pa["status"],
                "created_at": pa["created_at"].isoformat() if pa.get("created_at") else None,
                "expires_at": pa["expires_at"].isoformat() if pa.get("expires_at") else None,
            }
        return {
            "id": pa["id"],
            "tool": pa["tool"],
            "arguments": pa["arguments"],
            "status": pa["status"],
            "created_at": pa["created_at"].isoformat() if pa.get("created_at") else None,
            "expires_at": pa["expires_at"].isoformat() if pa.get("expires_at") else None,
        }
    finally:
        db.close()


@app.post("/ai/execute")
def ai_execute(request: ExecutePendingRequest):
    return execute_confirm_action(request.pending_id)


@app.get("/ai/reject/{pending_id}")
def ai_reject(pending_id: str):
    db = SessionLocal()
    try:
        _check_pending_expired(db)
        try:
            reject_pending(db, pending_id)
        except HTTPException:
            raise
        return {
            "ok": True,
            "pending_id": pending_id,
            "status": "rejected",
        }
    finally:
        db.close()


@app.post("/wot/resource")
def add_wot_resource(request: WotResourceRequest):
    db = SessionLocal()

    try:
        existing = (
            db.query(WotResource)
            .filter(WotResource.resource == request.resource)
            .first()
        )

        old_amount = None
        if existing:
            old_amount = float(existing.amount or 0.0)
            existing.amount = request.amount
            item_id = existing.id
            action_type = "update"
        else:
            item = WotResource(
                resource=request.resource,
                amount=request.amount
            )
            db.add(item)
            db.flush()
            item_id = item.id
            action_type = "create"

        if action_type == "update" and old_amount is not None:
            old_str = f"{old_amount:,.0f}".replace(",", " ")
            new_str = f"{float(request.amount):,.0f}".replace(",", " ")
            summary = f"Zdroj {request.resource}: {old_str} → {new_str}"
            delta = delta_dict(
                type("Temp", (), {"amount": old_amount})(),
                type("Temp", (), {"amount": float(request.amount)})(),
                ["amount"]
            )
            log_activity(
                db, "wot", action_type, summary,
                entity_type="WotResource", entity_id=item_id,
                delta=delta,
                user_context="manual"
            )
        else:
            amount_str = f"{float(request.amount):,.0f}".replace(",", " ")
            summary = f"Zdroj {request.resource} nastaven na {amount_str}"
            delta = delta_dict(None, type("Temp", (), {"amount": float(request.amount), "resource": request.resource})(), ["resource", "amount"])
            log_activity(
                db, "wot", action_type, summary,
                entity_type="WotResource", entity_id=item_id,
                delta=delta,
                user_context="manual"
            )

        db.commit()

        return {
            "status": "ok",
            "resource": request.resource,
            "amount": request.amount
        }

    finally:
        db.close()

@app.get("/wot/resources")
def wot_resources():
    return get_wot_resources()

@app.post("/wot/grind")
def add_wot_grind(request: WotGrindRequest):
    db = SessionLocal()

    try:
        existing = (
            db.query(WotGrind)
            .filter(WotGrind.tank == request.tank)
            .first()
        )

        tracked_fields = ["xp_remaining", "priority", "status"]
        if existing:
            old_obj = WotGrind()
            for f in tracked_fields:
                setattr(old_obj, f, getattr(existing, f, None))

            existing.xp_remaining = request.xp_remaining
            existing.priority = request.priority
            existing.status = request.status
            item_id = existing.id

            xp_str = f"{float(request.xp_remaining or 0):,.0f}".replace(",", " ")
            summary = f"Grind {request.tank} upraven – zbývá {xp_str} XP"
            log_activity(
                db, "wot", "update", summary,
                entity_type="WotGrind", entity_id=item_id,
                delta=delta_dict(old_obj, existing, tracked_fields),
                user_context="manual"
            )
        else:
            item = WotGrind(
                tank=request.tank,
                xp_remaining=request.xp_remaining,
                priority=request.priority,
                status=request.status
            )
            db.add(item)
            db.flush()
            item_id = item.id

            xp_str = f"{float(request.xp_remaining or 0):,.0f}".replace(",", " ")
            summary = f"Nový grind {request.tank} – zbývá {xp_str} XP"
            log_activity(
                db, "wot", "create", summary,
                entity_type="WotGrind", entity_id=item_id,
                delta=delta_dict(None, item, tracked_fields + ["tank"]),
                user_context="manual"
            )

        db.commit()

        return {
            "status": "ok",
            "tank": request.tank
        }

    finally:
        db.close()

@app.get("/wot/grinds")
def wot_grinds():
    return get_wot_grinds()

@app.post("/finance/transaction")
def add_finance_transaction(request: FinanceTransactionRequest):
    db = SessionLocal()

    try:
        item = FinanceTransaction(
            amount=request.amount,
            category=request.category,
            description=request.description,
            transaction_type=request.transaction_type
        )

        db.add(item)
        db.flush()
        item_id_for_log = item.id

        sign = "+" if request.transaction_type == "income" else "-"
        amount_str = f"{request.amount:,.0f}".replace(",", " ")
        summary = f"{sign}{amount_str} Kč {request.category}"
        if request.description:
            summary = f"{summary} ({request.description})"
        log_activity(
            db, "finance", "create", summary,
            entity_type="FinanceTransaction", entity_id=item_id_for_log,
            delta=delta_dict(None, item, ["amount", "category", "description", "transaction_type"]),
            user_context="manual"
        )

        db.commit()
        db.refresh(item)

        goals = (
            db.query(Goal)
            .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
            .filter(Goal.source == "finance_balance")
            .all()
        )
        changed = 0
        for g in goals:
            before_pct, _ = compute_goal_progress_and_value(db, g)
            if ensure_goal_progress_snapshot(db, g):
                after_pct, _ = compute_goal_progress_and_value(db, g)
                if before_pct != after_pct:
                    log_activity(
                        db, "goals", "snapshot",
                        f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                        entity_type="Goal", entity_id=g.id,
                        user_context="manual"
                    )
                changed += 1
        if changed:
            db.commit()

        return {
            "status": "ok",
            "id": item.id
        }

    finally:
        db.close()

@app.get("/finance/transactions")
def finance_transactions():
    db = SessionLocal()

    try:
        items = (
            db.query(FinanceTransaction)
            .order_by(FinanceTransaction.created_at.desc())
            .all()
        )

        return [
            {
                "id": item.id,
                "amount": item.amount,
                "category": item.category,
                "description": item.description,
                "transaction_type": item.transaction_type,
                "created_at": item.created_at
            }
            for item in items
        ]

    finally:
        db.close()

@app.get("/finance/summary")
def finance_summary():
    return get_finance_summary()


# ===== SCHOOL =====

@app.get("/school/subjects")
def school_subjects():
    return get_school_subjects()

@app.post("/school/subject")
def add_school_subject(request: SubjectRequest):
    db = SessionLocal()

    try:
        item = Subject(
            name=request.name,
            code=request.code,
            semester=request.semester,
            credits=request.credits,
            active=request.active,
        )
        db.add(item)
        db.flush()

        log_activity(
            db, "school", "create", f"Předmět přidán: {request.name}",
            entity_type="Subject", entity_id=item.id,
            delta=delta_dict(None, item, ["name", "code", "semester", "credits", "active"]),
            user_context="manual"
        )

        db.commit()
        db.refresh(item)

        return {
            "status": "ok",
            "id": item.id,
            "name": item.name,
        }

    finally:
        db.close()

@app.get("/school/assignments")
def school_assignments():
    return get_school_assignments()

@app.post("/school/assignment")
def add_school_assignment(request: AssignmentRequest):
    db = SessionLocal()

    try:
        item = Assignment(
            title=request.title,
            description=request.description,
            due_date=request.due_date,
            priority=request.priority,
            status=request.status,
            subject_id=request.subject_id,
        )
        db.add(item)
        db.flush()

        log_activity(
            db, "school", "create", f"Úkol přidán: {request.title}",
            entity_type="Assignment", entity_id=item.id,
            delta=delta_dict(None, item, ["title", "description", "due_date", "priority", "status", "subject_id"]),
            user_context="manual"
        )

        db.commit()
        db.refresh(item)

        return {
            "status": "ok",
            "id": item.id,
            "title": item.title,
        }

    finally:
        db.close()

@app.get("/school/exams")
def school_exams():
    return get_school_exams()

@app.post("/school/exam")
def add_school_exam(request: ExamRequest):
    db = SessionLocal()

    try:
        item = Exam(
            title=request.title,
            exam_type=request.exam_type,
            exam_date=request.exam_date,
            status=request.status,
            notes=request.notes,
            subject_id=request.subject_id,
        )
        db.add(item)
        db.flush()

        log_activity(
            db, "school", "create", f"Zkouška přidána: {request.title}",
            entity_type="Exam", entity_id=item.id,
            delta=delta_dict(None, item, ["title", "exam_type", "exam_date", "status", "notes", "subject_id"]),
            user_context="manual"
        )

        db.commit()
        db.refresh(item)

        return {
            "status": "ok",
            "id": item.id,
            "title": item.title,
        }

    finally:
        db.close()


# ===== WORK =====

@app.get("/work/sessions")
def work_sessions_list():
    return get_work_sessions()


@app.post("/work/session")
def add_work_session(request: WorkSessionRequest):
    db = SessionLocal()

    try:
        item = WorkSession(
            date=request.date,
            hours=request.hours,
            project=request.project,
            description=request.description,
            hourly_rate=request.hourly_rate,
            sync_to_finance=request.sync_to_finance,
        )
        db.add(item)
        db.flush()

        earnings = round(item.hours * item.hourly_rate, 2)
        finance_item = None
        if earnings > 0 and request.sync_to_finance and item.finance_transaction_id is None:
            description = f"Work: {item.project or 'Práce'}"
            if item.description:
                description = f"{description} – {item.description}"
            finance_item = FinanceTransaction(
                amount=earnings,
                category="work",
                description=description,
                transaction_type="income",
            )
            db.add(finance_item)
            db.flush()
            item.finance_transaction_id = finance_item.id

        hours_str = f"{request.hours:g}"
        work_summary = f"+{hours_str} h"
        if request.project:
            work_summary = f"{work_summary} – {request.project}"
        if request.description:
            work_summary = f"{work_summary} ({request.description})"
        log_activity(
            db, "work", "create", work_summary,
            entity_type="WorkSession", entity_id=item.id,
            delta=delta_dict(None, item, ["date", "hours", "project", "description", "hourly_rate", "sync_to_finance"]),
            user_context="manual"
        )

        if finance_item is not None:
            fin_amount_str = f"{earnings:,.0f}".replace(",", " ")
            fin_summary = f"+{fin_amount_str} Kč work (sync)"
            if request.description:
                fin_summary = f"{fin_summary} – {request.description}"
            log_activity(
                db, "finance", "sync", fin_summary,
                entity_type="FinanceTransaction", entity_id=finance_item.id,
                delta=delta_dict(None, finance_item, ["amount", "category", "description", "transaction_type"]),
                user_context="manual"
            )

        db.commit()
        db.refresh(item)

        goals = (
            db.query(Goal)
            .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
            .filter(Goal.source.in_(["work_month_hours", "finance_balance"]))
            .all()
        )
        changed = 0
        for g in goals:
            before_pct, _ = compute_goal_progress_and_value(db, g)
            if ensure_goal_progress_snapshot(db, g):
                after_pct, _ = compute_goal_progress_and_value(db, g)
                if before_pct != after_pct:
                    log_activity(
                        db, "goals", "snapshot",
                        f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                        entity_type="Goal", entity_id=g.id,
                        user_context="manual"
                    )
                changed += 1
        if changed:
            db.commit()

        return {
            "status": "ok",
            "id": item.id,
            "earnings": earnings,
            "finance_transaction_id": item.finance_transaction_id,
        }

    finally:
        db.close()


@app.get("/work/summary")
def work_summary_endpoint():
    return get_work_summary()


# ===== MFF =====

@app.get("/mff/characters")
def mff_characters_list():
    return get_mff_characters()


@app.post("/mff/character")
def add_mff_character(request: MffCharacterRequest):
    from fastapi import HTTPException
    from models import compute_mff_build_completeness, parse_legacy_uru_state, legacy_role_string_to_list

    roles_in = request.roles if request.roles is not None else legacy_role_string_to_list(request.role or "")
    if isinstance(roles_in, str):
        roles_in = legacy_role_string_to_list(roles_in)
    roles_clean = [str(r).strip() for r in (roles_in or []) if r and str(r).strip()]

    def_ut, def_uf, def_ob = parse_legacy_uru_state(request.uru_state or "")
    ut = int(request.uru_slots_total) if request.uru_slots_total is not None else def_ut
    uf = int(request.uru_slots_filled) if request.uru_slots_filled is not None else def_uf
    ob = int(request.odin_blessings_count) if request.odin_blessings_count is not None else def_ob
    ut = max(0, ut)
    uf = max(0, uf)
    ob = max(0, ob)
    level_i = max(1, int(request.level or 80))
    if ut > 0 and uf > ut:
        raise HTTPException(status_code=400, detail=f"uru_slots_filled ({uf}) nesmí být větší než uru_slots_total ({ut})")
    ts = (request.team_supports or "").strip() or (request.team or "").strip()
    auto_bc = compute_mff_build_completeness(
        request.tier,
        level_i,
        request.uniform,
        request.ctp,
        request.artifact,
        ut,
        uf,
        request.iso8_set,
        ts,
    )
    result = upsert_mff_character(
        name=request.name,
        tier=request.tier,
        level=level_i,
        uniform=request.uniform,
        ctp=request.ctp,
        artifact=request.artifact,
        priority=request.priority,
        status=request.status,
        notes=request.notes,
        role=request.role,
        team=request.team,
        uru_state=request.uru_state,
        iso8_set=request.iso8_set,
        build_completeness=auto_bc,
        roles=roles_clean,
        team_supports=ts,
        uru_slots_total=ut,
        uru_slots_filled=uf,
        odin_blessings_count=ob,
    )
    return {
        "status": "ok",
        "id": result.get("id"),
        "name": result.get("name"),
        "build_completeness": result.get("build_completeness", auto_bc),
    }


@app.get("/mff/summary")
def mff_summary_endpoint():
    return get_mff_summary()


@app.get("/mff/role-options")
def mff_role_options():
    from models import MFF_ROLE_OPTIONS
    return {"options": list(MFF_ROLE_OPTIONS)}


@app.delete("/mff/character/{item_id}")
def delete_mff_character(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(MffCharacter).filter(MffCharacter.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="MffCharacter not found")

        tracked_fields = ["tier", "build_completeness", "status", "priority"]
        tier_str = item.tier or "?"
        bc = int(getattr(item, "build_completeness", 0) or 0)
        log_activity(
            db, "mff", "delete", f"Postava smazána: '{item.name}' ({tier_str}, {bc}%)",
            entity_type="MffCharacter", entity_id=item.id,
            delta=delta_dict(item, None, tracked_fields),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        goals = (
            db.query(Goal)
            .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
            .filter(Goal.source.in_(["mff_t4_count", "mff_built_t4_count", "mff_high_priority_built_count"]))
            .all()
        )
        changed = 0
        for g in goals:
            before_pct, _ = compute_goal_progress_and_value(db, g)
            if ensure_goal_progress_snapshot(db, g):
                after_pct, _ = compute_goal_progress_and_value(db, g)
                if before_pct != after_pct:
                    log_activity(
                        db, "goals", "snapshot",
                        f"Cíl '{g.title}' {before_pct}% → {after_pct}%",
                        entity_type="Goal", entity_id=g.id,
                        user_context="manual"
                    )
                changed += 1
        if changed:
            db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()

@app.get("/goals/list")
def goals_list():
    return get_goals()


@app.get("/goals/summary")
def goals_summary():
    return get_goals_summary()


@app.post("/goal")
def add_or_update_goal(request: GoalRequest):
    db = SessionLocal()

    try:
        if request.id is not None:
            existing = db.query(Goal).filter(Goal.id == request.id).first()
            if existing:
                old_obj = Goal()
                for f in ["area", "title", "description", "status", "priority", "tracking_type", "target_value", "source", "target_date", "progress"]:
                    setattr(old_obj, f, getattr(existing, f, None))

                existing.area = request.area
                existing.title = request.title
                existing.description = request.description
                existing.status = request.status
                existing.priority = request.priority
                existing.tracking_type = request.tracking_type or "manual"
                existing.target_value = request.target_value
                existing.source = request.source
                existing.target_date = request.target_date
                if (existing.tracking_type or "manual") == "manual":
                    existing.progress = max(0, min(100, int(request.progress or 0)))

                log_activity(
                    db, "goals", "update", f"Cíl '{request.title}' upraven",
                    entity_type="Goal", entity_id=existing.id,
                    delta=delta_dict(old_obj, existing, ["area", "title", "description", "status", "priority", "progress", "tracking_type", "target_value", "source", "target_date"]),
                    user_context="manual"
                )

                db.commit()
                before_pct, _ = compute_goal_progress_and_value(db, existing)
                if ensure_goal_progress_snapshot(db, existing):
                    after_pct, _ = compute_goal_progress_and_value(db, existing)
                    if before_pct != after_pct:
                        log_activity(
                            db, "goals", "snapshot",
                            f"Cíl '{existing.title}' {before_pct}% → {after_pct}%",
                            entity_type="Goal", entity_id=existing.id,
                            user_context="manual"
                        )
                    db.commit()
                return {"status": "ok", "id": existing.id, "updated": True}

        item = Goal(
            area=request.area,
            title=request.title,
            description=request.description,
            status=request.status,
            priority=request.priority,
            tracking_type=request.tracking_type or "manual",
            target_value=request.target_value,
            source=request.source,
            target_date=request.target_date,
        )
        if (item.tracking_type or "manual") == "manual":
            item.progress = max(0, min(100, int(request.progress or 0)))
        db.add(item)
        db.flush()

        log_activity(
            db, "goals", "create", f"Nový cíl '{request.title}'",
            entity_type="Goal", entity_id=item.id,
            delta=delta_dict(None, item, ["area", "title", "description", "status", "priority", "progress", "tracking_type", "target_value", "source", "target_date"]),
            user_context="manual"
        )

        db.commit()
        db.refresh(item)
        before_pct, _ = compute_goal_progress_and_value(db, item)
        if ensure_goal_progress_snapshot(db, item):
            after_pct, _ = compute_goal_progress_and_value(db, item)
            if before_pct != after_pct:
                log_activity(
                    db, "goals", "snapshot",
                    f"Cíl '{item.title}' {before_pct}% → {after_pct}%",
                    entity_type="Goal", entity_id=item.id,
                    user_context="manual"
                )
            db.commit()
        return {"status": "ok", "id": item.id, "updated": False}

    finally:
        db.close()


# ===== MEMORY =====

@app.get("/memories")
def memories_list(
    area: str | None = None,
    category: str | None = None,
    q: str | None = None,
    include_inactive: bool = False,
):
    db = SessionLocal()
    try:
        query = db.query(Memory)
        if not include_inactive:
            query = query.filter(Memory.active == True)
        if area:
            query = query.filter(Memory.area == area)
        if category:
            query = query.filter(Memory.category == category)
        if q and q.strip():
            from sqlalchemy import or_
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    Memory.content.ilike(pattern),
                    Memory.area.ilike(pattern),
                    Memory.category.ilike(pattern),
                )
            )

        items = query.order_by(
            Memory.importance.desc(),
            Memory.updated_at.desc(),
            Memory.id.desc(),
        ).all()

        return [
            {
                "id": it.id,
                "area": it.area,
                "category": it.category,
                "content": it.content,
                "importance": it.importance,
                "active": it.active,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
            for it in items
        ]
    finally:
        db.close()


@app.post("/memory")
def add_memory(request: MemoryRequest):
    from tools import save_memory
    return save_memory(
        area=request.area,
        category=request.category,
        content=request.content,
        importance=request.importance,
        active=request.active,
    )


# ===== NOTIFICATIONS =====

@app.get("/notifications")
def notifications_list(
    unread_only: bool = False,
    severity: str | None = None,
    area: str | None = None,
    include_resolved: bool = False,
):
    db = SessionLocal()
    try:
        return list_notifications(
            db,
            unread_only=bool(unread_only),
            severity=severity,
            area=area,
            include_resolved=bool(include_resolved),
        )
    finally:
        db.close()


@app.get("/notifications/summary")
def notifications_summary_endpoint():
    db = SessionLocal()
    try:
        return notifications_summary(db)
    finally:
        db.close()


@app.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int):
    db = SessionLocal()
    try:
        ok = mark_read(db, notification_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notification not found")
        db.commit()
        return {"status": "ok", "id": notification_id, "read": True}
    finally:
        db.close()


@app.patch("/notifications/read-all")
def mark_all_notifications_read():
    db = SessionLocal()
    try:
        count = mark_all_read(db)
        db.commit()
        return {"status": "ok", "updated": count}
    finally:
        db.close()


@app.patch("/notifications/{notification_id}/resolve")
def resolve_notification(notification_id: int):
    db = SessionLocal()
    try:
        ok = resolve(db, notification_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notification not found")
        db.commit()
        return {"status": "ok", "id": notification_id, "resolved": True}
    finally:
        db.close()


@app.post("/notifications/generate")
def generate_notifications_endpoint():
    db = SessionLocal()
    try:
        stats = generate_notifications(db)
        db.commit()
        return {"status": "ok", "stats": stats}
    finally:
        db.close()


# ===== PLANNER 2.0 =====

@app.get("/planner")
def planner_generate(mode: str = "weekly"):
    db = SessionLocal()
    try:
        plan = generate_plan(db, mode=mode)
        db.commit()
        return plan
    finally:
        db.close()


# ===== DASHBOARD 2.0 =====


def _top_active_goals(db, limit: int = 3):
    from datetime import date as _date

    today = _date.today()
    rows = db.query(Goal).all()
    enriched: list[dict] = []
    for g in rows:
        status = (g.status or "").lower()
        if status in ("completed", "paused", "cancelled"):
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


def _get_work_with_goal(db):
    today = date.today()
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


def _get_finance_with_goal(db):
    transactions = db.query(FinanceTransaction).all()
    income = 0.0
    expenses = 0.0
    today = date.today()
    this_month = (today.year, today.month)
    this_month_income = 0.0
    this_month_expenses = 0.0
    for t in transactions:
        amt = float(t.amount or 0.0)
        if (t.transaction_type or "").lower() == "income":
            income += amt
            if t.created_at and (t.created_at.year, t.created_at.month) == this_month:
                this_month_income += amt
        else:
            expenses += amt
            if t.created_at and (t.created_at.year, t.created_at.month) == this_month:
                this_month_expenses += amt
    goal_row = (
        db.query(Goal)
        .filter(Goal.source == "finance_balance")
        .all()
    )
    active_goal = None
    balance = income - expenses
    for g in goal_row:
        s = (g.status or "").lower()
        if s in ("completed", "cancelled", "paused"):
            continue
        progress, current_value = compute_goal_progress_and_value(db, g, today=today)
        active_goal = {
            "id": g.id,
            "title": g.title,
            "current_value": float(current_value) if current_value is not None else float(balance),
            "target_value": float(g.target_value) if g.target_value is not None else None,
            "progress": progress,
            "target_date": g.target_date.isoformat() if g.target_date else None,
        }
        break
    return {
        "balance": round(balance, 2),
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "this_month_income": round(this_month_income, 2),
        "this_month_expenses": round(this_month_expenses, 2),
        "transactions_count": len(transactions),
        "goal": active_goal,
    }


def _get_upcoming(db, limit: int = 5, today: date | None = None):
    from datetime import date as _d

    today_use: date = today or _d.today()
    entries: list[dict] = []
    assignments = db.query(Assignment).filter(Assignment.due_date.is_not(None)).all()
    for it in assignments:
        st = (it.status or "").lower()
        if st in ("completed", "done"):
            continue
        days = (it.due_date - today_use).days
        entries.append({
            "type": "assignment",
            "id": it.id,
            "title": it.title,
            "area": "school",
            "date": it.due_date.isoformat(),
            "days_left": days,
            "overdue": days < 0,
        })
    exams = db.query(Exam).filter(Exam.exam_date.is_not(None)).all()
    for it in exams:
        st = (it.status or "").lower()
        if st in ("completed", "done", "passed"):
            continue
        days = (it.exam_date - today_use).days
        entries.append({
            "type": "exam",
            "id": it.id,
            "title": it.title,
            "area": "school",
            "date": it.exam_date.isoformat(),
            "days_left": days,
            "overdue": days < 0,
        })
    goals = db.query(Goal).filter(Goal.target_date.is_not(None)).all()
    for g in goals:
        st = (g.status or "").lower()
        if st in ("completed", "paused", "cancelled"):
            continue
        days = (g.target_date - today_use).days
        entries.append({
            "type": "goal_target",
            "id": g.id,
            "title": g.title,
            "area": g.area or "general",
            "date": g.target_date.isoformat(),
            "days_left": days,
            "overdue": days < 0,
        })

    def sort_key(e):
        overdue_rank = 0 if e["overdue"] else 1
        if e["overdue"]:
            return (overdue_rank, int(e["days_left"] or 0), e["type"], e["title"])
        return (overdue_rank, int(e["days_left"] or 0), e["type"], e["title"])

    entries.sort(key=sort_key)
    return entries[:max(0, int(limit))]


def _get_notifications_preview(db, limit: int = 3, now: datetime | None = None):
    rows = list_notifications(db, unread_only=True, include_resolved=False, now=now)
    sev_rank = {"important": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda n: (
        sev_rank.get((n.get("severity") or "info").lower(), 3),
        -(n.get("created_at_ts") or 0),
    ))
    return rows[:max(0, int(limit))]


def _get_wot_quick_status(db, limit: int = 2):
    grinds = db.query(WotGrind).all()
    pr_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {"active": 0, "in_progress": 1, "paused": 2}
    active_grinds = []
    for g in grinds:
        s = (g.status or "").lower()
        if s in ("completed", "done", "cancelled"):
            continue
        active_grinds.append({
            "id": g.id,
            "tank": g.tank,
            "xp_remaining": float(g.xp_remaining or 0.0),
            "priority": g.priority or "medium",
            "status": g.status or "active",
        })
    active_grinds.sort(key=lambda g: (
        pr_rank.get((g["priority"] or "").lower(), 3),
        status_rank.get((g["status"] or "").lower(), 4),
        float(g["xp_remaining"] or 0.0),
    ))
    resources = {r.resource: float(r.amount or 0.0) for r in db.query(WotResource).all()}
    return {
        "top_grinds": active_grinds[:max(0, int(limit))],
        "credits": resources.get("credits"),
        "free_xp": resources.get("free_xp"),
        "bonds": resources.get("bonds"),
    }


def _get_mff_quick_status(db):
    items = db.query(MffCharacter).all()
    tracked = len(items)
    t4_count = 0
    priority_high_count = 0
    bc_sum = 0.0
    from models import compute_mff_build_completeness, parse_legacy_uru_state, legacy_role_string_to_list
    for it in items:
        t = (it.tier or "").strip().lower().replace(" ", "")
        if t in ("t4", "tier4", "transcendent"):
            t4_count += 1
        if (it.priority or "").lower() == "high":
            priority_high_count += 1
        roles_list = getattr(it, "roles", None)
        if roles_list is None or isinstance(roles_list, str):
            roles_list = legacy_role_string_to_list(
                roles_list if isinstance(roles_list, str) else (getattr(it, "role", "") or "")
            )
        ut = int(getattr(it, "uru_slots_total", 0) or 0)
        uf = int(getattr(it, "uru_slots_filled", 0) or 0)
        ob = int(getattr(it, "odin_blessings_count", 0) or 0)
        if ut <= 0:
            _ut2, _uf2, _ob2 = parse_legacy_uru_state(getattr(it, "uru_state", "") or "")
            if ut <= 0:
                ut = _ut2 or 20
            if uf <= 0 and _uf2:
                uf = _uf2
            if ob <= 0 and _ob2:
                ob = _ob2
        ts = (getattr(it, "team_supports", None) or "") or (getattr(it, "team", "") or "")
        bc = compute_mff_build_completeness(
            it.tier, it.level, it.uniform, it.ctp, it.artifact, ut, uf, it.iso8_set, ts,
        )
        bc_sum += float(bc)
    return {
        "tracked_characters": tracked,
        "t4_count": t4_count,
        "priority_count": priority_high_count,
        "average_build_completeness": 0 if tracked == 0 else int(round(bc_sum / tracked)),
    }


@app.get("/dashboard")
def dashboard_get():
    db = SessionLocal()
    try:
        today_plan = generate_plan(db, mode="daily")
        db.commit()
        today_actions = today_plan.get("actions") or []
        summary_text = today_plan.get("summary") or ""

        today_deadline = None
        for a in today_actions:
            reason = a.get("reason") or ""
            if "dnes" in reason.lower():
                today_deadline = a
                break

        today = {
            "summary": summary_text,
            "actions": today_actions[:3],
            "today_deadline": today_deadline,
        }

        notif_summary = notifications_summary(db)
        notif_preview = _get_notifications_preview(db, limit=3)

        notifications = {
            "unread": int(notif_summary.get("unread") or 0),
            "important": int(notif_summary.get("important") or 0),
            "warning": int(notif_summary.get("warning") or 0),
            "info": int(notif_summary.get("info") or 0),
            "preview": notif_preview,
        }

        goals_list = _top_active_goals(db, limit=3)
        goals = {
            "top": goals_list,
            "count": len(goals_list),
        }

        work = _get_work_with_goal(db)
        finance = _get_finance_with_goal(db)
        upcoming = _get_upcoming(db, limit=5)
        wot = _get_wot_quick_status(db, limit=2)
        mff = _get_mff_quick_status(db)

        recent_activity_rows = (
            db.query(ActivityLog)
            .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
            .limit(5)
            .all()
        )
        recent_activity = [
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "area": r.area,
                "action_type": r.action_type,
                "summary": r.summary,
            }
            for r in recent_activity_rows
        ]

        return {
            "today": today,
            "notifications": notifications,
            "goals": goals,
            "work": work,
            "finance": finance,
            "upcoming": upcoming,
            "wot": wot,
            "mff": mff,
            "recent_activity": recent_activity,
        }
    finally:
        db.close()


def _parse_iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


@app.get("/activity")
def activity_list(
    area: str | None = None,
    action_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    from_date: str | None = None,
    to_date: str | None = None,
    q: str | None = None,
):
    from sqlalchemy import and_, or_

    limit_val = max(1, min(int(limit or 50), 500))
    offset_val = max(0, int(offset or 0))

    db = SessionLocal()
    try:
        query = db.query(ActivityLog)
        conditions = []

        if area:
            conditions.append(ActivityLog.area == area)
        if action_type:
            conditions.append(ActivityLog.action_type == action_type)
        if q:
            qpat = f"%{q}%"
            conditions.append(ActivityLog.summary.ilike(qpat))
        from_dt = _parse_iso_dt(from_date)
        if from_dt:
            conditions.append(ActivityLog.timestamp >= from_dt)
        to_dt = _parse_iso_dt(to_date)
        if to_dt:
            conditions.append(ActivityLog.timestamp <= to_dt)

        if conditions:
            query = query.filter(and_(*conditions))

        total = query.count()
        items = (
            query.order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
            .limit(limit_val)
            .offset(offset_val)
            .all()
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "area": r.area,
                    "action_type": r.action_type,
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "summary": r.summary,
                    "user_context": r.user_context,
                }
                for r in items
            ],
            "total": total,
            "limit": limit_val,
            "offset": offset_val,
        }
    finally:
        db.close()


@app.get("/activity/{item_id}")
def activity_detail(item_id: int):
    import json as _json_inner

    db = SessionLocal()
    try:
        r = db.query(ActivityLog).filter(ActivityLog.id == item_id).first()
        if r is None:
            raise HTTPException(status_code=404, detail="ActivityLog not found")
        delta_obj = None
        if r.delta_json:
            try:
                delta_obj = _json_inner.loads(r.delta_json)
            except Exception:
                delta_obj = {"_raw": r.delta_json}
        return {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "area": r.area,
            "action_type": r.action_type,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "summary": r.summary,
            "delta": delta_obj,
            "user_context": r.user_context,
            "dedupe_key": r.dedupe_key,
        }
    finally:
        db.close()


@app.get("/pending")
def pending_list(status: str | None = None, limit: int = 50):
    db = SessionLocal()
    try:
        limit_val = max(1, min(int(limit or 50), 500))
        query = db.query(PendingAction)
        if status:
            for s in status.split(","):
                s = s.strip()
                if s:
                    query = query.filter(PendingAction.status == s)
        items = query.order_by(PendingAction.created_at.desc()).limit(limit_val).all()
        import json as _j
        return {
            "items": [
                {
                    "id": str(p.id),
                    "tool": p.tool,
                    "arguments": _j.loads(p.arguments) if p.arguments else {},
                    "status": p.status,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                }
                for p in items
            ]
        }
    finally:
        db.close()


@app.get("/scheduler/status")
def scheduler_status():
    from scheduler_service import SCHEDULER_ENABLED, SCHEDULER_INTERVAL_SECONDS, SINGLE_WORKER_ASSUMPTION_DOC
    return {
        "enabled": SCHEDULER_ENABLED,
        "interval_seconds": SCHEDULER_INTERVAL_SECONDS,
        "doc": SINGLE_WORKER_ASSUMPTION_DOC,
    }


@app.post("/scheduler/run-now")
def scheduler_run_now():
    from scheduler_service import run_job_now
    return run_job_now()


@app.get("/backup/list")
def backup_list(limit: int = 20):
    from backup_service import list_backups
    return {
        "items": list_backups(limit=max(1, min(limit, 100)))
    }


@app.post("/backup/run-now")
def backup_run_now():
    from backup_service import run_backup, BACKUP_ENABLED
    backup_id = run_backup()
    return {"ok": True, "backup_log_id": backup_id, "backup_enabled_env": BACKUP_ENABLED}


@app.post("/auth/login")
async def auth_login(request: Request, response: Response):
    body = await request.json()
    pin = (body or {}).get("pin") or ""
    if not isinstance(pin, str):
        return JSONResponse({"ok": False, "error": "invalid_pin"}, status_code=400)
    ip = _get_client_ip(request)
    ua = request.headers.get("user-agent")
    token, exp, err = authenticate_pin_and_create_session(pin, ip, ua)
    if err == "auth_disabled":
        # auth is disabled, return ok no-op
        return {"ok": True, "auth_disabled": True, "session_set": False}
    if err or token is None:
        return JSONResponse(
            {"ok": False, "error": err or "invalid_credentials"},
            status_code=401
        )
    response.set_cookie(value=token, expires=exp, **{k: v for k, v in cookie_params(exp).items() if k != "expires"})
    return {
        "ok": True,
        "session_set": True,
        "expires_at": exp.isoformat() if exp else None,
    }


@app.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    revoke_session_token(token)
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        secure=cookie_params().get("secure"),
        httponly=cookie_params().get("httponly"),
        samesite=cookie_params().get("samesite"),
    )
    return {"ok": True, "logged_out": True}


@app.get("/auth/session/validate")
async def auth_session_validate(request: Request):
    """Ověření pro Next.js middleware. Vrací {valid:bool, auth_disabled:bool}."""
    if not auth_enabled():
        return {"valid": True, "auth_disabled": True}
    token = request.cookies.get(AUTH_COOKIE_NAME)
    info = validate_session_token(token)
    valid = bool(info and info.get("is_authenticated"))
    return {
        "valid": valid,
        "auth_disabled": False,
        "session": {
            k: info[k] for k in ("expires_at", "auth_disabled", "session_id") if k in (info or {})
        } if valid else None,
    }


# ===== DELETE ENDPOINTS (FAZE 3) =====

@app.delete("/wot/grind/{item_id}")
def delete_wot_grind(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(WotGrind).filter(WotGrind.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="WotGrind not found")

        tracked_fields = ["tank", "xp_remaining", "priority", "status"]
        log_activity(
            db, "wot", "delete", f"Grind smazán: {item.tank}",
            entity_type="WotGrind", entity_id=item.id,
            delta=delta_dict(item, None, tracked_fields),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()


@app.delete("/finance/transaction/{item_id}")
def delete_finance_transaction(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(FinanceTransaction).filter(FinanceTransaction.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="FinanceTransaction not found")
        try:
            sp = db.begin_nested()
            try:
                from sqlalchemy import text as _tx
                db.execute(
                    _tx("UPDATE work_sessions SET finance_transaction_id = NULL WHERE finance_transaction_id = :tid"),
                    {"tid": item_id},
                )
                sp.commit()
            except Exception:
                sp.rollback()
        except Exception:
            pass

        sign = "+" if item.transaction_type == "income" else "-"
        amount_str = f"{float(item.amount or 0):,.0f}".replace(",", " ")
        summary = f"{sign}{amount_str} Kč {item.category or ''}"
        if item.description:
            summary = f"{summary} ({item.description})"
        log_activity(
            db, "finance", "delete", f"Smazáno: {summary}",
            entity_type="FinanceTransaction", entity_id=item.id,
            delta=delta_dict(item, None, ["amount", "category", "description", "transaction_type"]),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()


@app.delete("/work/session/{item_id}")
def delete_work_session(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(WorkSession).filter(WorkSession.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="WorkSession not found")

        hours_str = f"{float(item.hours or 0):g}"
        work_summary = f"-{hours_str} h"
        if item.project:
            work_summary = f"{work_summary} – {item.project}"
        log_activity(
            db, "work", "delete", f"Smazáno: {work_summary}",
            entity_type="WorkSession", entity_id=item.id,
            delta=delta_dict(item, None, ["date", "hours", "project", "description", "hourly_rate"]),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()


@app.delete("/school/assignment/{item_id}")
def delete_school_assignment(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(Assignment).filter(Assignment.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Assignment not found")

        log_activity(
            db, "school", "delete", f"Úkol smazán: {item.title}",
            entity_type="Assignment", entity_id=item.id,
            delta=delta_dict(item, None, ["title", "description", "due_date", "priority", "status", "subject_id"]),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()


@app.delete("/school/exam/{item_id}")
def delete_school_exam(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(Exam).filter(Exam.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Exam not found")

        log_activity(
            db, "school", "delete", f"Zkouška smazána: {item.title}",
            entity_type="Exam", entity_id=item.id,
            delta=delta_dict(item, None, ["title", "exam_type", "exam_date", "status", "notes", "subject_id"]),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()


@app.delete("/goal/{item_id}")
def delete_goal(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(Goal).filter(Goal.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Goal not found")

        log_activity(
            db, "goals", "delete", f"Smazán cíl '{item.title}'",
            entity_type="Goal", entity_id=item.id,
            delta=delta_dict(item, None, ["area", "title", "description", "status", "priority", "progress", "tracking_type", "target_value", "source", "target_date"]),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()


@app.delete("/memory/{item_id}")
def delete_memory(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(Memory).filter(Memory.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        old_obj = Memory()
        for f in ["area", "category", "content", "importance", "active"]:
            setattr(old_obj, f, getattr(item, f, None))
        item.active = False

        content_preview = (item.content or "").strip()
        if len(content_preview) > 50:
            content_preview = content_preview[:50].rstrip() + "…"
        log_activity(
            db, "memory", "delete", f"Pamatka deaktivována (soft): {content_preview}",
            entity_type="Memory", entity_id=item.id,
            delta=delta_dict(old_obj, item, ["active"]),
            user_context="manual"
        )

        db.commit()
        return {"status": "ok", "deactivated": True, "id": item_id}
    finally:
        db.close()


@app.patch("/memory/{item_id}")
def update_memory(item_id: int, request: MemoryUpdateRequest):
    db = SessionLocal()
    try:
        item = db.query(Memory).filter(Memory.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        old_obj = Memory()
        for f in ["area", "category", "content", "importance", "active"]:
            setattr(old_obj, f, getattr(item, f, None))
        old_active = bool(item.active)

        if request.area is not None:
            item.area = request.area.strip() or item.area
        if request.category is not None:
            item.category = request.category.strip() or item.category
        if request.content is not None:
            item.content = request.content
        if request.importance is not None:
            item.importance = max(1, min(10, int(request.importance)))
        if request.active is not None:
            item.active = bool(request.active)

        changed_fields = []
        for f in ["area", "category", "content", "importance", "active"]:
            if getattr(old_obj, f, None) != getattr(item, f, None):
                changed_fields.append(f)

        if request.active is not None and old_active != bool(request.active):
            toggle_str = "aktivována" if bool(request.active) else "deaktivována"
            content_preview = (item.content or "").strip()
            if len(content_preview) > 50:
                content_preview = content_preview[:50].rstrip() + "…"
            log_activity(
                db, "memory", "update", f"Pamatka {toggle_str}: {content_preview}",
                entity_type="Memory", entity_id=item.id,
                delta=delta_dict(old_obj, item, changed_fields or ["active"]),
                user_context="manual"
            )
        elif changed_fields:
            content_preview = (item.content or "").strip()
            if len(content_preview) > 50:
                content_preview = content_preview[:50].rstrip() + "…"
            log_activity(
                db, "memory", "update", f"Pamatka upravena: {content_preview}",
                entity_type="Memory", entity_id=item.id,
                delta=delta_dict(old_obj, item, changed_fields),
                user_context="manual"
            )

        db.commit()
        db.refresh(item)
        return {
            "status": "ok",
            "id": item.id,
            "area": item.area,
            "category": item.category,
            "content": item.content,
            "importance": item.importance,
            "active": item.active,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
    finally:
        db.close()


@app.delete("/memory/{item_id}/hard")
def hard_delete_memory(item_id: int):
    db = SessionLocal()
    try:
        item = db.query(Memory).filter(Memory.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        content_preview = (item.content or "").strip()
        if len(content_preview) > 50:
            content_preview = content_preview[:50].rstrip() + "…"
        log_activity(
            db, "memory", "delete", f"Pamatka trvale smazána (hard): {content_preview}",
            entity_type="Memory", entity_id=item.id,
            delta=delta_dict(item, None, ["area", "category", "content", "importance", "active"]),
            user_context="manual"
        )

        db.delete(item)
        db.commit()
        return {"status": "ok", "deleted": True, "id": item_id}
    finally:
        db.close()
