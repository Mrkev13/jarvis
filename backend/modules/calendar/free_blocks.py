"""Free blocks (MRK-32): "when am I free between two times?" – a deterministic projection, never stored.

Source of busy time = active Calendar occurrences (`get_calendar_occurrences`, called once per query), so
recurrence, EXDATE, moved/cancelled overrides, cancelled and source-missing records are already resolved there.

1. every local (Europe/Prague) day in the range gets a window [day_start, day_end] built with zoneinfo, so a DST
   day keeps real lengths (no naive hour arithmetic); windows are clipped to the query;
2. busy intervals: timed occurrences ± optional buffer; all-day ones only with `all_day_busy` (they don't block the
   day by default – MRK-32 acceptance); zero-length events block nothing but their buffer;
3. busy intervals are sorted and merged (overlapping, nested and touching ones become one), then subtracted;
4. blocks shorter than `min_minutes` (exact elapsed time) are dropped; output is ordered by start.

Nothing here writes Activity, domain events, Search or What Changed: free time is derived, not a fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from modules.calendar.occurrences import MAX_OCCURRENCES, get_calendar_occurrences, local_window
from time_utils import APP_TZ

UTC = timezone.utc
MAX_DAYS = 31
MIN_MINUTES_RANGE = (5, 720)
BUFFER_RANGE = (0, 120)
DEFAULT_DAY_START = time(7, 0)
DEFAULT_DAY_END = time(22, 0)
MAX_BLOCKS = 500


class FreeBlockError(ValueError):
    """Invalid free-block query (→ 422)."""


@dataclass(frozen=True)
class FreeBlock:
    starts_at: datetime  # aware UTC
    ends_at: datetime

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    def as_dict(self) -> dict:
        start, end = self.starts_at.astimezone(APP_TZ), self.ends_at.astimezone(APP_TZ)
        return {
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "local_date": start.date().isoformat(),
            "local_start": start.strftime("%H:%M"),
            "local_end": "24:00" if end.date() > start.date() and end.time() == time.min else end.strftime("%H:%M"),
            "duration_minutes": self.duration_minutes,
        }


@dataclass(frozen=True)
class FreeBlockResult:
    blocks: tuple[FreeBlock, ...]
    truncated: bool  # occurrence or block cap reached: busy time may be incomplete, never claim more


def _windows(first: date, last: date, day_start: time, day_end: time | None, lo: datetime, hi: datetime):
    """Local day windows (DST-aware); `day_end=None` = next local midnight."""
    day = first
    while day <= last:
        start = datetime.combine(day, day_start, APP_TZ).astimezone(UTC)
        end = (local_window(day, day + timedelta(days=1))[1] if day_end is None
               else datetime.combine(day, day_end, APP_TZ).astimezone(UTC))
        start, end = max(start, lo), min(end, hi)
        if end > start:
            yield start, end
        day += timedelta(days=1)


def merge_intervals(intervals):
    """Sorted, merged busy intervals: overlapping, nested and touching ones become one."""
    merged: list[list[datetime]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def subtract(window, busy):
    """Free parts of one window minus merged (sorted) busy intervals."""
    start, end = window
    cursor, out = start, []
    for b_start, b_end in busy:
        if b_end <= cursor or b_start >= end:
            continue
        if b_start > cursor:
            out.append((cursor, min(b_start, end)))
        cursor = max(cursor, b_end)
        if cursor >= end:
            break
    if cursor < end:
        out.append((cursor, end))
    return out


def get_free_blocks(db, *, start: datetime, end: datetime, min_minutes: int = 30,
                    day_start: time = DEFAULT_DAY_START, day_end: time | None = DEFAULT_DAY_END,
                    buffer_minutes: int = 0, all_day_busy: bool = False,
                    occurrences: list | None = None) -> FreeBlockResult:
    """`occurrences`: already loaded active occurrences covering [start - buffer, end + buffer] (the day timeline
    shares its single load); None = load them here, once."""
    if start.tzinfo is None or end.tzinfo is None:
        raise FreeBlockError("window must be timezone-aware")
    if end <= start:
        raise FreeBlockError("window end must be after its start")
    if end - start > timedelta(days=MAX_DAYS, hours=1):  # 31 local days may be 31 d + 1 h across autumn DST
        raise FreeBlockError("window is too large")
    if not MIN_MINUTES_RANGE[0] <= min_minutes <= MIN_MINUTES_RANGE[1]:
        raise FreeBlockError("min_minutes out of range")
    if not BUFFER_RANGE[0] <= buffer_minutes <= BUFFER_RANGE[1]:
        raise FreeBlockError("buffer_minutes out of range")
    if day_end is not None and day_end <= day_start:
        raise FreeBlockError("day_end must be after day_start")
    lo, hi = start.astimezone(UTC), end.astimezone(UTC)
    buffer = timedelta(minutes=buffer_minutes)

    # One occurrence query for the whole range (+ buffer on both sides): no per-day loops over the database.
    if occurrences is None:
        occurrences = get_calendar_occurrences(db, lo - buffer, hi + buffer)
    truncated = len(occurrences) >= MAX_OCCURRENCES
    busy = []
    for o in occurrences:
        if o.all_day:
            if not all_day_busy:
                continue
            o_start, o_end = local_window(o.starts_on, o.ends_on)  # Prague days, like the occurrence layer
        else:
            o_start, o_end = o.starts_at, o.ends_at
        busy.append((max(o_start - buffer, lo), min(o_end + buffer, hi)))
    busy = merge_intervals(busy)

    minimum = timedelta(minutes=min_minutes)
    blocks = []
    first, last = lo.astimezone(APP_TZ).date(), hi.astimezone(APP_TZ).date()
    for window in _windows(first, last, day_start, day_end, lo, hi):
        for free_start, free_end in subtract(window, busy):
            if free_end - free_start >= minimum:
                blocks.append(FreeBlock(free_start, free_end))
    if len(blocks) > MAX_BLOCKS:
        blocks, truncated = blocks[:MAX_BLOCKS], True
    return FreeBlockResult(tuple(blocks), truncated)


def free_blocks_between(db, start_day: date, end_day: date, **options) -> dict:
    """API shape for local days [start_day, end_day)."""
    if end_day <= start_day or (end_day - start_day).days > MAX_DAYS:
        raise FreeBlockError("window must be 1–31 days")
    lo, hi = local_window(start_day, end_day)
    result = get_free_blocks(db, start=lo, end=hi, **options)
    return {"start": start_day.isoformat(), "end": end_day.isoformat(),
            "min_minutes": options.get("min_minutes", 30), "truncated": result.truncated,
            "blocks": [b.as_dict() for b in result.blocks]}
