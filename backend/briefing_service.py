"""Denní přehled (Roadmap 3.0 Phase F): jeden perzistentní AI přehled na pražský kalendářní den.

Tok: deterministický snímek (`briefing_snapshot`) → jedno LLM volání BEZ toolů a se stropem výstupu →
validace JSON → grounding (každá položka musí odkazovat na `ref` ze snímku; konkrétní čísla / data / jména
v textu musí být ve snímku, jinak se text nahradí štítkem ze snímku) → uložení do `daily_briefings`.
Klidný den (nic po termínu ani blízko) se zvládne bez LLM. Selhání nic dalšího neovlivní: připomínky,
notifikace i Web Push běží v jiných jobech; Groq denní limit se zkusí až za několik hodin.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, time as dtime, timedelta

from sqlalchemy import update as _sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from briefing_snapshot import Snapshot, build_snapshot
from llm_budget import estimate_tokens
from models import DailyBriefing, Notification
from planner_guard import build_evidence, ungrounded_items
from time_utils import local_day_bounds_utc, to_local, utc_now

logger = logging.getLogger("standa_hub.briefing")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s [briefing] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

MAX_OUTPUT_TOKENS = 700
MAX_PRIORITIES, MAX_LIST = 5, 5
MAX_SCHEDULER_ATTEMPTS = 4
STALE_GENERATING = timedelta(minutes=10)
ON_TIME_WINDOW = timedelta(minutes=30)  # později než tohle po nastaveném čase = „catchup"
RETRY_DELAYS = {
    "daily_limit": timedelta(hours=3),
    "rate_limit": timedelta(minutes=15),
    "provider": timedelta(minutes=15),
    "invalid_response": timedelta(minutes=30),
    "grounding_rejected": timedelta(minutes=30),
    "internal": timedelta(minutes=30),
}
ERROR_TEXT = {
    "daily_limit": "AI má vyčerpaný denní limit – zkusím to později (nebo ručně).",
    "rate_limit": "AI je teď přetížená (limit za minutu) – zkusím to za chvíli.",
    "provider": "AI služba neodpověděla – zkusím to později.",
    "invalid_response": "AI vrátila neplatnou odpověď – zkusím to znovu.",
    "grounding_rejected": "AI odpověď neodpovídala datům – zkusím to znovu.",
    "internal": "Interní chyba při sestavení přehledu.",
}

SYSTEM_PROMPT = """You write the user's Daily Briefing in Standa Hub. The user message is a SNAPSHOT of real data (Europe/Prague); every line starts with a [ref].
Rules:
- Use ONLY the snapshot. Never invent tasks, dates, amounts, names or commitments. No motivational filler, no fake urgency.
- Czech, short. If little is happening, say so in one sentence and keep lists short or empty.
- priorities: 1-5 highest-value actions for today, ordered; each is one snapshot item (its ref).
- watch: overdue or needs-attention items. upcoming: next days. Never repeat a ref across lists.
- note: optional one short factual remark about progress or changes, else null.
Return ONLY this JSON:
{"summary":"1-2 sentences","priorities":[{"ref":"…","title":"max 12 words","why":"max 20 words"}],"watch":[{"ref":"…","text":"max 15 words"}],"upcoming":[{"ref":"…","text":"max 15 words"}],"note":null}"""


class BriefingError(Exception):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


class BriefingInProgress(Exception):
    pass


# ===== konfigurace =====

def briefing_enabled() -> bool:
    return os.environ.get("DAILY_BRIEFING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def briefing_push_enabled() -> bool:
    return os.environ.get("DAILY_BRIEFING_PUSH", "true").strip().lower() in ("1", "true", "yes", "on")


def briefing_time() -> dtime:
    raw = os.environ.get("DAILY_BRIEFING_TIME", "07:00").strip()
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", raw)
    return dtime(int(m.group(1)), int(m.group(2))) if m else dtime(7, 0)


# ===== LLM a validace =====

def _strip_json(text: str) -> dict:
    t = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if fence:
        t = fence.group(1)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise BriefingError("invalid_response")
    try:
        data = json.loads(t[start:end + 1])
    except ValueError:
        raise BriefingError("invalid_response") from None
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        raise BriefingError("invalid_response")
    for key in ("priorities", "watch", "upcoming"):
        value = data.get(key) or []
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise BriefingError("invalid_response")
        data[key] = value
    if data.get("note") is not None and not isinstance(data.get("note"), str):
        data["note"] = None
    return data


def _clip(text, limit: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def ground(data: dict, snap: Snapshot) -> tuple[dict, int]:
    """Odkazy jen na položky snímku, bez duplicit; neověřitelný text → štítek ze snímku. Vrací (obsah, oprav)."""
    by_ref = snap.by_ref()
    evidence = build_evidence([snap.render()])
    fixes = 0
    used: set[str] = set()

    def text_ok(text: str) -> bool:
        return bool(text) and not ungrounded_items(text, evidence)

    def items(raw: list[dict], text_key: str, limit: int, allow_kinds=None) -> list[dict]:
        nonlocal fixes
        out = []
        for entry in raw:
            ref = str(entry.get("ref") or "").strip().strip("[]")
            src = by_ref.get(ref)
            if src is None or ref in used or (allow_kinds and src.kind not in allow_kinds) or len(out) >= limit:
                fixes += 1
                continue
            used.add(ref)
            text = _clip(entry.get(text_key), 140)
            if not text_ok(text):
                fixes += int(bool(text))
                text = src.label
            item = {"ref": ref, "kind": src.kind, "text": text, "label": src.label, "when": src.when,
                    "url": src.url, "detail": src.detail, "new": src.new}
            if text_key == "title":
                why = _clip(entry.get("why"), 200)
                if why and not text_ok(why):
                    fixes += 1
                    why = ""
                item["why"] = why
            out.append(item)
        return out

    actionable = {"assignment", "exam", "reminder", "goal", "notification", "finance"}
    priorities = items(data.get("priorities") or [], "title", MAX_PRIORITIES, actionable)
    watch = items(data.get("watch") or [], "text", MAX_LIST, actionable)
    upcoming = items(data.get("upcoming") or [], "text", MAX_LIST, actionable)
    summary = _clip(data.get("summary"), 400)
    if not text_ok(summary):
        fixes += 1
        summary = deterministic_summary(snap)
    note = _clip(data.get("note"), 200) if data.get("note") else None
    if note and not text_ok(note):
        fixes += 1
        note = None
    if not (priorities or watch or upcoming) and not snap.is_quiet:
        raise BriefingError("grounding_rejected")
    return {"summary": summary, "priorities": priorities, "watch": watch, "upcoming": upcoming, "note": note}, fixes


def deterministic_summary(snap: Snapshot) -> str:
    parts = []
    for key, word in (("today", "dnes"), ("overdue", "po termínu / nevyřízeno"), ("soon", "brzy")):
        n = len(snap.sections.get(key) or [])
        if n:
            parts.append(f"{word}: {n}")
    return ("Přehled: " + ", ".join(parts) + ".") if parts else "Dnes žádné termíny ani nevyřízené věci."


def quiet_content(snap: Snapshot) -> dict:
    note = None
    if snap.changes_summary:
        note = f"Od minulého přehledu: {snap.changes_summary}."
    return {"summary": "Dnes žádné termíny ani nevyřízené věci – klidný den.", "priorities": [], "watch": [],
            "upcoming": [], "note": note}


def build_messages(snap: Snapshot) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": snap.render()}]


def estimate_request_tokens(snap: Snapshot) -> int:
    return sum(estimate_tokens(m["content"]) for m in build_messages(snap)) + MAX_OUTPUT_TOKENS


def _call_llm(snap: Snapshot, llm=None) -> tuple[str, dict]:
    """Jedno volání bez toolů. llm(messages, max_tokens) -> (text, usage) – v testech fake."""
    if llm is not None:
        return llm(build_messages(snap), MAX_OUTPUT_TOKENS)
    import ai
    from llm_config import LLM_SETTINGS

    records = []
    started = time.monotonic()
    try:
        response = ai._llm_create_with_retry(build_messages(snap), tools=None, temperature=0.2, max_retries=2,
                                             call_log=records, max_tokens=MAX_OUTPUT_TOKENS)
    except ai.DailyLimitError:
        raise BriefingError("daily_limit") from None
    except RuntimeError as exc:
        kinds = {r.limit_kind for r in records if r.rate_limited}
        raise BriefingError("rate_limit" if kinds or "Rate limit" in str(exc) else "provider") from None
    ok = [r for r in records if not r.rate_limited and r.error_status is None]
    usage = {
        "model": LLM_SETTINGS.groq_model,
        "prompt_tokens": sum(r.prompt_tokens or 0 for r in ok),
        "completion_tokens": sum(r.completion_tokens or 0 for r in ok),
        "total_tokens": sum(r.total_tokens or 0 for r in ok),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    return response.choices[0].message.content or "", usage


# ===== perzistence a generování =====

def get_for_date(db: Session, d: date) -> DailyBriefing | None:
    return db.query(DailyBriefing).filter(DailyBriefing.briefing_date == d).first()


def _previous(db: Session, d: date) -> DailyBriefing | None:
    return (db.query(DailyBriefing)
            .filter(DailyBriefing.briefing_date < d, DailyBriefing.status == "ready")
            .order_by(DailyBriefing.briefing_date.desc()).first())


def _claim(db: Session, d: date, trigger: str, now: datetime, *, regenerate: bool) -> tuple[DailyBriefing | None, str | None]:
    """Získá řádek dne ve stavu generating (nejvýš jeden běh) a hned započítá pokus (přežije i rollback).
    Vrací (řádek, předchozí obsah) nebo (None, None)."""
    row = get_for_date(db, d)
    if row is None:
        row = DailyBriefing(briefing_date=d, status="generating", trigger=trigger, attempts=1, grounding_removed=0,
                            regenerated_count=0, created_at=now, updated_at=now)
        try:
            db.add(row)
            db.commit()
        except IntegrityError:
            db.rollback()
            return None, None  # souběžný běh ho založil
        return row, None
    if row.status == "generating" and row.updated_at and now - row.updated_at < STALE_GENERATING:
        raise BriefingInProgress()
    if row.status == "ready" and not regenerate:
        return None, None
    claimed = db.execute(
        _sql_update(DailyBriefing)
        .where(DailyBriefing.id == row.id, DailyBriefing.status == row.status, DailyBriefing.updated_at == row.updated_at)
        .values(status="generating", trigger=trigger, updated_at=now, attempts=DailyBriefing.attempts + 1)
    )
    db.commit()
    if claimed.rowcount != 1:
        raise BriefingInProgress()
    db.refresh(row)
    previous_content = row.content if row.generated_at else None
    return row, previous_content


def generate(db: Session, *, trigger: str, now: datetime | None = None, regenerate: bool = False, llm=None) -> DailyBriefing | None:
    """Vygeneruje přehled pro DNEŠNÍ pražský den. Vrací řádek (ready/failed) nebo None, když nic nedělal."""
    now = now or utc_now()
    today = to_local(now).date()
    row, previous_content = _claim(db, today, trigger, now, regenerate=regenerate)
    if row is None:
        return get_for_date(db, today)
    was_ready = row.generated_at is not None
    started = time.monotonic()
    try:
        prev = _previous(db, today)
        prev_refs = set(json.loads(prev.source_refs or "[]")) if prev else None
        snap = build_snapshot(db, now, previous_refs=prev_refs, changes_since=prev.generated_at if prev else None)
        if snap.is_quiet:
            content, fixes = quiet_content(snap), 0
            usage = {"model": "deterministic", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                     "latency_ms": int((time.monotonic() - started) * 1000)}
        else:
            text, usage = _call_llm(snap, llm)
            content, fixes = ground(_strip_json(text), snap)
        content["quiet"] = snap.is_quiet
        content["date"] = today.isoformat()
        row.status, row.error_category, row.next_retry_at = "ready", None, None
        row.content = json.dumps(content, ensure_ascii=False)
        row.source_hash, row.source_refs = snap.source_hash(), json.dumps(snap.refs)
        row.snapshot_tokens = snap.tokens
        row.model = (usage.get("model") or "")[:100]
        row.prompt_tokens, row.completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        row.total_tokens, row.latency_ms = usage.get("total_tokens"), usage.get("latency_ms")
        row.grounding_removed = fixes
        row.generated_at = now
        row.first_generated_at = row.first_generated_at or now
        if was_ready:
            row.regenerated_count = int(row.regenerated_count or 0) + 1
        row.updated_at = now
        db.commit()
        if trigger != "manual":
            _notify(db, row, content, now)
        _log(row, trigger, "ready")
        return row
    except Exception as exc:  # noqa: BLE001 - selhání přehledu nesmí rozbít nic dalšího
        db.rollback()
        category = exc.category if isinstance(exc, BriefingError) else "internal"
        if not isinstance(exc, BriefingError):
            logger.warning("briefing internal error %s", type(exc).__name__)
        row = db.get(DailyBriefing, row.id)
        row.error_category = category if not previous_content else f"regenerate_failed:{category}"
        row.next_retry_at = now + RETRY_DELAYS.get(category, timedelta(minutes=30))
        # Nepovedené přegenerování nechá původní (platný) přehled.
        row.status = "ready" if previous_content else "failed"
        row.updated_at = now
        db.commit()
        _log(row, trigger, row.status)
        return row


def _log(row: DailyBriefing, trigger: str, status: str) -> None:
    logger.info(
        "briefing id=%s date=%s trigger=%s status=%s attempt=%s error=%s prompt_tokens=%s completion_tokens=%s "
        "total_tokens=%s latency_ms=%s snapshot_tokens=%s grounding_fixes=%s",
        row.id, row.briefing_date, trigger, status, row.attempts, row.error_category or "-", row.prompt_tokens,
        row.completion_tokens, row.total_tokens, row.latency_ms, row.snapshot_tokens, row.grounding_removed,
    )


def _notify(db: Session, row: DailyBriefing, content: dict, now: datetime) -> None:
    """Jedna notifikace na den (dedupe); starší přehledové notifikace se uzavřou. Web Push ji pak vezme
    stávající fronta doručení (Phase E), pokud je typ povolen."""
    key = f"briefing:{row.briefing_date.isoformat()}"
    try:
        if db.query(Notification.id).filter(Notification.dedupe_key == key).first():
            return
        for old in (db.query(Notification)
                    .filter(Notification.notification_type == "daily_briefing", Notification.resolved == False)  # noqa: E712
                    .all()):
            old.resolved = True
        _start, end = local_day_bounds_utc(row.briefing_date)
        db.add(Notification(
            area="briefing", title="☀️ Denní přehled", message=_clip(content.get("summary"), 280), severity="info",
            read=False, created_at=now, expires_at=end, notification_type="daily_briefing",
            source_type="daily_briefing", source_id=row.id, dedupe_key=key, last_triggered_at=now, resolved=False,
            action_url="/",
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("briefing notification failed %s", type(exc).__name__)


# ===== scheduler =====

def run_scheduled(db: Session, now: datetime | None = None, llm=None) -> str:
    """Zavolá se periodicky: vygeneruje dnešní přehled po nastaveném pražském čase, nejvýš jednou;
    po selhání ohraničeně znovu (podle kategorie chyby). Vrací stav pro log/testy."""
    if not briefing_enabled():
        return "disabled"
    now = now or utc_now()
    local = to_local(now)
    if local.time().replace(tzinfo=None) < briefing_time():
        return "not_yet"
    row = get_for_date(db, local.date())
    scheduled_at = datetime.combine(local.date(), briefing_time())
    late = local.replace(tzinfo=None) - scheduled_at > ON_TIME_WINDOW
    if row is None:
        generate(db, trigger="catchup" if late else "scheduler", now=now, llm=llm)
        return "generated"
    if row.status == "ready":
        return "exists"
    if row.status == "generating" and row.updated_at and now - row.updated_at < STALE_GENERATING:
        return "in_progress"
    if int(row.attempts or 0) >= MAX_SCHEDULER_ATTEMPTS:
        return "gave_up"
    if row.next_retry_at and now < row.next_retry_at:
        return "waiting"
    generate(db, trigger="retry", now=now, llm=llm)
    return "retried"


# ===== API výstup =====

def payload(db: Session, now: datetime | None = None) -> dict:
    now = now or utc_now()
    today = to_local(now).date()
    row = get_for_date(db, today)
    out = {
        "date": today.isoformat(),
        "enabled": briefing_enabled(),
        "scheduled_time": briefing_time().strftime("%H:%M"),
        "status": row.status if row else "missing",
        "briefing": None,
        "generated_at": None,
        "generated_label": None,
        "trigger": row.trigger if row else None,
        "regenerated_count": int(row.regenerated_count or 0) if row else 0,
        "error_category": row.error_category if row else None,
        "error_text": None,
        "fallback": None,
    }
    if row and row.error_category:
        out["error_text"] = ERROR_TEXT.get(row.error_category.split(":")[-1], ERROR_TEXT["internal"])
    if row and row.content and row.generated_at:
        out["briefing"] = json.loads(row.content)
        out["generated_at"] = row.generated_at.isoformat() + "Z"
        out["generated_label"] = to_local(row.generated_at).strftime("%H:%M")
    if out["briefing"] is None:
        # Bez AI: aspoň deterministický přehled (dnes / po termínu / brzy) – nikdy prázdná stránka.
        snap = build_snapshot(db, now)
        out["fallback"] = {k: v for k, v in snap.as_dict()["sections"].items() if k in ("today", "overdue", "soon")}
    return out
