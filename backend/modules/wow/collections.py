"""WoW sbírky (MRK-128) – denní snapshot počtů z Blizzard API a seznam „chci získat“.

- Mounti a pets jsou v API účtové; čtou se přes první postavu se stavem `ok` (nejvyšší level). Achievementy taky
  (body jsou účtové, seznam dokončených dává názvy pro odškrtnutí).
- Snapshot je jeden řádek na den (Europe/Prague) – historie „za týden +3“ je rozdíl dvou snapshotů, deterministicky.
- Položka seznamu přání se odškrtne sama, když API ukáže stejný název (bez velikosti písmen, sjednocené mezery a
  apostrofy). Odškrtnutí = doménová událost `wow.collection.acquired` (Aktivita, Co se změnilo, „Mise splněna“).
- Výpadek jednoho endpointu nechá u jeho čísla poslední stav; nic se nevymýšlí.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from activity_service import log_activity
from domain_events import ActivityProjection, append_domain_event
from modules.wow import battlenet
from modules.wow.models import WISH_KINDS, WowCharacter, WowCollectionSnapshot, WowWish
from time_utils import today_local, utc_now

AREA = "wow"
SYNC_EVERY = timedelta(hours=6)     # stejný rytmus jako postavy
HISTORY_DAYS = 30
MAX_WISHES = 200
NAME_MIN, NAME_MAX = 2, 120
COUNTS = ("mounts", "pets", "achievements", "achievement_points")
COUNT_LABELS = {"mounts": "mounti", "pets": "mazlíčci", "achievements": "achievementy",
                "achievement_points": "achievement body"}
KIND_LABELS = {"mount": "mount", "pet": "mazlíček", "achievement": "achievement"}

GOAL_MOUNTS = "wow_mounts"
GOAL_PETS = "wow_pets"
GOAL_ACHIEVEMENT_POINTS = "wow_achievement_points"
GOAL_SOURCES = {GOAL_MOUNTS: "mounts", GOAL_PETS: "pets", GOAL_ACHIEVEMENT_POINTS: "achievement_points"}

ACQUIRED_EVENT = "wow.collection.acquired"


class CollectionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- názvy ----------


def name_key(raw: str) -> str:
    """„Swift  Spectral Tiger“ / „swift spectral tiger“ → stejný klíč; typografické apostrofy = rovné."""
    s = (raw or "").replace("’", "'").replace("‘", "'").replace("`", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise CollectionError(400, f"Název: {NAME_MIN}–{NAME_MAX} znaků (anglicky, jak ho píše hra).")
    return name


# ---------- parsování odpovědí API (jen známá pole) ----------


def _names(items, inner: str) -> set[str]:
    out: set[str] = set()
    for it in items:
        obj = it.get(inner) if isinstance(it, dict) else None
        name = obj.get("name") if isinstance(obj, dict) else None
        if isinstance(name, str) and name.strip():
            out.add(name_key(name))
    return out


def _list(data, key: str) -> list | None:
    if not isinstance(data, dict):
        return None
    items = data.get(key)
    return items if isinstance(items, list) else None


def parse_mounts(data) -> tuple[int | None, set[str] | None]:
    items = _list(data, "mounts")
    return (None, None) if items is None else (len(items), _names(items, "mount"))


def parse_pets(data) -> tuple[int | None, set[str] | None]:
    """Počet = sebraní mazlíčci (i duplicity druhu, jak je počítá hra); názvy = druhy."""
    items = _list(data, "pets")
    return (None, None) if items is None else (len(items), _names(items, "species"))


def _nonneg(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 10**7 else None


def parse_achievements(data) -> tuple[int | None, int | None, set[str] | None]:
    """→ (dokončené, body, názvy dokončených). Dokončený = má `completed_timestamp` (retail vrací i rozpracované)."""
    items = _list(data, "achievements")
    if items is None:
        return None, None, None
    done = [it for it in items if isinstance(it, dict) and it.get("completed_timestamp")]
    return len(done), _nonneg(data.get("total_points")), _names(done, "achievement")


# ---------- čtení ----------


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def latest(db: Session) -> WowCollectionSnapshot | None:
    return db.query(WowCollectionSnapshot).order_by(WowCollectionSnapshot.day.desc()).first()


def snapshot_dict(s: WowCollectionSnapshot) -> dict:
    return {"day": s.day.isoformat(), **{k: getattr(s, k) for k in COUNTS}, "updated_at": _iso(s.updated_at)}


def week_delta(db: Session, today: date) -> dict:
    """Rozdíl posledního snapshotu proti stavu před 7 dny (nebo proti nejstaršímu, když historie tak dlouhá není).
    Číslo jen tam, kde obě strany mají hodnotu; jinak None."""
    last = latest(db)
    if last is None:
        return {k: None for k in COUNTS}
    base = (db.query(WowCollectionSnapshot).filter(WowCollectionSnapshot.day <= today - timedelta(days=7))
            .order_by(WowCollectionSnapshot.day.desc()).first()
            or db.query(WowCollectionSnapshot).order_by(WowCollectionSnapshot.day.asc()).first())
    if base is None or base.id == last.id:
        return {k: None for k in COUNTS}
    return {k: (getattr(last, k) - getattr(base, k)) if getattr(last, k) is not None and getattr(base, k) is not None
            else None for k in COUNTS}


def history(db: Session, today: date) -> list[dict]:
    rows = (db.query(WowCollectionSnapshot).filter(WowCollectionSnapshot.day > today - timedelta(days=HISTORY_DAYS))
            .order_by(WowCollectionSnapshot.day.asc()).all())
    return [snapshot_dict(s) for s in rows]


def wish_dict(w: WowWish) -> dict:
    return {"id": w.id, "kind": w.kind, "kind_label": KIND_LABELS.get(w.kind, w.kind), "name": w.name,
            "acquired": w.acquired_at is not None, "acquired_at": _iso(w.acquired_at), "created_at": _iso(w.created_at)}


def all_wishes(db: Session) -> list[WowWish]:
    rows = db.query(WowWish).limit(MAX_WISHES).all()
    # chybějící nahoře (nejstarší přání první), získané dole (nejčerstvější první)
    return sorted(rows, key=lambda w: (w.acquired_at is not None,
                                       -(w.acquired_at.timestamp()) if w.acquired_at else w.created_at.timestamp(),
                                       w.id))


def overview(db: Session, now: datetime | None = None) -> dict:
    today = today_local(now or utc_now())
    last = latest(db)
    wishes = all_wishes(db)
    return {
        "latest": snapshot_dict(last) if last else None,
        "week": week_delta(db, today),
        "history": history(db, today),
        "wishes": [wish_dict(w) for w in wishes],
        "open_wishes": sum(1 for w in wishes if w.acquired_at is None),
    }


def goal_value(db: Session, source: str) -> tuple[float, bool]:
    field = GOAL_SOURCES.get(source)
    last = latest(db) if field else None
    value = getattr(last, field) if last is not None else None
    return (float(value), True) if value is not None else (0.0, False)


# ---------- synchronizace ----------


def source_character(db: Session) -> WowCharacter | None:
    """Účtová data přes nejvýš postavenou postavu s úspěšnou synchronizací (stabilní volba: level, pak id)."""
    rows = db.query(WowCharacter).filter(WowCharacter.sync_status == "ok").all()
    return min(rows, key=lambda c: (-(c.level or 0), c.id)) if rows else None


def sync_collections(db: Session, client: battlenet.Client | None, *, now: datetime | None = None,
                     force: bool = False, user_context: str = "system") -> str:
    """Stáhne sbírku do dnešního snapshotu a odškrtne získaná přání. Vrací `ok` | `skipped` | `no_character` |
    `not_configured` | `unavailable`; nikdy nevyhazuje kvůli API."""
    now = now or utc_now()
    if client is None:
        return "not_configured"
    today = today_local(now)
    snap = db.query(WowCollectionSnapshot).filter(WowCollectionSnapshot.day == today).first()
    if not force and snap is not None and snap.updated_at > now - SYNC_EVERY:
        return "skipped"
    ch = source_character(db)
    if ch is None:
        return "no_character"
    mounts, mount_names = parse_mounts(client.collection(ch.realm_slug, ch.name_key, "mounts"))
    pets, pet_names = parse_pets(client.collection(ch.realm_slug, ch.name_key, "pets"))
    achievements, points, ach_names = parse_achievements(client.collection(ch.realm_slug, ch.name_key, "achievements"))
    values = {"mounts": mounts, "pets": pets, "achievements": achievements, "achievement_points": points}
    if all(v is None for v in values.values()):
        return "unavailable"
    previous = latest(db)
    before = {k: getattr(previous, k) for k in COUNTS} if previous else {k: None for k in COUNTS}
    if snap is None:
        snap = WowCollectionSnapshot(day=today, updated_at=now)
        # chybějící endpoint dnes = poslední známá hodnota (graf nemá díry kvůli výpadku)
        for k in COUNTS:
            setattr(snap, k, before[k])
        db.add(snap)
    for k, v in values.items():
        if v is not None:
            setattr(snap, k, v)
    snap.source_character_id = ch.id
    snap.updated_at = now
    db.flush()
    delta = {k: {"old": before[k], "new": getattr(snap, k)} for k in COUNTS if getattr(snap, k) != before[k]}
    if delta:
        log_activity(db, AREA, "sync", _summary(delta), entity_type="wow_collection", entity_id=snap.id,
                     delta=delta, user_context=user_context, dedupe_key=f"wow:collection:{uuid.uuid4().hex}")
    _tick_wishes(db, {"mount": mount_names, "pet": pet_names, "achievement": ach_names}, now, user_context)
    return "ok"


def _summary(delta: dict) -> str:
    parts = [f"{COUNT_LABELS[k]} {d['old'] if d['old'] is not None else '–'} → {d['new'] if d['new'] is not None else '–'}"
             for k, d in delta.items()]
    return f"WoW sbírka z Blizzard API: {', '.join(parts)}"[:480]


def _tick_wishes(db: Session, owned: dict[str, set[str] | None], now: datetime, user_context: str) -> None:
    for w in db.query(WowWish).filter(WowWish.acquired_at.is_(None)).order_by(WowWish.id).all():
        names = owned.get(w.kind)
        if not names or w.name_key not in names:
            continue  # endpoint nedal data (None) = nic neodškrtávat ani neodebírat
        # podmíněný update: souběžný sync (hodinový krok × ruční obnova) odškrtne a emituje jen jednou
        won = db.query(WowWish).filter(WowWish.id == w.id, WowWish.acquired_at.is_(None)).update(
            {WowWish.acquired_at: now}, synchronize_session=False) == 1
        if not won:
            continue
        db.refresh(w)
        append_domain_event(
            db, event_type=ACQUIRED_EVENT, aggregate_type="wish", aggregate_id=w.id, now=now,
            payload={"wish_id": w.id, "kind": w.kind},
            activity=ActivityProjection(AREA, "acquired", f"WoW: získáno – {w.name} ({KIND_LABELS[w.kind]})",
                                        entity_type="wow_wish", entity_id=w.id, user_context=user_context),
        )


KIND_ENDPOINT = {"mount": ("mounts", parse_mounts), "pet": ("pets", parse_pets)}


def already_owned(db: Session, client: battlenet.Client | None, kind: str, key: str) -> bool:
    """Nové přání se hned porovná se sbírkou (jeden požadavek na API). Výpadek / bez klíčů = False (odškrtne ho
    až další synchronizace)."""
    ch = source_character(db) if client is not None else None
    if ch is None:
        return False
    if kind == "achievement":
        names = parse_achievements(client.collection(ch.realm_slug, ch.name_key, "achievements"))[2]
    else:
        what, parse = KIND_ENDPOINT[kind]
        names = parse(client.collection(ch.realm_slug, ch.name_key, what))[1]
    return bool(names) and key in names


# ---------- zápisy (seznam přání) ----------


def _get(db: Session, wish_id: int) -> WowWish:
    w = db.get(WowWish, wish_id)
    if w is None:
        raise CollectionError(404, "Položka neexistuje.")
    return w


def add_wish(db: Session, kind: str, name: str, client: battlenet.Client | None = None, *,
             user_context: str = "manual") -> dict:
    if kind not in WISH_KINDS:
        raise CollectionError(400, "Druh: mount, mazlíček nebo achievement.")
    clean = clean_name(name)
    key = name_key(clean)
    if db.query(WowWish).count() >= MAX_WISHES:
        raise CollectionError(400, f"Nejvýš {MAX_WISHES} položek.")
    if db.query(WowWish).filter(WowWish.kind == kind, WowWish.name_key == key).first():
        raise CollectionError(409, "Tuhle položku už v seznamu máš.")
    now = utc_now()
    owned = already_owned(db, client, kind, key)
    # už ve sbírce = rovnou odškrtnuté, ale BEZ události „získáno“ (nic se teď nezískalo)
    w = WowWish(kind=kind, name=clean, name_key=key, created_at=now, acquired_at=now if owned else None)
    db.add(w)
    db.flush()
    note = " – už ve sbírce" if owned else ""
    log_activity(db, AREA, "create", f"WoW chci získat: {clean} ({KIND_LABELS[kind]}){note}", entity_type="wow_wish",
                 entity_id=w.id, user_context=user_context, dedupe_key=f"wow:wish:create:{uuid.uuid4().hex}")
    return {**wish_dict(w), "already_owned": owned}


def delete_wish(db: Session, wish_id: int, *, user_context: str = "manual") -> None:
    w = _get(db, wish_id)
    log_activity(db, AREA, "delete", f"WoW odebráno ze seznamu: {w.name} ({KIND_LABELS.get(w.kind, w.kind)})",
                 entity_type="wow_wish", entity_id=w.id, delta={"acquired": w.acquired_at is not None},
                 user_context=user_context, dedupe_key=f"wow:wish:delete:{uuid.uuid4().hex}")
    db.delete(w)
    db.flush()
