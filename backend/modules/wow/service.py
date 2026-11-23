"""Doménová logika WoW (MRK-127) – sledované postavy a jejich snapshot z Blizzard API.

Jediná cesta zápisu (REST i hodinový krok). Synchronizace je deterministická: z odpovědi API se vezmou jen známá pole,
nic se nevymýšlí. Výpadek API nechá poslední známý stav (`sync_status` ukáže proč). Zvýšení levelu = doménová
událost `wow.character.level_up` (Aktivita / Co se změnilo) a přepočet automatických cílů.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from activity_service import log_activity
from domain_events import ActivityProjection, append_domain_event
from modules.wow import battlenet
from modules.wow.models import WowCharacter
from time_utils import utc_now

AREA = "wow"
MAX_CHARACTERS = 50
MIN_LEVEL, MAX_LEVEL = 1, 100
SYNC_EVERY = timedelta(hours=6)       # hodinový krok obnoví postavu nejvýš jednou za 6 h
SYNC_BATCH = 10                       # a nejvýš 10 postav za běh (limit API, krátký job)
NAME_RE = re.compile(r"^[^\W\d_]{2,12}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

GOAL_AT_TARGET = "wow_characters_at_target"
GOAL_MAX_LEVEL = "wow_max_level"
GOAL_SOURCES = (GOAL_AT_TARGET, GOAL_MAX_LEVEL)

SYNC_LABELS = {
    "pending": "čeká na načtení",
    "ok": "aktuální",
    "not_found": "postava nenalezena",
    "error": "API nedostupné",
}
ERROR_TEXT = {
    "not_configured": "WoW API není na serveru nastavené.",
    "not_found": "Postava nenalezena – zkontroluj jméno a realm.",
    "unauthorized": "Blizzard API odmítlo klíče serveru.",
    "rate_limited": "Blizzard API teď omezuje počet požadavků, zkus to za chvíli.",
    "unavailable": "Blizzard API teď neodpovídá.",
    "invalid_response": "Blizzard API vrátilo nečekanou odpověď.",
}


class WowError(Exception):
    """Neplatný požadavek (`status` = HTTP kód, `message` česky)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- normalizace vstupu ----------


def normalize_name(raw: str) -> tuple[str, str]:
    name = (raw or "").strip()
    if not NAME_RE.match(name):
        raise WowError(400, "Jméno postavy: 2–12 písmen, bez mezer a číslic.")
    return name[:1].upper() + name[1:].lower(), name.lower()


def realm_slug(raw: str) -> str:
    """„Pyrewood Village" / „pyrewood-village" → „pyrewood-village"; apostrofy pryč (Blizzard slug)."""
    s = (raw or "").strip().lower().replace("'", "").replace("’", "")
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or len(s) > 64 or not SLUG_RE.match(s):
        raise WowError(400, "Realm: název serveru (např. „Pyrewood Village“), jen písmena bez diakritiky, číslice a mezery.")
    return s


def normalize_target(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise WowError(400, "Cílový level musí být číslo.") from None
    if not MIN_LEVEL <= value <= MAX_LEVEL:
        raise WowError(400, f"Cílový level: {MIN_LEVEL}–{MAX_LEVEL}.")
    return value


# ---------- čtení ----------


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def professions(ch: WowCharacter) -> list[dict]:
    try:
        data = json.loads(ch.professions_json or "[]")
    except ValueError:
        return []
    return [p for p in data if isinstance(p, dict) and isinstance(p.get("name"), str)][:6]


def levels_to_go(ch: WowCharacter) -> int | None:
    if ch.target_level is None or ch.level is None:
        return None
    return max(0, ch.target_level - ch.level)


def character_dict(ch: WowCharacter) -> dict:
    return {
        "id": ch.id, "name": ch.name, "realm_slug": ch.realm_slug, "realm_name": ch.realm_name or ch.realm_slug,
        "level": ch.level, "target_level": ch.target_level, "levels_to_go": levels_to_go(ch),
        "at_target": ch.target_level is not None and ch.level is not None and ch.level >= ch.target_level,
        "class_name": ch.class_name, "race_name": ch.race_name, "faction": ch.faction, "active_spec": ch.active_spec,
        "item_level": ch.item_level, "professions": professions(ch), "last_login_at": _iso(ch.last_login_at),
        "sync_status": ch.sync_status, "sync_label": SYNC_LABELS.get(ch.sync_status, ch.sync_status),
        "last_synced_at": _iso(ch.last_synced_at),
    }


def all_characters(db: Session) -> list[WowCharacter]:
    # nejvyšší level nahoře, pak jméno – „kdo je nejdál" na první pohled
    rows = db.query(WowCharacter).limit(MAX_CHARACTERS).all()
    return sorted(rows, key=lambda c: (-(c.level or 0), c.name.lower(), c.id))


def summary(db: Session) -> dict:
    chars = all_characters(db)
    with_target = [c for c in chars if c.target_level is not None]
    return {
        "characters": len(chars),
        "max_level": max((c.level or 0 for c in chars), default=0),
        "with_target": len(with_target),
        "at_target": sum(1 for c in with_target if c.level is not None and c.level >= c.target_level),
    }


def overview(db: Session) -> dict:
    return {"config": battlenet.config_status(), "summary": summary(db),
            "characters": [character_dict(c) for c in all_characters(db)]}


def goal_value(db: Session, source: str) -> tuple[float, bool]:
    """Automatické cíle (goal_history_service): deterministicky z uložených snapshotů, bez API a bez LLM."""
    s = summary(db)
    if source == GOAL_AT_TARGET:
        return float(s["at_target"]), True
    if source == GOAL_MAX_LEVEL:
        return float(s["max_level"]), True
    return 0.0, False


def _get(db: Session, character_id: int) -> WowCharacter:
    ch = db.get(WowCharacter, character_id)
    if ch is None:
        raise WowError(404, "Postava neexistuje.")
    return ch


# ---------- synchronizace s API ----------


def _name(obj) -> str | None:
    if isinstance(obj, dict) and isinstance(obj.get("name"), str):
        return obj["name"][:40] or None
    return None


def _int(value, lo: int = 0, hi: int = 10_000) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and lo <= value <= hi else None


def parse_professions(data: dict | None) -> list[dict]:
    """Retail: tiers (poslední = aktuální expanze); Classic: skill_points přímo u profese."""
    out: list[dict] = []
    if not isinstance(data, dict):
        return out
    for group in ("primaries", "secondaries"):
        for p in data.get(group) or []:
            if not isinstance(p, dict):
                continue
            name = _name(p.get("profession"))
            if not name:
                continue
            tiers = [t for t in (p.get("tiers") or []) if isinstance(t, dict)]
            src = tiers[-1] if tiers else p
            out.append({"name": name, "skill": _int(src.get("skill_points")), "max": _int(src.get("max_skill_points")),
                        "secondary": group == "secondaries"})
    return out[:6]


def apply_profile(ch: WowCharacter, data: dict, prof: dict | None) -> None:
    level = _int(data.get("level"), 1, MAX_LEVEL)
    if level is None:
        raise battlenet.BattleNetError("invalid_response")
    if isinstance(data.get("name"), str) and NAME_RE.match(data["name"]):
        ch.name = data["name"]
    realm = data.get("realm")
    if _name(realm):
        ch.realm_name = _name(realm)
    ch.level = level
    ch.class_name = _name(data.get("character_class"))
    ch.race_name = _name(data.get("race"))
    ch.faction = _name(data.get("faction"))
    ch.active_spec = _name(data.get("active_spec"))
    ilvl = data.get("equipped_item_level", data.get("average_item_level"))
    ch.item_level = _int(ilvl, 0, 2000)
    ts = data.get("last_login_timestamp")
    ch.last_login_at = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)
                        if isinstance(ts, (int, float)) and ts > 0 else None)
    if prof is not None:
        ch.professions_json = json.dumps(parse_professions(prof), ensure_ascii=False)


def sync_character(db: Session, ch: WowCharacter, client: battlenet.Client | None, *, now: datetime | None = None,
                   user_context: str = "system") -> str:
    """Načte postavu z API do snapshotu. Vrací `ok` nebo kód chyby; nikdy nevyhazuje kvůli API."""
    now = now or utc_now()
    ch.last_attempt_at = now
    if client is None:
        return "not_configured"
    previous = ch.level
    try:
        data = client.character(ch.realm_slug, ch.name_key)
        prof = client.professions(ch.realm_slug, ch.name_key)
        apply_profile(ch, data, prof)
    except battlenet.BattleNetError as err:
        ch.sync_status = "not_found" if err.code == "not_found" else "error"
        return err.code
    ch.sync_status = "ok"
    ch.last_synced_at = now
    db.flush()
    if previous is not None and ch.level > previous:
        target = f" (cíl {ch.target_level})" if ch.target_level else ""
        append_domain_event(
            db, event_type="wow.character.level_up", aggregate_type="character", aggregate_id=ch.id, now=now,
            payload={"character_id": ch.id, "level": ch.level, "previous_level": previous,
                     "target_level": ch.target_level},
            activity=ActivityProjection(AREA, "level_up", f"{ch.name} – level {ch.level}{target}",
                                        entity_type="wow_character", entity_id=ch.id,
                                        delta={"level": {"old": previous, "new": ch.level}},
                                        user_context=user_context),
        )
    return "ok"


def _refresh_goals(db: Session, user_context: str) -> None:
    from goal_history_service import refresh_automatic_goals  # líně: goal_history importuje tento modul taky líně
    refresh_automatic_goals(db, set(GOAL_SOURCES), user_context=user_context)


def sync_one(db: Session, character_id: int, *, user_context: str = "manual") -> dict:
    ch = _get(db, character_id)
    result = sync_character(db, ch, battlenet.client(), user_context=user_context)
    if result == "ok":
        _refresh_goals(db, user_context)
    return {"result": result, "message": ERROR_TEXT.get(result), "character": character_dict(ch)}


def sync_due(db: Session, *, now: datetime | None = None, force: bool = False, user_context: str = "system") -> dict:
    """Hodinový krok (a „Obnovit vše"): postavy starší než SYNC_EVERY, nejvýš SYNC_BATCH. Bez klíčů nic nedělá."""
    now = now or utc_now()
    client = battlenet.client()
    if client is None:
        return {"synced": 0, "skipped": "not_configured"}
    due = [c for c in db.query(WowCharacter).all()
           if force or c.last_attempt_at is None or c.last_attempt_at <= now - SYNC_EVERY]
    due.sort(key=lambda c: c.last_attempt_at or datetime.min)
    results: dict[str, int] = {}
    for ch in due[:SYNC_BATCH]:
        code = sync_character(db, ch, client, now=now, user_context=user_context)
        results[code] = results.get(code, 0) + 1
        if code in ("unauthorized", "rate_limited"):
            break  # další pokusy by dopadly stejně
    if results.get("ok"):
        _refresh_goals(db, user_context)
    return {"synced": results.get("ok", 0), "results": results}


# ---------- zápisy ----------


def add_character(db: Session, name: str, realm: str, target_level=None, *, user_context: str = "manual") -> dict:
    display, key = normalize_name(name)
    slug = realm_slug(realm)
    target = normalize_target(target_level)
    if db.query(WowCharacter).count() >= MAX_CHARACTERS:
        raise WowError(400, f"Nejvýš {MAX_CHARACTERS} postav.")
    if db.query(WowCharacter).filter(WowCharacter.realm_slug == slug, WowCharacter.name_key == key).first():
        raise WowError(409, "Tuhle postavu už sleduješ.")
    ch = WowCharacter(name=display, name_key=key, realm_slug=slug, target_level=target, sync_status="pending",
                      created_at=utc_now())
    db.add(ch)
    db.flush()
    log_activity(db, AREA, "create", f"WoW postava: {display} ({slug})", entity_type="wow_character",
                 entity_id=ch.id, user_context=user_context, dedupe_key=f"wow:create:{uuid.uuid4().hex}")
    result = sync_character(db, ch, battlenet.client(), user_context=user_context)
    if result == "ok":
        _refresh_goals(db, user_context)
    return {"result": result, "message": ERROR_TEXT.get(result), "character": character_dict(ch)}


def set_target(db: Session, character_id: int, target_level, *, user_context: str = "manual") -> dict:
    ch = _get(db, character_id)
    target = normalize_target(target_level)
    if target != ch.target_level:
        old, ch.target_level = ch.target_level, target
        log_activity(db, AREA, "update", f"WoW {ch.name}: cílový level {target or '–'}", entity_type="wow_character",
                     entity_id=ch.id, delta={"target_level": {"old": old, "new": target}}, user_context=user_context,
                     dedupe_key=f"wow:update:{uuid.uuid4().hex}")
        _refresh_goals(db, user_context)
    return character_dict(ch)


def delete_character(db: Session, character_id: int, *, user_context: str = "manual") -> None:
    """Přestat sledovat – ve hře se nic nemění; level-up události v historii zůstávají."""
    ch = _get(db, character_id)
    log_activity(db, AREA, "delete", f"WoW postava odebrána: {ch.name} ({ch.realm_slug})", entity_type="wow_character",
                 entity_id=ch.id, delta={"level": ch.level, "target_level": ch.target_level},
                 user_context=user_context, dedupe_key=f"wow:delete:{uuid.uuid4().hex}")
    db.delete(ch)
    db.flush()
    _refresh_goals(db, user_context)
