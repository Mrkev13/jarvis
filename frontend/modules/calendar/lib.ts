import { pragueDayKey } from '../../lib/format.ts';

export interface CalendarEvent {
  id: number;
  source_id: number;
  title: string;
  location: string | null;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  starts_on: string | null;
  ends_on: string | null;
  status: 'active' | 'cancelled';
  rrule: string | null;
}
export interface CalendarPayload {
  today: string;
  events: CalendarEvent[];
  sources: { id: number; name: string; enabled: boolean; configured: boolean }[];
  moodle_configured: boolean;
}

export function groupEvents(events: CalendarEvent[], today: string) {
  const groups: Record<'today' | 'upcoming' | 'cancelled' | 'past', CalendarEvent[]> = {
    today: [], upcoming: [], cancelled: [], past: [],
  };
  for (const event of [...events].sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime() || a.id - b.id)) {
    const day = event.all_day ? event.starts_on! : pragueDayKey(event.starts_at);
    const end = new Date(event.ends_at).getTime();
    const start = new Date(event.starts_at).getTime();
    const lastDay = event.all_day ? event.ends_on! : pragueDayKey(new Date(end > start ? end - 1 : end));
    if (event.status === 'cancelled') groups.cancelled.push(event);
    else if (day <= today && (event.all_day ? today < lastDay : today <= lastDay)) groups.today.push(event);
    else if (day > today) groups.upcoming.push(event);
    else groups.past.push(event);
  }
  return groups;
}

function shortDate(value: string) {
  return new Intl.DateTimeFormat('cs-CZ', { day: 'numeric', month: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(value + 'T00:00:00Z'));
}

export function eventTime(event: CalendarEvent): string {
  if (event.all_day) {
    const last = new Date(event.ends_on! + 'T00:00:00Z');
    last.setUTCDate(last.getUTCDate() - 1);
    const lastDay = last.toISOString().slice(0, 10);
    return `Celý den · ${shortDate(event.starts_on!)}${lastDay === event.starts_on ? '' : ` – ${shortDate(lastDay)}`}`;
  }
  const day = new Intl.DateTimeFormat('cs-CZ', { day: 'numeric', month: 'numeric', year: 'numeric', timeZone: 'Europe/Prague' });
  const clock = new Intl.DateTimeFormat('cs-CZ', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Prague' });
  const start = new Date(event.starts_at), end = new Date(event.ends_at);
  const finish = start.getTime() === end.getTime() ? '' :
    ` – ${pragueDayKey(start) !== pragueDayKey(end) ? day.format(end) + ' ' : ''}${clock.format(end)}`;
  return `${day.format(start)} · ${clock.format(start)}${finish}`;
}

export function eventState(event: CalendarEvent) {
  return event.status === 'cancelled' ? 'Zrušeno' : 'Událost';
}
