import { pragueDayKey } from '../../lib/format.ts';

/** Active occurrence (MRK-40: recurring masters expanded by the backend) or a historical record. */
export interface CalendarEvent {
  /** Stable per-instance key; several occurrences of one recurring event share `id`. */
  key?: string;
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
  /** `source_missing` = no longer in the source's latest complete feed (kept as history, not cancelled). */
  state?: 'active' | 'cancelled' | 'source_missing';
  recurring?: boolean;
}
export interface CalendarPayload {
  today: string;
  events: CalendarEvent[];
  history?: CalendarEvent[];
  selected?: CalendarEvent | null;
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
    if (!isActive(event)) groups.cancelled.push(event);
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

export function isActive(event: CalendarEvent) {
  return event.status !== 'cancelled' && (event.state ?? 'active') === 'active';
}

export function eventState(event: CalendarEvent) {
  if (event.status === 'cancelled' || event.state === 'cancelled') return 'Zrušeno';
  return event.state === 'source_missing' ? 'Zmizelo ze zdroje' : 'Událost';
}

// ---------- MRK-32: free blocks (derived from active occurrences by the backend) ----------

export interface FreeBlock {
  starts_at: string;
  ends_at: string;
  local_date: string;
  local_start: string;
  local_end: string;
  duration_minutes: number;
}
export interface FreeBlocksPayload {
  start: string;
  end: string;
  min_minutes: number;
  truncated: boolean;
  blocks: FreeBlock[];
}

export const FREE_BLOCK_MINUTES = [15, 30, 60, 90, 120] as const;

/** „1 h 30 min", „45 min", „2 h". */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  return [hours ? `${hours} h` : '', rest || !hours ? `${rest} min` : ''].filter(Boolean).join(' ');
}

/** „10:30–12:00 · 1 h 30 min" (backend already gives Prague-local clock times). */
export function freeBlockLabel(block: FreeBlock): string {
  return `${block.local_start}–${block.local_end} · ${formatDuration(block.duration_minutes)}`;
}

/** One local day [day, day+1) with the default 07:00–22:00 bounds; `day` is YYYY-MM-DD. */
export function freeBlocksPath(day: string, minMinutes: number): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const next = new Date(day + 'T00:00:00Z');
  next.setUTCDate(next.getUTCDate() + 1);
  return `/calendar/free-blocks?start=${day}&end=${next.toISOString().slice(0, 10)}&min_minutes=${minMinutes}`;
}
