"""MRK-106: tabulka M-ek všech tanků z Wargaming API, automatické první M a párování s replayem. Bez LLM.

- Synchronizace (hodinový krok nejvýš jednou za 6 h, ručně hned) uloží u každého odehraného tanku nejvyšší odznak
  (`wot_vehicle_mastery`). API dává jen NEJVYŠŠÍ odznak – kolikrát má tank M, neví; opakovaná M zůstávají ruční.
- První synchronizace je jen výchozí stav (stará M nemají datum, žádné milníky nevznikají). Každá další, která uvidí
  přechod tanku na 4 (Ace), založí milník `source="api"` (cíl „M-ka celkem“ ho započítá) a doménovou událost
  `wot.mastery.ace_detected` („Mise splněna“). Podmíněný update = při souběhu jen jeden milník.
- Takový milník „čeká na replay“: nahraný replay se stejným tankem a odznakem M (bitva nejpozději den po detekci) se
  s ním spáruje sám a doplní statistiky bitvy (mapa, datum, poškození…).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import wot_wargaming
from activity_service import log_activity
from domain_events import append_domain_event
from models import WotMilestone, WotReplay, WotVehicleMastery
from time_utils import to_local, today_local, utc_now

AREA = "wot"
SYNC_EVERY = timedelta(hours=6)
PAIR_AFTER_DETECTION = timedelta(days=1)   # replay bitvy odehrané po detekci + 1 den = jiné (opakované) M
ACE = 4
MARK_LABELS = {4: "M", 3: "I", 2: "II", 1: "III", 0: "–"}
MARK_NAMES = {4: "Mistr (M)", 3: "1. třída", 2: "2. třída", 1: "3. třída", 0: "bez odznaku"}
ACE_EVENT = "wot.mastery.ace_detected"
NATION_LABELS = {"ussr": "SSSR", "germany": "Německo", "usa": "USA", "france": "Francie", "uk": "Británie",
                 "china": "Čína", "japan": "Japonsko", "czech": "Československo", "sweden": "Švédsko",
                 "poland": "Polsko", "italy": "Itálie", "intunion": "Mezinárodní"}
TYPE_LABELS = {"heavyTank": "TT", "mediumTank": "ST", "lightTank": "LT", "AT-SPG": "TD", "SPG": "SPG"}
PENDING_NOTE = "Zjištěno z Wargaming API – nahraj replay bitvy a statistiky se doplní samy."
ERROR_TEXT = {
    "not_configured": "Wargaming API není na serveru nastavené.",
    "not_found": "Účet s touhle přezdívkou Wargaming nenašel – zkontroluj WOT_NICKNAME a region.",
    "private": "Statistiky účtu jsou skryté – ve hře je zveřejni (Nastavení → Ostatní).",
    "unauthorized": "Wargaming API odmítlo application_id serveru.",
    "rate_limited": "Wargaming API teď omezuje počet požadavků, zkus to za chvíli.",
    "unavailable": "Wargaming API teď neodpovídá.",
    "invalid_response": "Wargaming API vrátilo nečekanou odpověď.",
}


class MasteryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def norm_name(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("’", "'")).strip().lower()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


# ---------- čtení ----------


def _ace_counts(db: Session) -> dict[str, int]:
    """Počet M milníků podle tanku (normalizovaný název) – tabulka ukáže „M ×3“ i s opakovanými ručními M."""
    out: dict[str, int] = {}
    for (tank,) in db.query(WotMilestone.tank).filter(WotMilestone.milestone_type == "mastery",
                                                       WotMilestone.mastery == "ace"):
        out[norm_name(tank)] = out.get(norm_name(tank), 0) + 1
    return out


def _pending_ids(db: Session) -> set[int]:
    """Milníky z API bez propojeného replaye."""
    linked = {mid for (mid,) in db.query(WotReplay.linked_milestone_id).filter(WotReplay.linked_milestone_id.isnot(None))}
    return {mid for (mid,) in db.query(WotMilestone.id).filter(WotMilestone.source == "api") if mid not in linked}


def row_dict(r: WotVehicleMastery, aces: dict[str, int], pending: set[int]) -> dict:
    name = r.name or f"Tank {r.tank_id}"
    return {
        "tank_id": r.tank_id, "name": name, "short_name": r.short_name, "tag": r.tag, "tier": r.tier,
        "nation": r.nation, "nation_label": NATION_LABELS.get(r.nation or "", r.nation),
        "type": r.vehicle_type, "type_label": TYPE_LABELS.get(r.vehicle_type or "", r.vehicle_type),
        "mark": r.mark_of_mastery, "mark_label": MARK_LABELS.get(r.mark_of_mastery, "–"),
        "battles": r.battles, "ace_count": aces.get(norm_name(name), 0),
        "ace_detected_at": _iso(r.ace_detected_at), "ace_milestone_id": r.ace_milestone_id,
        "pending_replay": r.ace_milestone_id is not None and r.ace_milestone_id in pending,
    }


def all_rows(db: Session) -> list[WotVehicleMastery]:
    rows = db.query(WotVehicleMastery).all()
    # nejvyšší tier a odznak nahoře, pak název – „co mám nejdál“ na první pohled
    return sorted(rows, key=lambda r: (-(r.tier or 0), -r.mark_of_mastery, norm_name(r.name), r.tank_id))


def summary(db: Session, rows: list[WotVehicleMastery] | None = None) -> dict:
    rows = all_rows(db) if rows is None else rows
    by_mark = {label: 0 for label in ("M", "I", "II", "III", "–")}
    for r in rows:
        by_mark[MARK_LABELS.get(r.mark_of_mastery, "–")] += 1
    last = max((r.updated_at for r in rows), default=None)
    return {"tanks": len(rows), "with_ace": by_mark["M"], "by_mark": by_mark, "last_synced_at": _iso(last),
            "pending_replays": len(_pending_ids(db))}


def overview(db: Session) -> dict:
    rows = all_rows(db)
    aces, pending = _ace_counts(db), _pending_ids(db)
    return {"config": wot_wargaming.config_status(), "summary": summary(db, rows),
            "tanks": [row_dict(r, aces, pending) for r in rows]}


def query(db: Session, *, tier: int | None = None, nation: str | None = None, mastery: str | None = None,
          limit: int = 50) -> dict:
    """AI read tool „M-ka po tancích“: spočítaný výsledek z uloženého snapshotu (žádné API, žádné LLM).
    `mastery`: ace | first | second | third | none | without_ace."""
    want = {"ace": {4}, "first": {3}, "second": {2}, "third": {1}, "none": {0}, "without_ace": {0, 1, 2, 3}}.get(
        (mastery or "").strip().lower())
    nation_key = (nation or "").strip().lower()
    nation_keys = {k for k, v in NATION_LABELS.items() if nation_key in (k, v.lower())} if nation_key else None
    rows = [r for r in all_rows(db)
            if (tier is None or r.tier == tier)
            and (nation_keys is None or (r.nation or "") in nation_keys)
            and (want is None or r.mark_of_mastery in want)]
    aces, pending = _ace_counts(db), _pending_ids(db)
    limit = max(1, min(int(limit or 50), 200))
    items = [{k: d[k] for k in ("name", "tier", "nation_label", "type_label", "mark_label", "battles", "ace_count")}
             for d in (row_dict(r, aces, pending) for r in rows[:limit])]
    s = summary(db)
    return {"source": "Wargaming API (nejvyšší odznak na tank)", "last_synced_at": s["last_synced_at"],
            "matching": len(rows), "returned": len(items), "items": items,
            "note": "API zná jen nejvyšší odznak; ace_count = M milníky v Hubu (včetně opakovaných ručních)."}


# ---------- synchronizace ----------


def sync(db: Session, client: wot_wargaming.Client | None, *, now: datetime | None = None, force: bool = False,
         user_context: str = "system") -> dict:
    """Stáhne odznaky všech tanků. Vrací {"result": ok | skipped | <kód chyby>, ...}; kvůli API nikdy nevyhazuje."""
    now = now or utc_now()
    if client is None:
        return {"result": "not_configured"}
    existing = {r.tank_id: r for r in db.query(WotVehicleMastery).all()}
    newest = max((r.updated_at for r in existing.values()), default=None)
    if not force and newest is not None and newest > now - SYNC_EVERY:
        return {"result": "skipped"}
    try:
        stats = client.tank_stats(client.account_id())
        missing = [s["tank_id"] for s in stats if s["tank_id"] not in existing or not existing[s["tank_id"]].name]
        info = client.vehicles(missing) if missing else {}
    except wot_wargaming.WargamingError as err:
        return {"result": err.code}
    baseline = not existing  # první synchronizace: stará M bez data, žádné milníky
    changed, new_aces = 0, []
    for s in stats:
        row = existing.get(s["tank_id"])
        meta = info.get(s["tank_id"])
        if row is None:
            row = _insert(db, s, meta, now)
            if row is None:
                continue  # souběžný sync tank právě vložil – další běh ho uvidí
            changed += 1
            if not baseline and s["mark_of_mastery"] == ACE:
                new_aces.append(row)
            continue
        if meta:
            _apply_meta(row, meta)
        old = row.mark_of_mastery
        if s["battles"] is not None:
            row.battles = s["battles"]
        row.updated_at = now
        if s["mark_of_mastery"] != old:
            # podmíněný update proti načtené hodnotě – souběžný sync přechod nezopakuje
            won = db.query(WotVehicleMastery).filter(WotVehicleMastery.id == row.id,
                                                     WotVehicleMastery.mark_of_mastery == old).update(
                {WotVehicleMastery.mark_of_mastery: s["mark_of_mastery"]}, synchronize_session=False) == 1
            if not won:
                db.refresh(row)
                continue
            row.mark_of_mastery = s["mark_of_mastery"]
            changed += 1
            if s["mark_of_mastery"] == ACE and old < ACE:
                new_aces.append(row)
    db.flush()
    for row in new_aces:
        _record_ace(db, row, now, user_context)
    if changed:
        log_activity(db, AREA, "sync", f"WoT odznaky z Wargaming API: {changed} tanků změněno"
                     + (f", nová M: {len(new_aces)}" if new_aces else ""),
                     entity_type="wot_vehicle_mastery", delta={"changed": changed, "new_aces": len(new_aces),
                                                               "baseline": baseline},
                     user_context=user_context, dedupe_key=f"wot:mastery:sync:{uuid.uuid4().hex}")
    return {"result": "ok", "tanks": len(stats), "changed": changed, "new_aces": len(new_aces), "baseline": baseline}


def _apply_meta(row: WotVehicleMastery, meta: dict) -> None:
    row.name, row.short_name, row.tag = meta["name"], meta["short_name"], meta["tag"]
    row.tier, row.nation, row.vehicle_type = meta["tier"], meta["nation"], meta["type"]


def _insert(db: Session, s: dict, meta: dict | None, now: datetime) -> WotVehicleMastery | None:
    try:
        with db.begin_nested():
            row = WotVehicleMastery(tank_id=s["tank_id"], mark_of_mastery=s["mark_of_mastery"], battles=s["battles"],
                                    updated_at=now)
            if meta:
                _apply_meta(row, meta)
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        return None


def _record_ace(db: Session, row: WotVehicleMastery, now: datetime, user_context: str) -> None:
    """Nové M tanku → milník „čeká na replay“ (+ cíl M-ka celkem) a doménová událost pro „Mise splněna“."""
    import wot_service  # líně: wot_service → goal_history_service → … (bez cyklu při importu modulu)

    m = wot_service.create_milestone(db, {
        "tank": row.name or f"Tank {row.tank_id}", "mastery": "ace", "played_on": today_local(now).isoformat(),
        "notes": PENDING_NOTE,
    }, user_context=user_context)
    m.source = "api"
    row.ace_detected_at = now
    row.ace_milestone_id = m.id
    db.flush()
    append_domain_event(db, event_type=ACE_EVENT, aggregate_type="milestone", aggregate_id=m.id, now=now,
                        payload={"milestone_id": m.id, "tank_id": row.tank_id, "tier": row.tier})


# ---------- párování replaye ----------


def _replay_tag(r: WotReplay) -> str:
    return (r.tank_tag or "").split(":", 1)[-1].strip().lower()


def pending_match(db: Session, r: WotReplay) -> WotMilestone | None:
    """Čekající M milník z API pro tenhle replay: stejný tank (tag z hlavičky, jinak název), odznak M a bitva
    nejpozději den po detekci (pozdější bitva = opakované M, to se nepáruje). Jinak None."""
    if r.mastery != "ace" or r.linked_milestone_id is not None:
        return None
    pending = _pending_ids(db)
    if not pending:
        return None
    tag, name = _replay_tag(r), norm_name(r.tank_name)
    for row in db.query(WotVehicleMastery).filter(WotVehicleMastery.ace_milestone_id.in_(pending)).all():
        same = (tag and (row.tag or "").lower() == tag) or (name and name in {norm_name(row.name), norm_name(row.short_name)})
        if not same:
            continue
        if r.played_at and row.ace_detected_at and r.played_at > row.ace_detected_at + PAIR_AFTER_DETECTION:
            continue
        return db.get(WotMilestone, row.ace_milestone_id)
    return None


def fill_from_replay(db: Session, m: WotMilestone, r: WotReplay, *, user_context: str = "manual") -> WotMilestone:
    """Doplní čekající milník údaji z replaye a propojí je (v transakci volajícího)."""
    if r.map_name:
        m.map_name = r.map_name
    if r.played_at:
        m.played_on = to_local(r.played_at).date()
    for field in ("damage", "assist", "kills", "base_xp"):
        if getattr(r, field) is not None:
            setattr(m, field, getattr(r, field))
    if m.notes == PENDING_NOTE:
        m.notes = None
    m.updated_at = utc_now()
    r.linked_milestone_id = m.id
    db.flush()
    log_activity(db, AREA, "update", f"M na {m.tank} doplněno z replaye", entity_type="WotMilestone", entity_id=m.id,
                 delta={"event": "wot_mastery_replay_paired", "replay_id": r.id}, user_context=user_context,
                 dedupe_key=f"wot:mastery:paired:{m.id}:{r.id}")
    return m
