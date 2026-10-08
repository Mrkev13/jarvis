"""MRK-19: SSE stream doménových událostí – GET /events/stream (kontrakt: docs/domain-events.md).

Formát (UTF-8, text/event-stream):

    retry: 3000                                   ← jednou na začátku (reconnect po 3 s)

    id: 42                                        ← = domain_events.id (monotónní)
    event: domain_event
    data: {"id":42,"type":"school.assignment.completed","module_id":"school","aggregate_type":"assignment",
           "aggregate_id":"7","occurred_at":"2026-10-08T12:00:00Z","payload":{...}}

    id: 57                                        ← řídicí událost, id = nejnovější uložené id
    event: reset
    data: {"reason":"retention|overflow|unknown_cursor","latest_id":57}

    : keepalive                                   ← komentář každých ~15 s bez provozu

Pozice: `Last-Event-ID` (hlavička, kterou EventSource posílá sám při reconnectu) nebo `?last_event_id=`.
- bez pozice → jen nové události (žádná historie),
- s pozicí → přehraje uložené události s id > pozice (nejvýš 200), pak pokračuje živě,
- pozice starší než retence / víc než 200 zmeškaných / pozice za koncem DB → jedna `reset` událost
  (klient má stav načíst znovu přes REST), pak živě od nejnovějšího id.
Události vypnutých modulů se nikdy neposílají (kurzor je ale přeskočí). Filtry `?modules=a,b&types=x,y`
(jádrové události = modul `system`).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Callable

from starlette.concurrency import run_in_threadpool

import domain_events as de

try:
    from database import SessionLocal  # testy patchují event_stream.SessionLocal
except Exception:  # pragma: no cover
    SessionLocal = None  # type: ignore[assignment]

RETRY_MS = 3000
HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 1.0
WAKE_STEP_SECONDS = 0.2
GAP_GRACE_SECONDS = 5.0
REPLAY_MAX = 200
BATCH = 100
MAX_CURSOR = 2 ** 63 - 1

RESET_RETENTION = "retention"
RESET_OVERFLOW = "overflow"
RESET_UNKNOWN = "unknown_cursor"


class Broadcaster:
    """Probouzí otevřené streamy po commitu (after-commit konzument). Jen počítadlo – data jdou z DB."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.generation = 0

    def notify(self, _events=None) -> None:
        with self._lock:
            self.generation += 1


broadcaster = Broadcaster()
de.register_after_commit(broadcaster.notify)


def parse_cursor(header: str | None, query: str | None) -> int | None:
    """Hlavička Last-Event-ID má přednost; jen nezáporné celé číslo, jinak žádná pozice."""
    for raw in (header, query):
        if raw is None:
            continue
        raw = raw.strip()
        if raw.isdigit() and int(raw) <= MAX_CURSOR:
            return int(raw)
    return None


def parse_filter(raw: str | None) -> frozenset[str] | None:
    if not raw:
        return None
    items = frozenset(x.strip() for x in raw.split(",") if x.strip())
    return items or None


def frame(event: str, data: dict, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def visible(ev: de.EventSnapshot, access, modules: frozenset[str] | None, types: frozenset[str] | None) -> bool:
    if ev.module_id is not None and not access.is_available(ev.module_id):
        return False  # vypnutý modul se nikdy nestreamuje
    if modules is not None and (ev.module_id or de.CORE_SCOPE) not in modules:
        return False
    if types is not None and ev.type not in types:
        return False
    return True


def initial_position(cursor: int | None) -> tuple[int, str | None, int]:
    """(pozice, důvod resetu nebo None, nejnovější id). Deterministické pravidlo – viz docstring modulu."""
    db = SessionLocal()
    try:
        lo, hi = de.bounds(db)
        latest = hi or 0
        if cursor is None:
            return latest, None, latest
        if cursor > latest:
            return latest, RESET_UNKNOWN, latest
        if lo is not None and cursor < lo - 1:
            return latest, RESET_RETENTION, latest
        if de.count_after(db, cursor) > REPLAY_MAX:
            return latest, RESET_OVERFLOW, latest
        return cursor, None, latest
    finally:
        db.close()


def _fetch(cursor: int):
    from module_registry import current_access
    db = SessionLocal()
    try:
        return de.fetch_after(db, cursor, BATCH), current_access()
    finally:
        db.close()


def _ready(ev: de.EventSnapshot, cursor: int, cutoff: datetime) -> bool:
    """Mezera v id může být rozpracovaná transakce s nižším id → u čerstvé události chvíli počkat."""
    if ev.id == cursor + 1:
        return True
    try:
        occurred = datetime.fromisoformat(ev.occurred_at.rstrip("Z")).replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError):
        return True
    return occurred <= cutoff  # starší než grace → mezera = rollback, přeskočit


async def stream_events(
    is_disconnected: Callable[[], "asyncio.Future[bool] | bool"],
    cursor: int | None,
    *,
    modules: frozenset[str] | None = None,
    types: frozenset[str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[str]:
    yield f"retry: {RETRY_MS}\n\n"
    position, reset_reason, latest = await run_in_threadpool(initial_position, cursor)
    if reset_reason:
        yield frame("reset", {"reason": reset_reason, "latest_id": latest}, latest)
    last_output = clock()
    seen = broadcaster.generation
    while True:
        disconnected = is_disconnected()
        if asyncio.iscoroutine(disconnected) or isinstance(disconnected, asyncio.Future):
            disconnected = await disconnected
        if disconnected:
            return
        batch, access = await run_in_threadpool(_fetch, position)
        cutoff = de.now_utc() - timedelta(seconds=GAP_GRACE_SECONDS)
        blocked = False
        for ev in batch:
            if not _ready(ev, position, cutoff):
                blocked = True
                break
            position = ev.id
            if visible(ev, access, modules, types):
                yield frame("domain_event", ev.to_wire(), ev.id)
                last_output = clock()
        if len(batch) == BATCH and not blocked:
            continue  # další dávka hned (dohánění)
        waited = 0.0
        while waited < POLL_SECONDS and broadcaster.generation == seen:
            await asyncio.sleep(WAKE_STEP_SECONDS)
            waited += WAKE_STEP_SECONDS
        seen = broadcaster.generation
        if clock() - last_output >= HEARTBEAT_SECONDS:
            yield ": keepalive\n\n"
            last_output = clock()
