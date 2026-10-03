"""Týdenní přehled (Roadmap 3.0 Phase G): jeden perzistentní přehled na pražský kalendářní týden.

Tok: deterministický snímek (`weekly_snapshot`: metriky, srovnání, položky, kandidáti odhadů) → jedno LLM
volání (strict JSON Schema, bez toolů a historie, reasoning low, strop výstupu) → grounding → `weekly_reviews`.
LLM jen vybírá a formuluje: každá položka odkazuje na `ref` ze snímku; čísla/data/jména v textu musí být ve
snímku; fakta nesmí obsahovat kauzální tvrzení; odhady jsou jen z připravených kandidátů a jejich jistotu
i podklad určuje snímek, ne model. Málo dat → deterministický přehled bez LLM.

Sémantika týdne: pondělí 00:00 → neděle 24:00 Europe/Prague, `week_start` = pondělí. Plánované generování
(default neděle 19:00) shrnuje týden „do teď"; srovnání je s předchozím týdnem ve stejném rozsahu. Když
přehled chybí (server neběžel), dožene se po startu celý minulý týden. Přehled pro další týden nikdy dřív.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, time as dtime, timedelta

from sqlalchemy import update as _sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from env_config import env_bool
from llm_budget import estimate_tokens
from models import Notification, WeeklyReview
from planner_guard import build_evidence, strict_text_problems
from structured_llm import StructuredLLMError, call_structured, clip, make_ref_stripper, parse_json_object
from structured_llm import request_params as _structured_params
from time_utils import local_to_utc, to_local, utc_now
from text_utils import WEEKDAYS_CZ
from weekly_snapshot import (
    CONFIDENCE_TEXT, Forecast, Metric, WeeklySnapshot, build_weekly_snapshot, plural, week_bounds_utc, week_label,
    week_start_for,
)

logger = logging.getLogger("standa_hub.weekly_review")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s [weekly] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# Strop výstupu (ne očekávaná spotřeba): plná odpověď ~700–1000 tokenů + nízké reasoning. Lekce z Phase F:
# reasoning tokeny se počítají do completion limitu, proto rezerva.
MAX_OUTPUT_TOKENS = 1600
REASONING_EFFORT = "low"
CAPS = {"wins": 4, "concerns": 4, "comparisons": 6, "next_week": 5, "forecasts": 3, "focus": 3}
MAX_SCHEDULER_ATTEMPTS = 4
STALE_GENERATING = timedelta(minutes=10)
ON_TIME_WINDOW = timedelta(hours=1)  # později = trigger „catchup"
MAX_DROP_RATIO = 0.5  # víc než polovina položek s neplatným odkazem → odpověď se odmítne
RETRY_DELAYS = {
    "daily_limit": timedelta(hours=3),
    "rate_limit": timedelta(minutes=15),
    "provider": timedelta(minutes=15),
    "invalid_response": timedelta(minutes=30),
    "grounding_rejected": timedelta(minutes=30),
    "internal": timedelta(minutes=30),
    "output_limit": timedelta(hours=6),
    "schema_error": timedelta(hours=1),
    "refused": timedelta(hours=6),
    "request_rejected": timedelta(hours=6),
}
ERROR_TEXT = {
    "daily_limit": "AI má vyčerpaný denní limit – zkusím to později (nebo ručně).",
    "rate_limit": "AI je teď přetížená – zkusím to za chvíli.",
    "provider": "AI služba neodpověděla – zkusím to později.",
    "invalid_response": "AI vrátila neplatnou odpověď – zkusím to znovu.",
    "grounding_rejected": "AI odpověď neodpovídala datům – zkusím to znovu.",
    "internal": "Interní chyba při sestavení přehledu.",
    "output_limit": "AI nestihla odpověď v limitu délky – zkusím to později.",
    "schema_error": "AI nedodržela formát odpovědi – zkusím to později.",
    "refused": "AI odmítla přehled vytvořit.",
    "request_rejected": "AI služba odmítla požadavek (nastavení) – zkusím to později.",
}
_DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_DAY_CZ = WEEKDAYS_CZ

SYSTEM_PROMPT = """You write the user's WEEKLY REVIEW in Standa Hub. The user message is a SNAPSHOT of real data for one Europe/Prague week (Monday-Sunday). Every metric, item and forecast candidate starts with a [ref].
Rules:
- Use ONLY the snapshot. Never invent tasks, dates, amounts, names, events or numbers. Do not calculate new numbers; use the metrics as given.
- Keep three things apart: FACTS (what happened), COMPARISONS (metric changes vs previous week), FORECASTS (estimates).
- Facts and comparisons state what the data shows. Never claim causes ("because", "due to", "kvůli", "protože", "díky").
- Forecasts: ONLY pick from the forecast candidates (forecast:* refs). You may shorten/rephrase the statement but keep it hedged ("může", "pokud trend vydrží"), keep its numbers, add nothing. If there are no candidates, return an empty list.
- Never talk about health, mood, motivation, stress, exam results that are not in the data, career or life outcomes. No motivational filler, no fake urgency.
- wins: things that clearly went well (metrics marked "lepší", completed items, progressed goals). concerns: things that went worse, stalled or are overdue. A ref may not be both a win and a concern.
- comparisons: metric:* refs only. next_week: items from PŘÍŠTÍ TÝDEN or metric:next_week_deadlines. focus: 1-3 most useful things to do next week (refs of items or metrics).
- Czech, short: headline max 10 words; summary 2-3 sentences; each text max 18 words. Empty lists are fine; at most 4 wins, 4 concerns, 6 comparisons, 5 next_week, 3 forecasts, 3 focus.
- ref is copied exactly from the snapshot, without brackets; never write refs inside text.
Answer with the JSON object defined by the response schema."""

_ITEM = {"type": "object", "additionalProperties": False, "required": ["ref", "text"],
         "properties": {"ref": {"type": "string"}, "text": {"type": "string"}}}
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "summary", "wins", "concerns", "comparisons", "next_week", "forecasts", "focus"],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "wins": {"type": "array", "items": _ITEM},
        "concerns": {"type": "array", "items": _ITEM},
        "comparisons": {"type": "array", "items": _ITEM},
        "next_week": {"type": "array", "items": _ITEM},
        "forecasts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["ref", "statement"],
            "properties": {"ref": {"type": "string"}, "statement": {"type": "string"}}}},
        "focus": {"type": "array", "items": _ITEM},
    },
}

_strip_refs = make_ref_stripper(("assignment", "exam", "reminder", "goal", "notification", "finance", "activity",
                                 "metric", "forecast"))
# Témata, o kterých data nic neříkají – v přehledu nikdy (fakta ani odhady).
_BANNED_RE = re.compile(
    r"zdrav|nemoc|nálad|motivac|stres|únav|vyhoř|depres|úzkost|psychi|sebevědom|emoc|kariér|"
    r"slož[íi]š|nesloží|neslož[íi]š|propadn|uspěj|neuspěj|selžeš|projdeš|neprojd|"
    r"\bhealth|\bmood|motivation|\bstress|burnout|anxiety|you will (?:fail|pass)|\bcareer", re.I)
_CAUSAL_RE = re.compile(
    r"\b(?:protože|kvůli|díky|v důsledku|způsobil\w*|zapříčin\w*|vedl\w* k|vedlo k|proto|"
    r"because|due to|caused|led to|thanks to)\b", re.I)
_CERTAIN_RE = re.compile(r"\b(?:určitě|jistě|zaručeně|stoprocentně|nevyhnutelně|definitely|certainly|surely)\b", re.I)


class WeeklyReviewError(StructuredLLMError):
    """Kategorie chyby přehledu (+ spotřeba i u nepovedené odpovědi)."""


class WeeklyReviewInProgress(Exception):
    pass


# ===== konfigurace =====

def review_enabled() -> bool:
    return env_bool("WEEKLY_REVIEW_ENABLED", True)


def review_time() -> dtime:
    raw = os.environ.get("WEEKLY_REVIEW_TIME", "19:00").strip()
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", raw)
    return dtime(int(m.group(1)), int(m.group(2))) if m else dtime(19, 0)


def review_day() -> int:
    """0 = pondělí … 6 = neděle (WEEKLY_REVIEW_DAY=MON…SUN, default SUN)."""
    return _DAYS.get(os.environ.get("WEEKLY_REVIEW_DAY", "SUN").strip().upper()[:3], 6)


def scheduled_at(week_start: date) -> datetime:
    """Plánovaný okamžik přehledu týdne (UTC) – pražský nástěnný čas, DST-safe."""
    return local_to_utc(datetime.combine(week_start + timedelta(days=review_day()), review_time()))


def due_week(now: datetime) -> date:
    """Týden, ke kterému teď patří „aktuální" přehled: tento týden po plánovaném čase, jinak minulý týden.
    Další týden nikdy (přehled se nevytvoří dřív)."""
    ws = week_start_for(to_local(now).date())
    return ws if now >= scheduled_at(ws) else ws - timedelta(days=7)


def request_params() -> dict:
    """Parametry jen pro Týdenní přehled (běžný AI chat je nepoužívá)."""
    return _structured_params("weekly_review", RESPONSE_SCHEMA, MAX_OUTPUT_TOKENS, REASONING_EFFORT)


# ===== zprávy pro LLM =====

def build_messages(snap: WeeklySnapshot) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": snap.render()}]


def estimate_request_tokens(snap: WeeklySnapshot) -> int:
    schema = estimate_tokens(json.dumps(RESPONSE_SCHEMA))  # provider schéma vkládá do promptu
    return sum(estimate_tokens(m["content"]) for m in build_messages(snap)) + schema + MAX_OUTPUT_TOKENS


def _call_llm(snap: WeeklySnapshot, llm=None) -> tuple[str, dict]:
    """llm(messages, max_tokens) -> (text, usage) je testovací háček; reálně structured_llm.call_structured."""
    if llm is not None:
        return llm(build_messages(snap), MAX_OUTPUT_TOKENS)
    try:
        return call_structured(build_messages(snap), request_params())
    except StructuredLLMError as exc:
        raise WeeklyReviewError(exc.category, exc.usage) from None


def _parse(text: str) -> dict:
    try:
        data = parse_json_object(text)
    except StructuredLLMError:
        raise WeeklyReviewError("invalid_response") from None
    if not isinstance(data.get("headline"), str) or not isinstance(data.get("summary"), str):
        raise WeeklyReviewError("invalid_response")
    for key in CAPS:
        value = data.get(key) or []
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise WeeklyReviewError("invalid_response")
        data[key] = value
    return data


# ===== tóny položek (co smí být „úspěch" a co „starost") =====

def _tone(snap: WeeklySnapshot, ref: str) -> str:
    src = snap.by_ref().get(ref)
    if isinstance(src, Metric):
        if src.trend == "better":
            return "positive"
        if src.trend == "worse" or (src.note and src.note.startswith("neobvykle")):
            return "negative"
        return "neutral"
    if isinstance(src, Forecast) or src is None:
        return "neutral"
    text = f"{src.when} {src.detail}"
    if any(k in text for k in ("dokončeno", "splněno", "složeno")) and "nesloženo" not in text:
        return "positive"
    if src.detail.startswith("+"):
        return "positive"
    if any(k in text for k in ("po termínu", "beze změny", "po cílovém datu", "nevyřízená", "nesloženo")) \
            or src.detail.startswith("−"):
        return "negative"
    return "neutral"


def _metric_text(m: Metric) -> str:
    if m.prev is None:
        return f"{m.label}: {m.as_dict()['cur_text']}"
    return f"{m.label}: {m.as_dict()['cur_text']} ({m.prev_label} {m.as_dict()['prev_text']}; {m.delta_text()})"


# ===== grounding =====

def ground(data: dict, snap: WeeklySnapshot) -> tuple[dict, int]:
    """Odkazy jen na snímek, tón musí sedět, text bez nepodložených čísel/dat/jmény, fakta bez kauzality,
    odhady jen z kandidátů (jistota a podklad ze snímku). Vrací (obsah, počet oprav)."""
    by_ref = snap.by_ref()
    evidence = build_evidence([snap.render()])
    fixes = dropped = submitted = 0
    used_tone: set[str] = set()

    def ok(text: str, *, fact: bool = True) -> bool:
        if not text or strict_text_problems(text, evidence) or _BANNED_RE.search(text):
            return False
        return not (fact and _CAUSAL_RE.search(text))

    def pick(key: str, allowed, fallback_text) -> list[dict]:
        nonlocal fixes, dropped, submitted
        out, seen = [], set()
        for entry in data.get(key) or []:
            submitted += 1
            ref = str(entry.get("ref") or "").strip().strip("[]")
            src = by_ref.get(ref)
            if src is None or ref in seen or not allowed(ref, src) or len(out) >= CAPS[key]:
                fixes += 1
                dropped += 1
                continue
            seen.add(ref)
            text = clip(_strip_refs(entry.get("text") or entry.get("statement")), 220)
            if not ok(text, fact=key != "forecasts"):
                fixes += int(bool(text))
                text = fallback_text(src)
            out.append({"ref": ref, "text": text, **_display(src)})
        return out

    def entity_text(src) -> str:
        return " · ".join(p for p in (src.label, src.when) if p)

    def label_text(src) -> str:
        return _metric_text(src) if isinstance(src, Metric) else entity_text(src)

    def win_ok(ref, src):
        return not isinstance(src, Forecast) and _tone(snap, ref) == "positive" and ref not in used_tone

    def concern_ok(ref, src):
        return not isinstance(src, Forecast) and _tone(snap, ref) == "negative" and ref not in used_tone

    wins = pick("wins", win_ok, label_text)
    used_tone |= {w["ref"] for w in wins}
    concerns = pick("concerns", concern_ok, label_text)
    comparisons = pick("comparisons", lambda r, s: isinstance(s, Metric) and s.prev is not None, label_text)
    next_refs = {i.ref for i in snap.sections.get("next_week", [])} | {"metric:next_week_deadlines"}
    next_week = pick("next_week", lambda r, s: r in next_refs, label_text)
    focus = pick("focus", lambda r, s: not isinstance(s, Forecast) and not r.startswith("activity:"), label_text)

    forecasts = []
    seen_f: set[str] = set()
    for entry in data.get("forecasts") or []:
        submitted += 1
        ref = str(entry.get("ref") or "").strip().strip("[]")
        f = by_ref.get(ref)
        if not isinstance(f, Forecast) or ref in seen_f or len(forecasts) >= CAPS["forecasts"]:
            fixes += 1
            dropped += 1
            continue
        seen_f.add(ref)
        statement = clip(_strip_refs(entry.get("statement")), 260)
        if not ok(statement, fact=False) or _CERTAIN_RE.search(statement):
            fixes += int(bool(statement))
            statement = f.statement
        forecasts.append(_forecast_display(f, statement, snap))

    headline = clip(_strip_refs(data.get("headline")), 90)
    if not ok(headline):
        fixes += 1
        headline = deterministic_headline(snap)
    summary = clip(_strip_refs(data.get("summary")), 500)
    if not ok(summary):
        fixes += 1
        summary = deterministic_summary(snap)

    if submitted >= 4 and dropped / submitted > MAX_DROP_RATIO:
        raise WeeklyReviewError("grounding_rejected")
    if not (wins or concerns or comparisons or next_week or forecasts):
        raise WeeklyReviewError("grounding_rejected")
    return {"headline": headline, "summary": summary, "wins": wins, "concerns": concerns,
            "comparisons": comparisons, "next_week": next_week, "forecasts": forecasts, "focus": focus}, fixes


def _display(src) -> dict:
    if isinstance(src, Metric):
        return {"kind": "metric", "url": src.url, "metric": src.as_dict()}
    return {"kind": src.kind, "url": src.url, "label": src.label, "when": src.when, "detail": src.detail}


def _forecast_display(f: Forecast, statement: str, snap: WeeklySnapshot) -> dict:
    by_ref = snap.by_ref()
    basis = []
    for ref in f.basis:
        src = by_ref.get(ref)
        if isinstance(src, Metric):
            basis.append(src.label)
        elif src is not None:
            basis.append(" · ".join(p for p in (src.label, src.when) if p))
    return {"ref": f.ref, "kind": "forecast", "statement": statement, "confidence": f.confidence,
            "confidence_text": CONFIDENCE_TEXT[f.confidence], "rule": f.rule, "basis": list(f.basis),
            "basis_labels": basis}


# ===== deterministický přehled (málo dat / bez AI) =====

def deterministic_headline(snap: WeeklySnapshot) -> str:
    if snap.is_quiet:
        return "Klidný týden – málo dat"
    return f"Týden {week_label(snap.week_start)}"


def deterministic_summary(snap: WeeklySnapshot) -> str:
    if snap.is_quiet:
        return ("Tento týden je v datech jen málo záznamů, takže přehled zůstává stručný – "
                "bez trendů a odhadů, které by data nepodložila.")
    better = sum(1 for m in snap.metrics if m.trend == "better")
    worse = sum(1 for m in snap.metrics if m.trend == "worse")
    nxt = len(snap.sections.get("next_week") or [])
    return (f"Oproti minulému týdnu: {better} {plural(better, 'ukazatel lepší', 'ukazatele lepší', 'ukazatelů lepších')}, "
            f"{worse} {plural(worse, 'horší', 'horší', 'horších')}. Na příští týden "
            f"{plural(nxt, 'je známý', 'jsou známé', 'je známo')} {nxt} {plural(nxt, 'závazek', 'závazky', 'závazků')}.")


def deterministic_content(snap: WeeklySnapshot) -> dict:
    metrics = [m for m in snap.metrics if m.prev is not None and (m.cur or m.prev)]
    wins = [m for m in metrics if m.trend == "better"][:CAPS["wins"]]
    concerns = [m for m in metrics if m.trend == "worse"][:CAPS["concerns"]]

    def row(src) -> dict:
        text = _metric_text(src) if isinstance(src, Metric) else " · ".join(p for p in (src.label, src.when) if p)
        return {"ref": src.ref, "text": text, **_display(src)}

    overdue = [i for i in snap.sections.get("school", []) if "po termínu" in i.when]
    return {
        "headline": deterministic_headline(snap),
        "summary": deterministic_summary(snap),
        "wins": [row(m) for m in wins],
        "concerns": ([row(m) for m in concerns] + [row(i) for i in overdue])[:CAPS["concerns"]],
        "comparisons": [row(m) for m in metrics][:CAPS["comparisons"]],
        "next_week": [row(i) for i in snap.sections.get("next_week", [])][:CAPS["next_week"]],
        "forecasts": [] if snap.is_quiet else
        [_forecast_display(f, f.statement, snap) for f in snap.forecasts][:CAPS["forecasts"]],
        "focus": [],
    }


# ===== perzistence a generování =====

def get_for_week(db: Session, week_start: date) -> WeeklyReview | None:
    return db.query(WeeklyReview).filter(WeeklyReview.week_start == week_start).first()


def _claim(db: Session, ws: date, trigger: str, now: datetime, *, regenerate: bool):
    row = get_for_week(db, ws)
    if row is None:
        row = WeeklyReview(week_start=ws, status="generating", trigger=trigger, attempts=1, grounding_fixes=0,
                           regenerated_count=0, created_at=now, updated_at=now)
        try:
            db.add(row)
            db.commit()
        except IntegrityError:
            db.rollback()
            return None, None  # souběžný běh ho založil
        return row, None
    if row.status == "generating" and row.updated_at and now - row.updated_at < STALE_GENERATING:
        raise WeeklyReviewInProgress()
    if row.status == "ready" and not regenerate:
        return None, None
    claimed = db.execute(
        _sql_update(WeeklyReview)
        .where(WeeklyReview.id == row.id, WeeklyReview.status == row.status, WeeklyReview.updated_at == row.updated_at)
        .values(status="generating", trigger=trigger, updated_at=now, attempts=WeeklyReview.attempts + 1)
    )
    db.commit()
    if claimed.rowcount != 1:
        raise WeeklyReviewInProgress()
    db.refresh(row)
    return row, (row.content if row.generated_at else None)


def generate(db: Session, *, trigger: str, now: datetime | None = None, regenerate: bool = False, llm=None,
             week_start: date | None = None) -> WeeklyReview | None:
    """Vygeneruje přehled pro „aktuální" týden (`due_week`), nebo pro předaný týden (jen scheduler catch-up).
    Snímek pokrývá týden do min(teď, konec týdne)."""
    now = now or utc_now()
    ws = week_start or due_week(now)
    if ws > due_week(now):
        raise ValueError("week not due yet")  # nikdy dřív, než je týden na řadě
    row, previous_content = _claim(db, ws, trigger, now, regenerate=regenerate)
    if row is None:
        return get_for_week(db, ws)
    was_ready = row.generated_at is not None
    try:
        _ws_start, week_end = week_bounds_utc(ws)
        cutoff = min(now, week_end)
        snap = build_weekly_snapshot(db, ws, cutoff)
        if snap.is_quiet:
            content, fixes = deterministic_content(snap), 0
            usage = {"model": "deterministic", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                     "latency_ms": 0}
        else:
            text, usage = _call_llm(snap, llm)
            content, fixes = ground(_parse(text), snap)
        content.update({"quiet": snap.is_quiet, "week_start": ws.isoformat(), "partial": snap.partial,
                        "period_end": snap.period_end.isoformat() + "Z", "deterministic": snap.is_quiet})
        row.status, row.error_category, row.next_retry_at = "ready", None, None
        row.period_end = snap.period_end
        row.content = json.dumps(content, ensure_ascii=False)
        row.snapshot_hash, row.snapshot_tokens = snap.source_hash(), snap.tokens
        row.model = (usage.get("model") or "")[:100]
        row.prompt_tokens, row.completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        row.total_tokens, row.latency_ms = usage.get("total_tokens"), usage.get("latency_ms")
        row.grounding_fixes = fixes
        row.generated_at = now
        row.first_generated_at = row.first_generated_at or now
        if was_ready:
            row.regenerated_count = int(row.regenerated_count or 0) + 1
        row.updated_at = now
        db.commit()
        if trigger != "manual":
            _notify(db, row, content, now)
        _log(row, trigger, "ready", usage.get("reasoning_tokens"))
        return row
    except Exception as exc:  # noqa: BLE001 - selhání přehledu nesmí rozbít nic dalšího
        db.rollback()
        category = exc.category if isinstance(exc, StructuredLLMError) else "internal"
        if not isinstance(exc, StructuredLLMError):
            logger.warning("weekly review internal error %s", type(exc).__name__)
        row = db.get(WeeklyReview, row.id)
        failed_usage = getattr(exc, "usage", None)
        if failed_usage and not previous_content:
            row.prompt_tokens, row.completion_tokens = failed_usage.get("prompt_tokens"), failed_usage.get("completion_tokens")
            row.total_tokens, row.latency_ms = failed_usage.get("total_tokens"), failed_usage.get("latency_ms")
        row.error_category = category if not previous_content else f"regenerate_failed:{category}"
        row.next_retry_at = now + RETRY_DELAYS.get(category, timedelta(minutes=30))
        row.status = "ready" if previous_content else "failed"  # nepovedené přegenerování nechá platný přehled
        row.updated_at = now
        db.commit()
        _log(row, trigger, row.status, (failed_usage or {}).get("reasoning_tokens"))
        return row


def _log(row: WeeklyReview, trigger: str, status: str, reasoning_tokens: int | None = None) -> None:
    logger.info(
        "weekly_review id=%s week_start=%s trigger=%s status=%s attempt=%s error=%s prompt_tokens=%s "
        "completion_tokens=%s reasoning_tokens=%s total_tokens=%s latency_ms=%s snapshot_tokens=%s grounding_fixes=%s",
        row.id, row.week_start, trigger, status, row.attempts, row.error_category or "-", row.prompt_tokens,
        row.completion_tokens, reasoning_tokens if reasoning_tokens is not None else "-", row.total_tokens,
        row.latency_ms, row.snapshot_tokens, row.grounding_fixes,
    )


def _notify(db: Session, row: WeeklyReview, content: dict, now: datetime) -> None:
    """Jedna notifikace na týden (dedupe); starší se uzavřou. Web Push ji vezme fronta z Phase E
    (`delivery_service.deliverable_types`, WEEKLY_REVIEW_PUSH)."""
    key = f"weekly_review:{row.week_start.isoformat()}"
    try:
        if db.query(Notification.id).filter(Notification.dedupe_key == key).first():
            return
        for old in (db.query(Notification)
                    .filter(Notification.notification_type == "weekly_review", Notification.resolved == False)  # noqa: E712
                    .all()):
            old.resolved = True
        message = clip(f"{content.get('headline') or ''} – {content.get('summary') or ''}".strip(" –"), 280)
        db.add(Notification(
            area="review", title="📅 Týdenní přehled", message=message, severity="info", read=False,
            created_at=now, expires_at=now + timedelta(days=7), notification_type="weekly_review",
            source_type="weekly_review", source_id=row.id, dedupe_key=key, last_triggered_at=now, resolved=False,
            action_url="/review",
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("weekly review notification failed %s", type(exc).__name__)


# ===== scheduler =====

def run_scheduled(db: Session, now: datetime | None = None, llm=None) -> str:
    """Periodicky: po plánovaném čase vygeneruje přehled tohoto týdne (nejvýš jednou); před ním dožene
    chybějící přehled minulého týdne (celý týden). Po selhání ohraničeně znovu. Vrací stav pro log/testy."""
    if not review_enabled():
        return "disabled"
    now = now or utc_now()
    ws = due_week(now)
    this_week = week_start_for(to_local(now).date())
    row = get_for_week(db, ws)
    if row is None:
        late = ws != this_week or now - scheduled_at(ws) > ON_TIME_WINDOW
        generate(db, trigger="catchup" if late else "scheduler", now=now, llm=llm, week_start=ws)
        return "generated"
    if row.status == "ready":
        return "exists"
    if row.status == "generating" and row.updated_at and now - row.updated_at < STALE_GENERATING:
        return "in_progress"
    if int(row.attempts or 0) >= MAX_SCHEDULER_ATTEMPTS:
        return "gave_up"
    if row.next_retry_at and now < row.next_retry_at:
        return "waiting"
    generate(db, trigger="retry", now=now, llm=llm, week_start=ws)
    return "retried"


# ===== API výstup =====

def _clean_visible(content: dict) -> dict:
    out = dict(content)
    for key in ("headline", "summary"):
        if isinstance(out.get(key), str):
            out[key] = _strip_refs(out[key])
    for key in CAPS:
        out[key] = [{**i, **{f: _strip_refs(i[f]) for f in ("text", "statement") if isinstance(i.get(f), str)}}
                    for i in out.get(key) or [] if isinstance(i, dict)]
    return out


def schedule_label() -> str:
    return f"{_DAY_CZ[review_day()]} {review_time():%H:%M}"


def week_payload(db: Session, ws: date, now: datetime | None = None, *, with_fallback: bool = True) -> dict:
    now = now or utc_now()
    row = get_for_week(db, ws)
    current = due_week(now)
    out = {
        "week_start": ws.isoformat(),
        "week_label": week_label(ws),
        "is_current": ws == current,
        "can_generate": ws == current,
        "enabled": review_enabled(),
        "schedule_label": schedule_label(),
        "scheduled_at": scheduled_at(ws).isoformat() + "Z",
        "status": row.status if row else "missing",
        "review": None,
        "generated_at": None,
        "generated_label": None,
        "period_end_label": None,
        "trigger": row.trigger if row else None,
        "regenerated_count": int(row.regenerated_count or 0) if row else 0,
        "error_category": row.error_category if row else None,
        "error_text": None,
        "fallback": None,
    }
    if row and row.error_category:
        out["error_text"] = ERROR_TEXT.get(row.error_category.split(":")[-1], ERROR_TEXT["internal"])
    if row and row.content and row.generated_at:
        out["review"] = _clean_visible(json.loads(row.content))
        out["generated_at"] = row.generated_at.isoformat() + "Z"
        local = to_local(row.generated_at)
        out["generated_label"] = f"{_DAY_CZ[local.weekday()]} {local.day}. {local.month}. {local:%H:%M}"
        if row.period_end:
            pe = to_local(row.period_end)
            out["period_end_label"] = f"{_DAY_CZ[pe.weekday()]} {pe.day}. {pe.month}. {pe:%H:%M}"
    if out["review"] is None and with_fallback and ws == current:
        _s, week_end = week_bounds_utc(ws)
        snap = build_weekly_snapshot(db, ws, min(now, week_end))
        out["fallback"] = deterministic_content(snap)
    return out


def payload(db: Session, now: datetime | None = None) -> dict:
    now = now or utc_now()
    return week_payload(db, due_week(now), now)


def history(db: Session, limit: int = 26) -> list[dict]:
    rows = db.query(WeeklyReview).order_by(WeeklyReview.week_start.desc()).limit(limit).all()
    out = []
    for r in rows:
        headline = None
        if r.content and r.generated_at:
            try:
                headline = _strip_refs(json.loads(r.content).get("headline") or "") or None
            except ValueError:
                headline = None
        out.append({"week_start": r.week_start.isoformat(), "week_label": week_label(r.week_start),
                    "status": r.status, "headline": headline})
    return out
