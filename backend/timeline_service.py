"""Denní časová osa (MRK-13) – „jak můj den skutečně vypadá". Deterministická projekce, nikdy se neukládá.

Položky dodávají moduly (`ModuleIntegrations.timeline`, module_contracts.TimelineSource); jádro tu drží jen
politiku: sběr povolených příspěvků, rozdělení na denní sekci (termíny, celodenní) a časové položky, řazení,
limity a vložení odvozených volných bloků. Žádné větve podle modulu. Překryvy se nespojují – každý fakt zůstává
samostatnou položkou. Nic se nezapisuje do Aktivity, doménových událostí, vyhledávání ani „Co se změnilo".
"""
from __future__ import annotations

import logging
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone

from module_contracts import TimelineItem, TimelineRequest
from time_utils import APP_TZ

log = logging.getLogger(__name__)

MAX_ITEMS = 200
DEFAULT_MIN_MINUTES = 30
UTC = timezone.utc
# denní sekce: nejdřív termíny/zkoušky, pak celodenní události; neznámý druh nakonec (stabilně podle názvu)
_DAY_KIND_RANK = {"exam": 0, "assignment": 1}


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Pražský den [00:00, další 00:00) v aware UTC – 23/24/25 h podle DST."""
    return (datetime.combine(day, datetime.min.time(), APP_TZ).astimezone(UTC),
            datetime.combine(day + timedelta(days=1), datetime.min.time(), APP_TZ).astimezone(UTC))


def _iso(value):
    return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value


def item_dict(item: TimelineItem) -> dict:
    out = asdict(item)
    out["starts_at"], out["ends_at"] = _iso(item.starts_at), _iso(item.ends_at)
    if isinstance(item.starts_at, datetime) and not item.all_day:
        out["local_start"] = item.starts_at.astimezone(APP_TZ).strftime("%H:%M")
        out["local_end"] = item.ends_at.astimezone(APP_TZ).strftime("%H:%M") if isinstance(item.ends_at, datetime) else None
    return out


def get_day_timeline(db, access, *, day: date, include_free_blocks: bool = True,
                     min_minutes: int = DEFAULT_MIN_MINUTES, now: datetime | None = None) -> dict:
    start, end = day_bounds(day)
    req = TimelineRequest(db=db, day=day, start=start, end=end, now=(now or datetime.now(UTC)).astimezone(UTC))
    sources = sorted(access.contributions("timeline"), key=lambda pair: (pair[1].order, pair[1].name))
    order = {source.name: i for i, (_owner, source) in enumerate(sources)}
    collected: list[tuple[int, TimelineItem]] = []
    for owner, source in sources:
        try:
            for item in source.build(req):
                collected.append((order[source.name], replace(item, module_id=owner)))
        except Exception as exc:  # noqa: BLE001 - jeden zdroj nesmí shodit celý den (loguje se jen typ)
            log.warning("timeline: source %s failed (%s)", source.name, type(exc).__name__)
            db.rollback()

    day_items = [(rank, it) for rank, it in collected if it.all_day or it.starts_at is None]
    timed = [(rank, it) for rank, it in collected if not (it.all_day or it.starts_at is None)]
    day_items.sort(key=lambda p: (_DAY_KIND_RANK.get(p[1].kind, 2), p[0], p[1].title.casefold(), p[1].id))
    # časové: začátek, konec (okamžik = začátek), pořadí zdroje, id – nikdy pořadí z DB
    timed.sort(key=lambda p: (p[1].starts_at, p[1].ends_at or p[1].starts_at, p[0], p[1].id))
    truncated = len(day_items) + len(timed) > MAX_ITEMS

    free, free_sources = [], []
    if include_free_blocks:
        for _owner, source in sources:
            if source.free_blocks is None:
                continue
            try:
                result = source.free_blocks(req, min_minutes)
            except Exception as exc:  # noqa: BLE001
                log.warning("timeline: free blocks %s failed (%s)", source.name, type(exc).__name__)
                db.rollback()
                continue
            truncated = truncated or result.truncated
            free.extend(result.blocks)
            free_sources.append(source.name)
        free.sort(key=lambda b: (b.starts_at, b.ends_at))
    truncated = truncated or req.truncated
    return {
        "date": day.isoformat(),
        "all_day_items": [item_dict(it) for _r, it in day_items[:MAX_ITEMS]],
        "timed_items": [item_dict(it) for _r, it in timed[:max(0, MAX_ITEMS - len(day_items))]],
        "free_blocks": [b.as_dict() for b in free],
        "free_blocks_from": free_sources,  # zdroje obsazenosti pro volno (dnes jen Kalendář – docs/calendar.md)
        "truncated": truncated,
    }
