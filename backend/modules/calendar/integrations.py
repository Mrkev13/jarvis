"""Calendar supplies data through framework contributions, never aggregator branches."""
from datetime import timedelta

from context_format import short
from module_contracts import ChangeSource, ContextSection, EntityRef, ModuleIntegrations, SearchSource, TodaySource, event_changes
from modules.calendar.models import CalendarEvent
from modules.calendar.occurrences import get_calendar_occurrences, local_window
from modules.calendar.router import router
from time_utils import to_local
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
    return lines or ['Kalendář: žádné události v příštích 7 dnech.']


INTEGRATIONS = ModuleIntegrations(
    search=(SearchSource('calendar', 85, search_events),),
    today=(TodaySource('calendar', 35, timeline=timeline, upcoming=upcoming),),
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
