"""World of Tanks – průběh, splnění grindů a milníky (Game Enrichment B). Deterministické, bez LLM.

Životní cyklus grindu: active/paused → (výslovné „Splněno") → completed. Splnění:
- podmíněný UPDATE (jen z nesplněného stavu) → nejvýš jedno splnění i při dvojkliku / souběhu,
- xp_remaining = 0 (průběh 100 %), řádek grindu zůstává (status completed),
- nový řádek `wot_grind_completions` = trvalá historie (přežije smazání nebo znovuzaložení grindu),
- záznam v Aktivitě s `delta.event = "wot_grind_completed"` a stabilním dedupe klíčem podle id splnění.
Budoucí gamifikace čte jen `wot_grind_completions` (nebo tyto řádky Aktivity) – žádné XP, odznaky ani event bus teď.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

import media_storage
from activity_service import log_activity
from goal_history_service import WOT_ACE_MASTERY_SOURCE, refresh_automatic_goals
from models import WotGrind, WotGrindCompletion, WotMilestone, WotMilestoneScreenshot, WotReplay
from time_utils import utc_now

COMPLETION_EVENT = "wot_grind_completed"
SCREENSHOT_FOLDER = "wot-screenshots"
MAX_SCREENSHOTS = 20
MASTERY_VALUES = ("ace", "first", "second", "third")
MILESTONE_TYPES = ("mastery",)


class WotError(ValueError):
    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


# ---------- grindy ----------

def grind_progress(g: WotGrind) -> int | None:
    """Průběh v % podle výchozího zbývajícího XP; splněný = 100; bez základu = None (neznámo, nic se nevymýšlí)."""
    if (g.status or "").lower() == "completed":
        return 100
    start = float(g.xp_start or 0)
    if start <= 0:
        return None
    remaining = max(0.0, float(g.xp_remaining or 0))
    return max(0, min(100, round((start - remaining) / start * 100)))


def serialize_grind(g: WotGrind) -> dict:
    return {
        "id": g.id,
        "tank": g.tank,
        "xp_remaining": g.xp_remaining,
        "priority": g.priority,
        "status": g.status,
        "xp_start": g.xp_start,
        "started_at": _iso(g.started_at),
        "progress": grind_progress(g),
    }


def serialize_completion(c: WotGrindCompletion) -> dict:
    days = None
    if c.started_at and c.completed_at and c.completed_at >= c.started_at:
        days = (c.completed_at - c.started_at).days
    return {
        "id": f"completion:{c.id}",
        "completion_id": c.id,
        "grind_id": c.grind_id,
        "tank": c.tank,
        "completed_at": _iso(c.completed_at),
        "started_at": _iso(c.started_at),
        "xp_start": c.xp_start,
        "xp_remaining_before": c.xp_remaining_before,
        "duration_days": days,
        "source": c.source,
        "legacy": False,
    }


def ensure_new_grind_status(status: str | None) -> None:
    """Nový grind nesmí vzniknout rovnou splněný – zmizel by bez historie i události. Splnění jde jen přes
    complete_grind nebo úpravu existujícího grindu (record_completion). Platí pro formulář, API i AI nástroj."""
    if (status or "").strip().lower() == "completed":
        raise WotError("Nový grind nejde vytvořit jako splněný – splň ho tlačítkem Splněno.", status=422, code="invalid_status")


def record_completion(db: Session, g: WotGrind, *, source: str, xp_before: float | None, now: datetime) -> WotGrindCompletion:
    """Zapíše historii + Aktivitu pro grind, který se právě stal splněným (volající zajistil přechod stavu)."""
    completion = WotGrindCompletion(
        grind_id=g.id, tank=g.tank, xp_start=g.xp_start, xp_remaining_before=xp_before,
        started_at=g.started_at, completed_at=now, source=source,
    )
    db.add(completion)
    db.flush()
    log_activity(
        db, "wot", "complete", f"Grind splněn: {g.tank}",
        entity_type="WotGrind", entity_id=g.id,
        delta={"event": COMPLETION_EVENT, "completion_id": completion.id, "tank": g.tank,
               "xp_start": g.xp_start, "xp_remaining_before": xp_before},
        user_context=source, dedupe_key=f"{COMPLETION_EVENT}:{completion.id}",
    )
    return completion


def complete_grind(db: Session, grind_id: int, *, source: str = "manual", now: datetime | None = None) -> tuple[WotGrind, WotGrindCompletion]:
    """Výslovné „Splněno". Nejvýš jednou: podmíněný UPDATE ze stavu ≠ completed (dvojklik / jiná záložka → 409)."""
    now = now or utc_now()
    g = db.get(WotGrind, grind_id)
    if g is None:
        raise WotError("Grind neexistuje.", status=404, code="not_found")
    if (g.status or "").lower() == "completed":
        raise WotError("Grind už je splněný.", status=409, code="already_completed")
    xp_before = g.xp_remaining
    flipped = db.execute(
        update(WotGrind)
        .where(WotGrind.id == grind_id, WotGrind.status != "completed")
        .values(status="completed", xp_remaining=0)
        .execution_options(synchronize_session=False)
    )
    if flipped.rowcount != 1:
        db.rollback()
        raise WotError("Grind už je splněný.", status=409, code="already_completed")
    db.refresh(g)
    completion = record_completion(db, g, source=source, xp_before=xp_before, now=now)
    return g, completion


def detach_completions(db: Session, grind_id: int) -> None:
    """Před smazáním grindu: historie splnění zůstane, jen bez odkazu (i na SQLite bez vynucených FK)."""
    db.query(WotGrindCompletion).filter(WotGrindCompletion.grind_id == grind_id).update(
        {WotGrindCompletion.grind_id: None}, synchronize_session=False)


def list_completions(db: Session) -> list[dict]:
    """Historie splněných grindů (nejnovější první). Grindy označené „Dokončeno" dřív / jinou cestou bez záznamu
    splnění se ukážou taky – s neznámým datem (`legacy`), nic se nedopočítává."""
    rows = db.query(WotGrindCompletion).order_by(WotGrindCompletion.completed_at.desc(), WotGrindCompletion.id.desc()).all()
    out = [serialize_completion(c) for c in rows]
    recorded = {c.grind_id for c in rows if c.grind_id is not None}
    for g in db.query(WotGrind).filter(WotGrind.status == "completed").order_by(WotGrind.id).all():
        if g.id in recorded:
            continue
        out.append({
            "id": f"grind:{g.id}", "completion_id": None, "grind_id": g.id, "tank": g.tank, "completed_at": None,
            "started_at": _iso(g.started_at), "xp_start": g.xp_start, "xp_remaining_before": None, "duration_days": None,
            "source": "legacy", "legacy": True,
        })
    return out


# ---------- milníky ----------

FIELD_LIMITS = {"damage": 100_000, "assist": 100_000, "kills": 15, "base_xp": 10_000}


def _clean_text(value, field: str, max_len: int, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise WotError(f"Vyplň pole {field}.", code=f"invalid_{field}")
        return None
    s = " ".join(str(value).split()) if field != "notes" else str(value).strip()
    if not s:
        if required:
            raise WotError(f"Vyplň pole {field}.", code=f"invalid_{field}")
        return None
    if len(s) > max_len:
        raise WotError(f"Pole {field} je moc dlouhé (max. {max_len}).", code=f"invalid_{field}")
    return s


def validate_milestone(data: dict, *, partial: bool = False, today: date | None = None) -> dict:
    """Ověří a normalizuje vstup. `partial` = PATCH (jen poslaná pole). Povinný je jen tank."""
    today = today or utc_now().date()
    out: dict = {}
    if not partial or "tank" in data:
        out["tank"] = _clean_text(data.get("tank"), "tank", 100, required=True)
    for f, n in (("map_name", 100), ("notes", 2000)):
        if not partial or f in data:
            out[f] = _clean_text(data.get(f), f, n)
    for f, limit in FIELD_LIMITS.items():
        if not partial or f in data:
            v = data.get(f)
            if v is None or v == "":
                out[f] = None
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 0 <= v <= limit:
                raise WotError(f"Pole {f} musí být celé číslo 0–{limit}.", code=f"invalid_{f}")
            out[f] = int(v)
    if not partial or "mastery" in data:
        m = data.get("mastery")
        if m not in (None, "") and m not in MASTERY_VALUES:
            raise WotError("Neznámý stupeň odznaku zvládnutí.", code="invalid_mastery")
        out["mastery"] = m or None
    if not partial or "milestone_type" in data:
        t = data.get("milestone_type") or "mastery"
        if t not in MILESTONE_TYPES:
            raise WotError("Neznámý druh milníku.", code="invalid_milestone_type")
        out["milestone_type"] = t
    if not partial or "played_on" in data:
        raw = data.get("played_on")
        if raw in (None, ""):
            out["played_on"] = None
        else:
            try:
                d = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
            except ValueError:
                raise WotError("Datum musí být ve tvaru RRRR-MM-DD.", code="invalid_played_on") from None
            if d > today or d.year < 2010:
                raise WotError("Datum bitvy nemůže být v budoucnu.", code="invalid_played_on")
            out["played_on"] = d
    if not partial or "favorite" in data:
        out["favorite"] = bool(data.get("favorite", False))
    return out


def serialize_screenshot(s: WotMilestoneScreenshot) -> dict:
    return {
        "id": s.id,
        "url": f"/wot/screenshots/{s.id}/file",
        "caption": s.caption,
        "original_name": s.original_name,
        "content_type": s.content_type,
        "size_bytes": s.size_bytes,
        "position": s.position,
        "created_at": _iso(s.created_at),
    }


def serialize_milestone(m: WotMilestone) -> dict:
    return {
        "id": m.id,
        "milestone_type": m.milestone_type,
        "mastery": m.mastery,
        "tank": m.tank,
        "map_name": m.map_name,
        "played_on": m.played_on.isoformat() if m.played_on else None,
        "damage": m.damage,
        "assist": m.assist,
        "kills": m.kills,
        "base_xp": m.base_xp,
        "notes": m.notes,
        "favorite": bool(m.favorite),
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
        "screenshots": [serialize_screenshot(s) for s in sorted(m.screenshots, key=lambda s: (s.position, s.id))],
        # Game Enrichment C: propojené replaye (jen id – detail je v knihovně replayů)
        "replay_ids": sorted(r.id for r in m.replays),
    }


def list_milestones(db: Session) -> list[dict]:
    """Nejnovější bitvy první (podle data bitvy, pak založení)."""
    rows = db.query(WotMilestone).all()
    rows.sort(key=lambda m: (m.played_on or date.min, m.created_at or datetime.min, m.id), reverse=True)
    return [serialize_milestone(m) for m in rows]


def _label(m: WotMilestone) -> str:
    return f"{m.tank}" + (f" · {m.map_name}" if m.map_name else "")


def _refresh_mastery_goals(db: Session, user_context: str) -> None:
    """MRK-82: a goal like "50 M-ek" follows every milestone create/update/delete in the same transaction."""
    db.flush()
    refresh_automatic_goals(db, {WOT_ACE_MASTERY_SOURCE}, user_context=user_context)


def create_milestone(db: Session, data: dict, *, user_context: str = "manual") -> WotMilestone:
    fields = validate_milestone(data)
    m = WotMilestone(**fields)
    now = utc_now()
    m.created_at = m.updated_at = now
    db.add(m)
    db.flush()
    log_activity(db, "wot", "create", f"Nový milník: {_label(m)}", entity_type="WotMilestone", entity_id=m.id,
                 user_context=user_context)
    _refresh_mastery_goals(db, user_context)
    return m


def get_milestone(db: Session, milestone_id: int) -> WotMilestone:
    m = db.get(WotMilestone, milestone_id)
    if m is None:
        raise WotError("Milník neexistuje.", status=404, code="not_found")
    return m


def update_milestone(db: Session, milestone_id: int, data: dict, *, user_context: str = "manual") -> WotMilestone:
    m = get_milestone(db, milestone_id)
    for k, v in validate_milestone(data, partial=True).items():
        setattr(m, k, v)
    m.updated_at = utc_now()
    log_activity(db, "wot", "update", f"Milník upraven: {_label(m)}", entity_type="WotMilestone", entity_id=m.id,
                 user_context=user_context, dedupe_key=f"wot-milestone-update:{m.id}:{m.updated_at.isoformat()}")
    _refresh_mastery_goals(db, user_context)
    return m


def delete_milestone(db: Session, milestone_id: int, *, user_context: str = "manual") -> list[str]:
    """Smaže milník i metadata screenshotů; vrací uložené názvy souborů – smažou se AŽ po commitu."""
    m = get_milestone(db, milestone_id)
    files = [s.stored_name for s in m.screenshots]
    # propojené replaye zůstávají, jen bez odkazu (SQLite ON DELETE SET NULL nevynucuje)
    db.query(WotReplay).filter(WotReplay.linked_milestone_id == m.id).update(
        {WotReplay.linked_milestone_id: None}, synchronize_session=False)
    log_activity(db, "wot", "delete", f"Milník smazán: {_label(m)}", entity_type="WotMilestone", entity_id=m.id,
                 user_context=user_context)
    db.delete(m)
    _refresh_mastery_goals(db, user_context)
    return files


def add_screenshot(db: Session, milestone_id: int, data: bytes, original_name: str | None, caption: str | None) -> WotMilestoneScreenshot:
    m = get_milestone(db, milestone_id)
    if len(m.screenshots) >= MAX_SCREENSHOTS:
        raise WotError(f"K jednomu milníku jde uložit nejvýš {MAX_SCREENSHOTS} screenshotů.", code="too_many")
    cap = _clean_text(caption, "caption", 300)
    try:
        stored = media_storage.save_image(SCREENSHOT_FOLDER, data, original_name)
    except media_storage.MediaError as exc:
        raise WotError(str(exc), status=exc.status, code="invalid_file") from None
    shot = WotMilestoneScreenshot(
        milestone_id=m.id, stored_name=stored.stored_name, original_name=media_storage.clean_original_name(original_name),
        content_type=stored.content_type, size_bytes=stored.size_bytes, caption=cap,
        position=max((s.position for s in m.screenshots), default=-1) + 1, created_at=utc_now(),
    )
    db.add(shot)
    m.updated_at = utc_now()
    db.flush()
    log_activity(db, "wot", "update", f"Screenshot přidán: {_label(m)}", entity_type="WotMilestone", entity_id=m.id,
                 user_context="manual", dedupe_key=f"wot-screenshot-add:{shot.id}")
    return shot


def get_screenshot(db: Session, screenshot_id: int) -> WotMilestoneScreenshot:
    s = db.get(WotMilestoneScreenshot, screenshot_id)
    if s is None:
        raise WotError("Screenshot neexistuje.", status=404, code="not_found")
    return s


def update_screenshot(db: Session, screenshot_id: int, data: dict) -> WotMilestoneScreenshot:
    s = get_screenshot(db, screenshot_id)
    if "caption" in data:
        s.caption = _clean_text(data.get("caption"), "caption", 300)
    if "position" in data:
        pos = data.get("position")
        if isinstance(pos, bool) or not isinstance(pos, int) or not 0 <= pos < MAX_SCREENSHOTS:
            raise WotError("Neplatné pořadí.", code="invalid_position")
        siblings = sorted((x for x in s.milestone.screenshots if x.id != s.id), key=lambda x: (x.position, x.id))
        siblings.insert(min(pos, len(siblings)), s)
        for i, x in enumerate(siblings):
            x.position = i
    return s


def delete_screenshot(db: Session, screenshot_id: int) -> str:
    """Smaže metadata; vrací uložený název souboru (soubor se maže až po commitu)."""
    s = get_screenshot(db, screenshot_id)
    name = s.stored_name
    milestone = s.milestone
    log_activity(db, "wot", "update", f"Screenshot smazán: {_label(milestone)}", entity_type="WotMilestone",
                 entity_id=milestone.id, user_context="manual", dedupe_key=f"wot-screenshot-delete:{s.id}")
    db.delete(s)
    return name
