"""MRK-19: doménové události – transakční outbox + after-commit dispatch (Platform 2.0 B, docs/domain-events.md).

Autoritativní je UDÁLOST (fakt „úkol splněn"), Aktivita je její projekce. Jeden zápis:

    1. business změna v session volajícího
    2. `append_domain_event(db, …)` ve STEJNÉ transakci → řádek `domain_events` (+ projekce do Aktivity)
    3. volající `db.commit()` → data, událost i řádek Aktivity uložené spolu, nebo nic (rollback)
    4. po commitu `after_commit` hook předá snímky registrovaným konzumentům (SSE…); chyba konzumenta
       nikdy neshodí ani nevrátí uložený zápis

Pojmenování: `<modul>.<agregát>.<akce>` – malá písmena, číslice, `_`; první část = id modulu-vlastníka,
jádro používá `system` (`system.module.enabled`). Typ musí být DEKLAROVANÝ: modulové v `ModuleDef.event_types`,
jádrové v `CORE_EVENT_TYPES` – nedeklarovaný typ = DomainEventError. `module_id` se odvodí z deklarace.

Payload: malý JSON slovník jen s identifikátory, stavy, daty a ISO časy – žádné ORM objekty, volný text
ani osobní obsah (názvy, poznámky). Text pro lidi patří do projekce Aktivity (`ActivityProjection`).
Retence (`cleanup_domain_events`) maže jen tuto tabulku, nikdy Aktivitu ani business historii.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CORE_SCOPE = "system"

# Jádro (nepatří žádnému modulu → streamuje se vždy).
CORE_EVENT_TYPES = frozenset({"system.module.enabled", "system.module.disabled"})

PAYLOAD_MAX_BYTES = 2048
PAYLOAD_MAX_DEPTH = 3

RETENTION_DEFAULT_DAYS = 180
RETENTION_MIN_DAYS = 90
RETENTION_MAX_DAYS = 365
CLEANUP_BATCH = 5000

_PENDING_KEY = "_standa_hub_domain_events_pending"


class DomainEventError(ValueError):
    """Neplatná událost (nedeklarovaný typ, špatný payload…) – programátorská chyba, transakce selže."""


@dataclass(frozen=True)
class ActivityProjection:
    """Jak se událost promítne do Aktivity (in-transaction konzument). Text pro lidi žije jen tady."""
    area: str
    action_type: str
    summary: str
    entity_type: str | None = None
    entity_id: int | None = None
    delta: dict | None = None
    user_context: str | None = "manual"
    # None = klíč podle id události → každý fakt = jeden řádek (opakované cykly se neztratí, žádné duplikáty)
    dedupe_key: str | None = None


@dataclass(frozen=True)
class EventSnapshot:
    """Neměnný snímek uložené události (after-commit konzumenti, SSE). `to_wire` = stabilní tvar streamu."""
    id: int
    type: str
    module_id: str | None
    aggregate_type: str
    aggregate_id: str | None
    occurred_at: str
    payload: dict = field(default_factory=dict)

    def to_wire(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "module_id": self.module_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }


# ---------- deklarace typů ----------

def declared_types() -> dict[str, str | None]:
    """typ → vlastník (id modulu, nebo None = jádro). Jediný zdroj pravdy o povolených typech."""
    from module_registry import MODULES
    out: dict[str, str | None] = {t: None for t in CORE_EVENT_TYPES}
    for m in MODULES:
        for t in m.event_types:
            if t in out:
                raise DomainEventError(f"event type declared twice: {t}")
            out[t] = m.id
    return out


def owner_of(event_type: str) -> str | None:
    types = declared_types()
    if event_type not in types:
        raise DomainEventError(f"undeclared domain event type: {event_type}")
    return types[event_type]


# ---------- payload a čas ----------

def _check_value(value: Any, depth: int) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DomainEventError("payload floats must be finite")
        return
    if depth >= PAYLOAD_MAX_DEPTH:
        raise DomainEventError("payload is nested too deeply")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise DomainEventError("payload keys must be strings")
            _check_value(v, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _check_value(v, depth + 1)
        return
    raise DomainEventError(f"payload value of type {type(value).__name__} is not allowed (use ids / ISO strings)")


def validate_payload(payload: dict | None) -> dict:
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        raise DomainEventError("payload must be a dict")
    _check_value(payload, 0)
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > PAYLOAD_MAX_BYTES:
        raise DomainEventError("payload is too large – keep events small (ids, states, times)")
    return json.loads(raw)  # čistá kopie (žádné sdílené měnitelné objekty volajícího)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """SQLite vrací naivní čas – v této tabulce je vždy UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """ISO 8601 v UTC se „Z" (naivní datetime = UTC, konvence projektu)."""
    if dt is None:
        return None
    return as_utc(dt).replace(tzinfo=None).isoformat() + "Z"


# ---------- zápis ----------

def append_domain_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: Any = None,
    module_id: str | None = None,
    payload: dict | None = None,
    activity: ActivityProjection | None = None,
    now: datetime | None = None,
):
    """Přidá událost do transakce volajícího – nikdy necommituje a neotvírá vlastní transakci.
    Neplatný typ / payload = DomainEventError (volající transakci vrátí). Vrací ORM řádek (s id)."""
    from activity_service import log_activity
    from models import DomainEvent

    if not isinstance(event_type, str) or not EVENT_TYPE_RE.match(event_type):
        raise DomainEventError(f"invalid event type name: {event_type!r} (expected <module>.<aggregate>.<action>)")
    owner = owner_of(event_type)
    if event_type.split(".", 1)[0] != (owner or CORE_SCOPE):
        raise DomainEventError(f"{event_type} must start with its owner '{owner or CORE_SCOPE}'")
    if module_id is not None and module_id != owner:
        raise DomainEventError(f"{event_type} belongs to {owner or CORE_SCOPE}, not {module_id}")
    if not isinstance(aggregate_type, str) or not IDENT_RE.match(aggregate_type):
        raise DomainEventError("aggregate_type must be a lowercase identifier")
    clean = validate_payload(payload)

    row = DomainEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=None if aggregate_id is None else str(aggregate_id)[:64],
        module_id=owner,
        occurred_at=as_utc(now) if now else now_utc(),
        payload=clean,
    )
    db.add(row)
    db.flush()  # id pro projekci a SSE; selže-li cokoli dál, rollback volajícího vezme vše

    if activity is not None:
        log_activity(
            db, activity.area, activity.action_type, activity.summary,
            entity_type=activity.entity_type, entity_id=activity.entity_id, delta=activity.delta,
            user_context=activity.user_context, dedupe_key=activity.dedupe_key or f"event:{row.id}",
        )
    db.info.setdefault(_PENDING_KEY, []).append(snapshot(row))
    return row


def snapshot(row) -> EventSnapshot:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return EventSnapshot(
        id=int(row.id), type=row.event_type, module_id=row.module_id, aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id, occurred_at=iso(row.occurred_at), payload=dict(payload),
    )


# ---------- after-commit dispatch ----------
# Statické registrace (žádné skenování pluginů). Konzument dostane seznam právě uložených událostí.

_consumers: list[Callable[[list[EventSnapshot]], None]] = []
_consumers_lock = threading.Lock()


def register_after_commit(consumer: Callable[[list[EventSnapshot]], None]) -> Callable[[], None]:
    with _consumers_lock:
        _consumers.append(consumer)

    def unregister() -> None:
        with _consumers_lock:
            if consumer in _consumers:
                _consumers.remove(consumer)
    return unregister


def _dispatch(events: list[EventSnapshot]) -> None:
    with _consumers_lock:
        consumers = list(_consumers)
    for consumer in consumers:
        try:
            consumer(events)
        except Exception as exc:  # noqa: BLE001 - konzument nikdy neovlivní uložený zápis
            # bez obsahu události a bez textu výjimky (může obsahovat data) – jen kategorie
            log.warning("domain events: after-commit consumer %s failed (%s)",
                        getattr(consumer, "__name__", "consumer"), type(exc).__name__)


@sa_event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if pending:
        _dispatch(pending)


@sa_event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)


# ---------- čtení (SSE, replay) ----------

def fetch_after(db: Session, after_id: int, limit: int = 100) -> list[EventSnapshot]:
    from models import DomainEvent
    rows = db.query(DomainEvent).filter(DomainEvent.id > after_id).order_by(DomainEvent.id).limit(limit).all()
    return [snapshot(r) for r in rows]


def bounds(db: Session) -> tuple[int | None, int | None]:
    """(nejstarší, nejnovější) uložené id; (None, None) pro prázdný outbox."""
    from sqlalchemy import func
    from models import DomainEvent
    lo, hi = db.query(func.min(DomainEvent.id), func.max(DomainEvent.id)).one()
    return (int(lo) if lo is not None else None, int(hi) if hi is not None else None)


def count_after(db: Session, after_id: int) -> int:
    from models import DomainEvent
    return db.query(DomainEvent.id).filter(DomainEvent.id > after_id).count()


# ---------- retence (jen přenosová historie) ----------

def retention_days() -> int:
    """DOMAIN_EVENTS_RETENTION_DAYS: výchozí 180, povoleno 90–365. Mimo rozsah = nejbližší mez,
    nečíselná hodnota = výchozí (vždy s varováním v logu)."""
    import os
    raw = (os.environ.get("DOMAIN_EVENTS_RETENTION_DAYS") or "").strip()
    if not raw:
        return RETENTION_DEFAULT_DAYS
    try:
        days = int(raw)
    except ValueError:
        log.warning("domain events: DOMAIN_EVENTS_RETENTION_DAYS is not a number – using %s", RETENTION_DEFAULT_DAYS)
        return RETENTION_DEFAULT_DAYS
    clamped = min(max(days, RETENTION_MIN_DAYS), RETENTION_MAX_DAYS)
    if clamped != days:
        log.warning("domain events: retention %s days out of range 90–365 – using %s", days, clamped)
    return clamped


def cleanup_domain_events(db: Session, *, now: datetime | None = None, days: int | None = None,
                          batch: int = CLEANUP_BATCH) -> int:
    """Smaže jen řádky `domain_events` STARŠÍ než práh (occurred_at < now − days), nejvýš `batch` najednou.
    Událost přesně na prahu zůstává. Necommituje. Aktivita ani business historie se nikdy nemažou."""
    from models import DomainEvent
    days = retention_days() if days is None else days
    if not RETENTION_MIN_DAYS <= days <= RETENTION_MAX_DAYS:
        raise ValueError("retention must be 90–365 days")
    threshold = (as_utc(now) if now else now_utc()) - timedelta(days=days)
    ids = [i for (i,) in db.query(DomainEvent.id).filter(DomainEvent.occurred_at < threshold)
           .order_by(DomainEvent.id).limit(batch).all()]
    if not ids:
        return 0
    db.query(DomainEvent).filter(DomainEvent.id.in_(ids)).delete(synchronize_session=False)
    return len(ids)
