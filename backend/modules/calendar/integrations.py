"""Calendar supplies data through framework contributions, never aggregator branches."""
from datetime import datetime, time, timedelta, timezone

from context_format import short
from module_contracts import ChangeSource, ContextSection, EntityRef, ModuleIntegrations, SearchSource, TodaySource, event_changes
from modules.calendar.models import CalendarEvent
from modules.calendar.router import router
from time_utils import APP_TZ, to_local
from today_types import TodayItem, UPCOMING_DAYS


def _window(db, start, end):
    lower = datetime.combine(start, time.min, APP_TZ).astimezone(timezone.utc)
    upper = datetime.combine(end, time.min, APP_TZ).astimezone(timezone.utc)
    return (db.query(CalendarEvent).filter(CalendarEvent.status == 'active',
                ((CalendarEvent.all_day.is_(True) & (CalendarEvent.starts_on < end) & (CalendarEvent.ends_on > start)) |
                 (CalendarEvent.all_day.is_(False) & (CalendarEvent.starts_at < upper) &
                  ((CalendarEvent.ends_at > lower) | (CalendarEvent.starts_at >= lower)))))
            .order_by(CalendarEvent.starts_at, CalendarEvent.id).limit(200).all())


def _item(row, today):
    local = to_local(row.starts_at)
    display_day = max(row.starts_on if row.all_day else local.date(), today)
    return TodayItem(id=f'calendar_event:{row.id}', type='calendar_event', title=row.title,
                     subtitle=' · '.join(filter(None, ['Celý den' if row.all_day else 'Událost', row.location])),
                     area='calendar', date=display_day.isoformat(), time=None if row.all_day else local.strftime('%H:%M'),
                     status='upcoming', href=f'/calendar?event={row.id}', source_id=row.id)


def timeline(c):
    return [_item(e, c.today) for e in _window(c.db, c.today, c.today + timedelta(days=1))]


def upcoming(c):
    return [_item(e, c.today + timedelta(days=1)) for e in
            _window(c.db, c.today + timedelta(days=1), c.today + timedelta(days=UPCOMING_DAYS + 1))
            if (e.starts_on if e.all_day else to_local(e.starts_at).date()) > c.today]


def search_events(db, q):
    # Global Search owns normalization/diacritic folding and matching policy.
    for e in (db.query(CalendarEvent)
              .order_by(CalendarEvent.starts_at.desc(), CalendarEvent.id).limit(500).all()):
        subtitle = ' · '.join(filter(None, [e.starts_on.isoformat() if e.all_day else to_local(e.starts_at).strftime('%d.%m.%Y %H:%M'),
                                           e.location, 'zrušeno' if e.status == 'cancelled' else None]))
        yield 'calendar_event', e.id, e.title, subtitle, 'kalendar calendar udalost', 'calendar', f'/calendar?event={e.id}'


def context_events(req):
    rows = _window(req.db, req.today, req.today + timedelta(days=8))
    # Bounds/token policy stays global. This section contributes a small, deterministic snapshot.
    lines = []
    for row in rows[:8]:
        local = to_local(row.starts_at)
        when = row.starts_on.isoformat() + ' celý den' if row.all_day else local.strftime('%Y-%m-%d %H:%M')
        lines.append(f'Kalendář: {when} {short(row.title, 60)}')
    return lines or ['Kalendář: žádné události v příštích 7 dnech.']


INTEGRATIONS = ModuleIntegrations(
    search=(SearchSource('calendar', 85, search_events),),
    today=(TodaySource('calendar', 35, timeline=timeline, upcoming=upcoming),),
    entity_refs=(EntityRef('calendar_event', '/calendar?event={id}'),),
    context=(ContextSection('calendar', ('kalendar', 'calendar', 'udalost', 'rozvrh', 'prednask', 'schuzk'),
                            order=85, build=context_events),),
    changes=(ChangeSource('calendar', from_event=event_changes({'calendar_event': '/calendar?event={id}'},
                            {'calendar.event.created': 'Událost přidána', 'calendar.event.updated': 'Událost změněna',
                             'calendar.event.cancelled': 'Událost zrušena'})),),
    routers=(router,),
)
