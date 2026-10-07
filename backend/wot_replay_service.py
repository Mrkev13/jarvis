"""Knihovna replayů WoT (Game Enrichment C). Deterministické, bez LLM.

- Originální .wotreplay se uloží beze změny přes media_storage (MEDIA_DIR/wot-replays, serverový název), metadata v DB.
- Duplicita = stejný SHA-256 obsahu (ne název souboru) → 409 `duplicate` s id existujícího replaye; nic se neuloží.
- Parser (replay_parser) jen předvyplní pole; selhání parseru ≠ selhání uploadu (kromě souboru, který replay vůbec není).
- Vše jde ručně opravit; ruční úprava metadat se do Aktivity nepíše (jen nahrání, smazání a propojení s milníkem).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, time, timezone

from sqlalchemy.orm import Session

import media_storage
from activity_service import log_activity
from env_config import env_int
from models import WotMilestone, WotReplay
from replay_parser import STATUSES, parse_replay
from time_utils import APP_TZ, to_local, utc_now
from wot_service import FIELD_LIMITS, MASTERY_VALUES, WotError, _clean_text, _iso, create_milestone, serialize_screenshot

REPLAY_FOLDER = "wot-replays"
REPLAY_EXT = ".wotreplay"
MAX_BYTES = min(env_int("WOT_REPLAY_MAX_MB", 50, minimum=1), 200) * 1024 * 1024
PRESET_TAGS = ("mko", "carry", "spotting", "record", "mistake", "fun", "close-game")
MAX_TAGS = 8
_TAG_RE = re.compile(r"^[\w][\w\- ]{0,23}$")
BATTLE_RESULTS = ("win", "loss", "draw")
SORTS = ("played_desc", "played_asc", "uploaded_desc")
EVENTS = {"uploaded": "replay_uploaded", "deleted": "replay_deleted", "linked": "replay_linked_to_milestone"}


class DuplicateReplay(WotError):
    def __init__(self, replay_id: int):
        super().__init__("Tenhle replay už v knihovně je.", status=409, code="duplicate")
        self.replay_id = replay_id


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_tag(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    tag = " ".join(raw.strip().lower().split())
    return tag if _TAG_RE.fullmatch(tag) else None


def _clean_tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WotError("Štítky musí být seznam.", code="invalid_tags")
    out: list[str] = []
    for raw in value:
        tag = normalize_tag(raw)
        if tag is None:
            raise WotError("Štítek smí mít 1–24 znaků (písmena, číslice, mezera, pomlčka).", code="invalid_tags")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise WotError(f"Nejvýš {MAX_TAGS} štítků.", code="invalid_tags")
    return out


def _played_at(raw, today: date) -> datetime | None:
    """Datum „RRRR-MM-DD“ (ruční úprava → poledne v Praze, ať se den neposune) nebo ISO čas (UTC)."""
    if raw in (None, ""):
        return None
    try:
        if isinstance(raw, str) and len(raw) == 10:
            d = date.fromisoformat(raw)
            value = datetime.combine(d, time(12, 0), APP_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        else:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if value.tzinfo:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise WotError("Datum musí být ve tvaru RRRR-MM-DD.", code="invalid_played_at") from None
    if value.date() > today or value.year < 2010:
        raise WotError("Datum bitvy nemůže být v budoucnu.", code="invalid_played_at")
    return value


def validate_meta(data: dict, *, today: date | None = None) -> dict:
    """PATCH – jen poslaná pole. Žádné pole není povinné (replay je platný i bez metadat)."""
    today = today or utc_now().date()
    out: dict = {}
    for f, n in (("tank_name", 100), ("map_name", 100), ("notes", 2000)):
        if f in data:
            out[f] = _clean_text(data.get(f), f, n)
    for f, limit in FIELD_LIMITS.items():
        if f in data:
            v = data.get(f)
            if v is None or v == "":
                out[f] = None
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 0 <= v <= limit:
                raise WotError(f"Pole {f} musí být celé číslo 0–{limit}.", code=f"invalid_{f}")
            else:
                out[f] = int(v)
    if "mastery" in data:
        m = data.get("mastery")
        if m not in (None, "") and m not in MASTERY_VALUES:
            raise WotError("Neznámý stupeň odznaku zvládnutí.", code="invalid_mastery")
        out["mastery"] = m or None
    if "battle_result" in data:
        r = data.get("battle_result")
        if r not in (None, "") and r not in BATTLE_RESULTS:
            raise WotError("Výsledek musí být výhra, prohra nebo remíza.", code="invalid_battle_result")
        out["battle_result"] = r or None
    if "played_at" in data:
        out["played_at"] = _played_at(data.get("played_at"), today)
    if "favorite" in data:
        out["favorite"] = bool(data.get("favorite"))
    if "tags" in data:
        out["tags"] = _clean_tags(data.get("tags"))
    if "linked_milestone_id" in data:
        mid = data.get("linked_milestone_id")
        if mid is not None and (isinstance(mid, bool) or not isinstance(mid, int) or mid < 1):
            raise WotError("Neplatný milník.", code="invalid_linked_milestone_id")
        out["linked_milestone_id"] = mid
    return out


def _milestone_brief(m: WotMilestone | None) -> dict | None:
    if m is None:
        return None
    return {
        "id": m.id, "tank": m.tank, "mastery": m.mastery, "map_name": m.map_name,
        "played_on": m.played_on.isoformat() if m.played_on else None,
        "screenshots": [serialize_screenshot(s) for s in sorted(m.screenshots, key=lambda s: (s.position, s.id))],
    }


def serialize_replay(r: WotReplay) -> dict:
    return {
        "id": r.id,
        "original_filename": r.original_filename,
        "file_size": r.file_size,
        "sha256": r.sha256,
        "uploaded_at": _iso(r.uploaded_at),
        "played_at": _iso(r.played_at),
        "tank_name": r.tank_name,
        "tank_tag": r.tank_tag,
        "map_name": r.map_name,
        "damage": r.damage,
        "assist": r.assist,
        "kills": r.kills,
        "base_xp": r.base_xp,
        "mastery": r.mastery,
        "battle_result": r.battle_result,
        "game_version": r.game_version,
        "notes": r.notes,
        "tags": list(r.tags or []),
        "favorite": bool(r.favorite),
        "parser_status": r.parser_status,
        "parser_version": r.parser_version,
        "parser_warnings": list(r.parser_warnings or []),
        "linked_milestone_id": r.linked_milestone_id,
        "milestone": _milestone_brief(r.milestone),
        "download_url": f"/wot/replays/{r.id}/file",
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }


def _label(r: WotReplay) -> str:
    name = r.tank_name or r.tank_tag or r.original_filename or f"replay #{r.id}"
    return name + (f" · {r.map_name}" if r.map_name else "")


def validate_upload(data: bytes, filename: str | None) -> None:
    name = media_storage.clean_original_name(filename) or ""
    if not name.lower().endswith(REPLAY_EXT):
        raise WotError("Nahrát jde jen soubor .wotreplay.", code="invalid_file")
    if not data:
        raise WotError("Soubor je prázdný.", code="invalid_file")
    if len(data) > MAX_BYTES:
        raise WotError(f"Replay je větší než {MAX_BYTES // (1024 * 1024)} MB.", status=413, code="invalid_file")


def _tank_name_hint(raw: str | None, tank_tag: str | None) -> str | None:
    """Lidský název vozidla poslaný frontendem (z manifestu Tankopedie podle tagu z hlavičky). Platí jen pro replay
    s rozpoznaným vozidlem a jen v mezích jako ruční úprava; neplatný se tiše zahodí – upload kvůli popisku nepadá."""
    if not tank_tag:
        return None
    try:
        return _clean_text(raw, "tank_name", 100)
    except WotError:
        return None


def upload_replay(db: Session, data: bytes, filename: str | None, *, tank_name: str | None = None,
                  now: datetime | None = None) -> WotReplay:
    """Ověří, odhalí duplicitu, zkusí parser, uloží soubor a založí záznam. Soubor se při chybě commitu maže volající.
    `tank_name` = lidský název z frontendu; technický `tank_tag` z hlavičky zůstává beze změny."""
    validate_upload(data, filename)
    digest = sha256(data)
    existing = db.query(WotReplay).filter(WotReplay.sha256 == digest).first()
    if existing is not None:
        raise DuplicateReplay(existing.id)
    result = parse_replay(data)
    if result.status == "invalid":
        raise WotError("Soubor nevypadá jako replay World of Tanks.", code="invalid_file")
    stored = media_storage.save_bytes(REPLAY_FOLDER, data, "wotreplay")
    now = now or utc_now()
    r = WotReplay(
        original_filename=media_storage.clean_original_name(filename), stored_filename=stored, file_size=len(data),
        sha256=digest, uploaded_at=now, created_at=now, updated_at=now, favorite=False, tags=[],
        parser_status=result.status, parser_version=result.parser_version, parser_warnings=result.warnings,
        **{k: v for k, v in result.metadata.items() if k in {"tank_tag", "map_name", "played_at", "game_version", "damage",
                                                              "assist", "kills", "base_xp", "mastery", "battle_result"}},
        tank_name=_tank_name_hint(tank_name, result.metadata.get("tank_tag")),
    )
    try:
        db.add(r)
        db.flush()
        log_activity(db, "wot", "create", f"Replay nahrán: {_label(r)}", entity_type="WotReplay", entity_id=r.id,
                     delta={"event": EVENTS["uploaded"], "parser_status": r.parser_status}, user_context="manual",
                     dedupe_key=f"{EVENTS['uploaded']}:{r.id}")
    except Exception:
        media_storage.delete_file(REPLAY_FOLDER, stored)  # žádný osiřelý soubor
        raise
    return r


def download_name(r: WotReplay) -> str:
    """Název přílohy: původní název bez uvozovek/lomítek, jinak replay-<id>.wotreplay."""
    name = re.sub(r'["\\/;]', "_", r.original_filename or "")
    return name if name.lower().endswith(REPLAY_EXT) else f"replay-{r.id}{REPLAY_EXT}"


def get_replay(db: Session, replay_id: int) -> WotReplay:
    r = db.get(WotReplay, replay_id)
    if r is None:
        raise WotError("Replay neexistuje.", status=404, code="not_found")
    return r


def create_milestone_from_replay(db: Session, replay_id: int) -> tuple[WotReplay, WotMilestone]:
    """„Vytvořit Mko z tohoto replaye": milník z uložených údajů replaye (tank, odznak, mapa, pražské datum,
    statistiky) a rovnou propojení – v jedné transakci. Už propojený replay / replay bez tanku se odmítne."""
    r = get_replay(db, replay_id)
    if r.linked_milestone_id is not None:
        raise WotError("Replay už je propojený s Mkem.", status=409, code="already_linked")
    tank = r.tank_name or (r.tank_tag.split(":", 1)[-1] if r.tank_tag else None)
    if not tank:
        raise WotError("Replay nemá tank – doplň ho v údajích replaye.", status=422, code="missing_tank")
    m = create_milestone(db, {
        "tank": tank, "mastery": r.mastery, "map_name": r.map_name,
        "played_on": to_local(r.played_at).date().isoformat() if r.played_at else None,
        "damage": r.damage, "assist": r.assist, "kills": r.kills, "base_xp": r.base_xp,
    })
    return update_replay(db, r.id, {"linked_milestone_id": m.id}), m


def update_replay(db: Session, replay_id: int, data: dict) -> WotReplay:
    r = get_replay(db, replay_id)
    fields = validate_meta(data)
    if "linked_milestone_id" in fields:
        mid = fields.pop("linked_milestone_id")
        if mid is not None and db.get(WotMilestone, mid) is None:
            raise WotError("Milník neexistuje.", status=404, code="milestone_not_found")
        if mid != r.linked_milestone_id:
            r.linked_milestone_id = mid
            if mid is not None:
                log_activity(db, "wot", "update", f"Replay propojen s milníkem: {_label(r)}", entity_type="WotReplay",
                             entity_id=r.id, delta={"event": EVENTS["linked"], "milestone_id": mid}, user_context="manual",
                             dedupe_key=f"{EVENTS['linked']}:{r.id}:{mid}:{utc_now().isoformat()}")
    for k, v in fields.items():
        setattr(r, k, v)
    r.updated_at = utc_now()
    db.flush()
    db.refresh(r)
    return r


def delete_replay(db: Session, replay_id: int) -> str:
    """Smaže záznam; vrací uložený název – soubor se maže AŽ po commitu. Propojený milník zůstává."""
    r = get_replay(db, replay_id)
    log_activity(db, "wot", "delete", f"Replay smazán: {_label(r)}", entity_type="WotReplay", entity_id=r.id,
                 delta={"event": EVENTS["deleted"]}, user_context="manual")
    name = r.stored_filename
    db.delete(r)
    return name


def _norm(text) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def list_replays(db: Session, *, q: str | None = None, tank: str | None = None, map_name: str | None = None,
                 tag: str | None = None, favorite: bool | None = None, mastery: str | None = None,
                 result: str | None = None, parser_status: str | None = None, sort: str = "played_desc") -> dict:
    """Deterministické filtrování v Pythonu (osobní knihovna = stovky záznamů). Fazety pro filtry z celé knihovny."""
    rows = db.query(WotReplay).all()
    facets = {
        "tanks": sorted({r.tank_name or r.tank_tag for r in rows if r.tank_name or r.tank_tag}, key=_norm),
        "maps": sorted({r.map_name for r in rows if r.map_name}, key=_norm),
        "tags": sorted({t for r in rows for t in (r.tags or [])}, key=lambda t: (PRESET_TAGS.index(t) if t in PRESET_TAGS else len(PRESET_TAGS), _norm(t))),
    }
    nq = _norm(q)[:100]
    tag_n = normalize_tag(tag) if tag else None
    out = []
    for r in rows:
        if nq and not all(w in _norm(" ".join(filter(None, [r.tank_name, r.tank_tag, r.map_name, r.notes, r.original_filename,
                                                            " ".join(r.tags or [])]))) for w in nq.split()):
            continue
        if tank and tank not in (r.tank_name, r.tank_tag):
            continue
        if map_name and r.map_name != map_name:
            continue
        if tag and tag_n not in (r.tags or []):
            continue
        if favorite is not None and bool(r.favorite) != favorite:
            continue
        if mastery and (r.mastery or "none") != mastery:
            continue
        if result and r.battle_result != result:
            continue
        if parser_status and r.parser_status != parser_status:
            continue
        out.append(r)
    if sort not in SORTS:
        raise WotError("Neznámé řazení.", code="invalid_sort")
    if sort == "uploaded_desc":
        out.sort(key=lambda r: (r.uploaded_at, r.id), reverse=True)
    else:
        # bez data na konec (v obou směrech), stabilně podle nahrání
        dated = sorted((r for r in out if r.played_at), key=lambda r: (r.played_at, r.id), reverse=sort == "played_desc")
        out = dated + sorted((r for r in out if not r.played_at), key=lambda r: (r.uploaded_at, r.id), reverse=True)
    return {"items": [serialize_replay(r) for r in out], "total": len(rows), "facets": facets,
            "preset_tags": list(PRESET_TAGS), "statuses": list(STATUSES)}
