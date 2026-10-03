/**
 * Aktivita (auditní záznamy): české popisky typů akcí, seskupení po pražských dnech a dotaz pro filtry.
 * Roadmap 4B. Čisté funkce, testy: activity.test.mjs.
 */
import { filterQuery } from "./filters.ts";
import { formatDate, pragueDayEndIso, pragueDayKey, pragueDayStartIso } from "./format.ts";

/** Oblasti, které backend do auditu zapisuje (activity_service.log_activity). */
export const ACTIVITY_AREAS = ["finance", "work", "school", "goals", "memory", "reminders", "mff", "wot", "ai", "system"] as const;

const ACTION_LABELS: Record<string, string> = {
  create: "Vytvořeno",
  update: "Upraveno",
  delete: "Smazáno",
  complete: "Dokončeno",
  snooze: "Odloženo",
  cancel: "Zrušeno",
  approve: "Schváleno",
  reject: "Zamítnuto",
  undo: "Vráceno",
  snapshot: "Snímek",
  sync: "Synchronizace",
  scheduler: "Plánovač",
  backup: "Záloha",
  expire: "Vypršelo",
  error: "Chyba",
};

export const ACTIVITY_ACTIONS = Object.keys(ACTION_LABELS);

export function activityActionLabel(actionType: string): string {
  return ACTION_LABELS[actionType] ?? actionType;
}

export type ActivityFilters = {
  areas: string[];
  actionType: string;
  q: string;
  fromDate: string;
  toDate: string;
};

export const EMPTY_ACTIVITY_FILTERS: ActivityFilters = { areas: [], actionType: "all", q: "", fromDate: "", toDate: "" };

/** Dotaz na GET /activity – data jako hranice pražských dnů v UTC (backend: from_date/to_date). */
export function activityQuery(f: ActivityFilters, limit: number, offset: number): string {
  return filterQuery({
    area: f.areas,
    action_type: f.actionType,
    q: f.q,
    from_date: f.fromDate ? pragueDayStartIso(f.fromDate) : null,
    to_date: f.toDate ? pragueDayEndIso(f.toDate) : null,
    limit,
    offset,
  });
}

/** Seskupení po pražských dnech; pořadí záznamů zůstává (backend řadí od nejnovějších). */
export function groupByDay<T extends { timestamp: string }>(items: T[]): Array<[string, T[]]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const key = pragueDayKey(item.timestamp) || "?";
    const list = map.get(key);
    if (list) list.push(item);
    else map.set(key, [item]);
  }
  return Array.from(map.entries());
}

/** „Dnes" / „Včera" / „5. 10. 2026" – `todayKey` = pražský dnešek (pragueDayKey(new Date())). */
export function dayHeading(key: string, todayKey: string): string {
  if (key === todayKey) return "Dnes";
  const today = Date.parse(`${todayKey}T00:00:00Z`);
  const day = Date.parse(`${key}T00:00:00Z`);
  if (Number.isFinite(today) && Number.isFinite(day) && today - day === 86_400_000) return "Včera";
  return formatDate(key);
}
