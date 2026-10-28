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
  sources: { id: number; name: string; enabled: boolean; configured: boolean; key?: string | null }[];
  moodle_configured: boolean;
  /** MRK-77: every allowlisted ICS source (Moodle, Google…) and whether its private address is set on the server. */
  available_sources?: { key: string; name: string; configured: boolean }[];
  /** At least one source is set up (older backends: only `moodle_configured`). */
  configured?: boolean;
}

type SyncCounts = { created: number; updated: number; cancelled: number; errors: number };
export type SyncResult = SyncCounts & { sources?: Record<string, Partial<SyncCounts> & { error?: string }> };

export function anySourceConfigured(data: Pick<CalendarPayload, 'configured' | 'moodle_configured'>): boolean {
  return data.configured ?? data.moodle_configured;
}

/** „Moodle a Google Kalendář“ – connected sources for the page header; empty when none. */
export function connectedSources(data: Pick<CalendarPayload, 'available_sources'>): string {
  const names = (data.available_sources ?? []).filter(s => s.configured).map(s => s.name);
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} a ${names[names.length - 1]}` : names[0] ?? '';
}

/** Notice after POST /calendar/sync: summed counts, then each source that failed (names only, never a reason text). */
export function syncNotice(result: SyncResult, available: CalendarPayload['available_sources'] = []): string {
  const text = `Přidáno ${result.created}, změněno ${result.updated}, zrušeno ${result.cancelled}.`
    + (result.errors ? ` ${result.errors} položek se nepodařilo načíst.` : '');
  const failed = Object.entries(result.sources ?? {}).filter(([, r]) => r.error)
    .map(([key]) => available.find(s => s.key === key)?.name ?? key);
  return failed.length ? `${text} Nepodařilo se načíst: ${failed.join(', ')} (uložené události zůstaly).` : text;
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

// ---------- MRK-13: unified day timeline (GET /timeline/day; projection, never stored) ----------

export interface TimelineItem {
  id: string;
  kind: string;
  module_id: string | null;
  title: string;
  subtitle: string;
  starts_at: string | null;
  ends_at: string | null;
  all_day: boolean;
  date: string;
  status: string;
  href: string | null;
  busy: boolean;
  local_start?: string;
  local_end?: string | null;
}
export interface DayTimelinePayload {
  date: string;
  all_day_items: TimelineItem[];
  timed_items: TimelineItem[];
  free_blocks: FreeBlock[];
  free_blocks_from: string[];
  truncated: boolean;
}
export type DayRow = { type: 'item'; key: string; item: TimelineItem } | { type: 'free'; key: string; block: FreeBlock };

export function timelinePath(day: string, minMinutes = 30): string | null {
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? `/timeline/day?date=${day}&min_minutes=${minMinutes}` : null;
}

/** Timed items and free gaps in one chronological list. Overlapping items stay separate rows (never merged);
 * on the same instant an item comes before a free gap. Server order is kept for items. */
export function dayRows(data: Pick<DayTimelinePayload, 'timed_items' | 'free_blocks'>): DayRow[] {
  const rows: (DayRow & { at: number; rank: number; index: number })[] = [
    ...data.timed_items.map((item, index) => ({ type: 'item' as const, key: item.id, item, at: Date.parse(item.starts_at!), rank: 0, index })),
    ...data.free_blocks.map((block, index) => ({ type: 'free' as const, key: `free:${block.starts_at}`, block, at: Date.parse(block.starts_at), rank: 1, index })),
  ];
  rows.sort((a, b) => a.at - b.at || a.rank - b.rank || a.index - b.index);
  return rows.map(({ at: _at, rank: _rank, index: _index, ...row }) => row as DayRow);
}

export function timelineTime(item: TimelineItem): string {
  if (!item.local_start) return '';
  return item.local_end && item.local_end !== item.local_start ? `${item.local_start}–${item.local_end}` : item.local_start;
}
