"""Lokální čas aplikace (Europe/Prague) ↔ UTC.

Konvence úložiště: všechny DateTime sloupce jsou naive UTC (datetime.utcnow).
Kalendářní logika ("dnes", "tento měsíc", "tento týden") se ale počítá v Praze.
Hranice období vrací naive UTC jako polouzavřený interval [start, end) –
v dotazech používej `col >= start AND col < end`.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Europe/Prague")


def utc_now() -> datetime:
    """Aktuální čas jako naive UTC (stejný formát jako ukládané timestampy)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt_utc: datetime) -> datetime:
    """Naive UTC (nebo aware) → aware čas v Europe/Prague."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(APP_TZ)


def local_to_utc(dt_local: datetime) -> datetime:
    """Naive pražský čas (nebo aware) → naive UTC pro uložení / dotazy."""
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=APP_TZ)
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def now_local(now_utc: datetime | None = None) -> datetime:
    """Aware aktuální čas v Europe/Prague (now_utc = naive UTC pro testy)."""
    return to_local(now_utc if now_utc is not None else utc_now())


def today_local(now_utc: datetime | None = None) -> date:
    return now_local(now_utc).date()


def _local_midnight_utc(d: date) -> datetime:
    return local_to_utc(datetime.combine(d, time.min))


def local_day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """[pražská půlnoc dne d, pražská půlnoc dne d+1) v naive UTC (23/24/25 h dle DST)."""
    return _local_midnight_utc(d), _local_midnight_utc(d + timedelta(days=1))


def local_week_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """ISO týden (pondělí–neděle) obsahující d, v naive UTC."""
    monday = d - timedelta(days=d.weekday())
    return _local_midnight_utc(monday), _local_midnight_utc(monday + timedelta(days=7))


def local_month_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """Kalendářní měsíc obsahující d, v naive UTC."""
    first = d.replace(day=1)
    next_first = (first + timedelta(days=32)).replace(day=1)
    return _local_midnight_utc(first), _local_midnight_utc(next_first)
