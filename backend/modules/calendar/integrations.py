"""Calendar supplies data through framework contributions, never aggregator branches."""
from datetime import datetime, time, timedelta, timezone

from context_format import short
from module_contracts import (
    ChangeSource, ContextSection, EntityRef, ModuleIntegrations, SearchSource, TimelineItem, TimelineSource, TodaySource,
    event_changes,
)
from modules.calendar.models import CalendarEvent
from modules.calendar.free_blocks import get_free_blocks
from modules.calendar.occurrences import MAX_OCCURRENCES, get_calendar_occurrences, local_window
from modules.calendar.router import router
from time_utils import APP_TZ, to_local
from today_types import TodayItem, UPCOMING_DAYS


def _occurrences(db, start, end):
    """MRK-40: actual active occurrences (recurrences expanded, cancelled/source-missing excluded) for local days."""
    return get_calendar_occurrences(db, *local_window(start, end), limit=200)


def _ref(o):
    # A recurring master yields several instances: the key keeps each Today item distinct for global dedupe.
    return f'calendar_event:{o.event_id}' + (f'@{o.recurrence_key}' if o.recurring else '')


def _start_day(o):
    return o.starts_on if o.all_day else to_local(o.starts_at).date()


def _item(o, today):
    local = to_local(o.starts_at)
    display_day = max(_start_day(o), today)
    return TodayItem(id=_ref(o), type='calendar_event', title=o.title,
                     subtitle=' · '.join(filter(None, ['Celý den' if o.all_day else 'Událost', o.location])),
                     area='calendar', date=display_day.isoformat(), time=None if o.all_day else local.strftime('%H:%M'),
                     status='upcoming', href=f'/calendar?event={o.event_id}', source_id=o.event_id)


def timeline(c):
    return [_item(o, c.today) for o in _occurrences(c.db, c.today, c.today + timedelta(days=1))]


def upcoming(c):
    return [_item(o, c.today + timedelta(days=1)) for o in
            _occurrences(c.db, c.today + timedelta(days=1), c.today + timedelta(days=UPCOMING_DAYS + 1))
            if _start_day(o) > c.today]


def search_events(db, q):
    # Definitions, not generated instances (Search must not expand thousands of occurrences).
    # Global Search owns normalization/diacritic folding and matching policy.
    for e in (db.query(CalendarEvent)
              .order_by(CalendarEvent.starts_at.desc(), CalendarEvent.id).limit(500).all()):
        when = e.starts_on.isoformat() if e.all_day else to_local(e.starts_at).strftime('%d.%m.%Y %H:%M')
        subtitle = ' · '.join(filter(None, [f'opakuje se od {when}' if e.rrule else when, e.location,
                                           'zrušeno' if e.status == 'cancelled' else None,
                                           'zmizelo ze zdroje' if e.source_missing_at else None]))
        yield 'calendar_event', e.id, e.title, subtitle, 'kalendar calendar udalost', 'calendar', f'/calendar?event={e.id}'


def context_events(req):
    rows = _occurrences(req.db, req.today, req.today + timedelta(days=8))
    # Bounds/token policy stays global. This section contributes a small, deterministic snapshot.
    lines = []
    for o in rows[:8]:
        when = o.starts_on.isoformat() + ' celý den' if o.all_day else to_local(o.starts_at).strftime('%Y-%m-%d %H:%M')
        lines.append(f'Kalendář: {when} {short(o.title, 60)}')
    lines = lines or ['Kalendář: žádné události v příštích 7 dnech.']
    return lines + _free_block_lines(req)


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return ' '.join(filter(None, [f'{hours} h' if hours else '', f'{rest} min' if rest else '']))


def _free_block_lines(req) -> list[str]:
    """MRK-32: deterministic free time (default 07:00–22:00, ≥ 30 min) for the rest of today and tomorrow."""
    now = req.local_now.replace(tzinfo=APP_TZ) if req.local_now.tzinfo is None else req.local_now
    lower = max(now, datetime.combine(req.today, time.min, APP_TZ))
    upper = local_window(req.today, req.today + timedelta(days=2))[1]
    if upper <= lower:
        return []
    result = get_free_blocks(req.db, start=lower, end=upper)
    blocks = result.blocks
    # partial busy data must never read as an authoritative schedule
    caveat = ' – neúplné (příliš mnoho událostí), neber jako jisté' if result.truncated else ''
    lines = []
    for label, day in (('dnes', req.today), ('zítra', req.today + timedelta(days=1))):
        chosen = [b.as_dict() for b in blocks if b.starts_at.astimezone(APP_TZ).date() == day][:3]
        text = ', '.join(f"{b['local_start']}–{b['local_end']} ({_duration(b['duration_minutes'])})" for b in chosen)
        lines.append(f'Kalendář – volno {label} (07–22, min. 30 min): {text or "žádné"}{caveat}')
    return lines


def _next_free_block(c):
    """One derived result per Today request; the tomorrow fallback belongs only in Upcoming."""
    key = 'calendar.next_free_block'
    if key not in c.cache:
        now = c.now_utc.replace(tzinfo=timezone.utc) if c.now_utc.tzinfo is None else c.now_utc
        lower = max(now, local_window(c.today, c.today + timedelta(days=1))[0])
        upper = local_window(c.today, c.today + timedelta(days=2))[1]
        result = get_free_blocks(c.db, start=lower, end=upper, min_minutes=30)
        if result.truncated:
            c.cache[key] = TodayItem(
                id=f'calendar_free_block:uncertain:{c.today}', type='calendar_free_block',
                title='Volno nelze spolehlivě určit', subtitle='Neúplná data kalendáře; zkontroluj týdenní přehled.',
                area='calendar', date=c.today.isoformat(), severity='warning', href='/calendar')
        elif result.blocks:
            block = result.blocks[0].as_dict()
            c.cache[key] = TodayItem(
                id=f"calendar_free_block:{block['starts_at']}", type='calendar_free_block',
                title=f"Volno {block['local_start']}–{block['local_end']} ({_duration(block['duration_minutes'])})",
                subtitle='Podle Kalendáře · 07–22 · alespoň 30 min', area='calendar',
                date=block['local_date'], time=block['local_start'], status='open', href='/calendar')
        else:
            c.cache[key] = None
    return c.cache[key]


def next_free_block_today(c):
    item = _next_free_block(c)
    return [item] if item and item.date == c.today.isoformat() else []


def next_free_block_upcoming(c):
    item = _next_free_block(c)
    return [item] if item and item.date != c.today.isoformat() else []


# ---------- denní osa (MRK-13) ----------

_OCCURRENCES = 'calendar.occurrences'


def _day_occurrences(req):
    """One occurrence load per timeline request, shared by the items and the free blocks."""
    if _OCCURRENCES not in req.cache:
        req.cache[_OCCURRENCES] = get_calendar_occurrences(req.db, req.start, req.end)
        if len(req.cache[_OCCURRENCES]) >= MAX_OCCURRENCES:
            req.truncated = True  # capped load: the day may be incomplete even without free blocks
    return req.cache[_OCCURRENCES]


def _timeline_status(o, now):
    if (o.ends_at > o.starts_at and o.ends_at <= now) or (o.ends_at == o.starts_at and o.starts_at < now):
        return 'past'
    return 'now' if o.starts_at <= now < o.ends_at else 'upcoming'


def timeline_items(req):
    items = []
    for o in _day_occurrences(req):
        items.append(TimelineItem(
            id=_ref(o), kind='calendar_event', title=o.title, date=req.day.isoformat(),
            status=_timeline_status(o, req.now), subtitle=' · '.join(filter(None, ['Opakuje se' if o.recurring else '', o.location])),
            starts_at=None if o.all_day else o.starts_at, ends_at=None if o.all_day else o.ends_at, all_day=o.all_day,
            href=f'/calendar?event={o.event_id}', busy=not o.all_day))
    return items


def timeline_free_blocks(req, min_minutes):
    return get_free_blocks(req.db, start=req.start, end=req.end, min_minutes=min_minutes,
                           occurrences=_day_occurrences(req))


INTEGRATIONS = ModuleIntegrations(
    search=(SearchSource('calendar', 85, search_events),),
    today=(TodaySource('calendar', 35, timeline=timeline, upcoming=upcoming),
           TodaySource('calendar_free_block', 36, timeline=next_free_block_today, upcoming=next_free_block_upcoming)),
    timeline=(TimelineSource('calendar', 30, timeline_items, free_blocks=timeline_free_blocks),),
    entity_refs=(EntityRef('calendar_event', '/calendar?event={id}'),),
    context=(ContextSection('calendar', ('kalendar', 'calendar', 'udalost', 'rozvrh', 'prednask', 'schuzk'),
                            order=85, build=context_events),),
    changes=(ChangeSource('calendar', from_event=event_changes({'calendar_event': '/calendar?event={id}'},
                            {'calendar.event.created': 'Událost přidána', 'calendar.event.updated': 'Událost změněna',
                             'calendar.event.cancelled': 'Událost zrušena',
                             'calendar.event.source_missing': 'Událost zmizela ze zdroje',
                             'calendar.event.restored': 'Událost je zpět ve zdroji'})),),
    routers=(router,),
)
