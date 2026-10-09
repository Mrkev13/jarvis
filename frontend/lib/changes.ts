/**
 * „Co se změnilo" (MRK-28): typy odpovědi GET /changes, období, dotaz, české popisky druhů změn a reakce na
 * doménové události. Čisté funkce, testy: changes.test.mjs. Kontrakt: docs/what-changed.md.
 */
import { groupByDay } from "./activity.ts";

/** Stabilní tvar položky (backend module_contracts.ChangeItem). */
export interface ChangeItem {
  id: string;
  occurred_at: string;
  module_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  kind: string;
  title: string;
  summary: string;
  href: string | null;
  source: "event" | "activity";
}

export interface ChangeFilter {
  id: string;
  label: string;
  count: number;
}

export interface ChangesResponse {
  since: string;
  items: ChangeItem[];
  total: number;
  truncated: boolean;
  filters: ChangeFilter[];
}

export const CHANGE_PERIODS = [
  { value: "24h", label: "Posledních 24 hodin", ms: 24 * 3_600_000 },
  { value: "7d", label: "Posledních 7 dní", ms: 7 * 86_400_000 },
  { value: "30d", label: "Posledních 30 dní", ms: 30 * 86_400_000 },
] as const;

export type ChangePeriod = (typeof CHANGE_PERIODS)[number]["value"];
export const DEFAULT_PERIOD: ChangePeriod = "7d";
export const CHANGES_LIMIT = 100;
/** Víc událostí rychle za sebou (hromadná změna) = jedno nové načtení. */
export const REFETCH_DEBOUNCE_MS = 600;

/**
 * Dotaz GET /changes. Začátek období se zaokrouhlí dolů na minutu, aby se URL (a tím načtení) neměnila při
 * každém vykreslení; `module` jen když je něco vybráno (prázdný výběr = vše).
 */
export function changesQuery(period: ChangePeriod, modules: ReadonlyArray<string>, now: number = Date.now()): string {
  const ms = CHANGE_PERIODS.find((p) => p.value === period)?.ms ?? CHANGE_PERIODS[1].ms;
  const since = new Date(Math.floor((now - ms) / 60_000) * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  const params = new URLSearchParams({ since, limit: String(CHANGES_LIMIT) });
  if (modules.length) params.set("module", [...modules].sort().join(","));
  return params.toString();
}

const KIND_LABELS: Record<string, string> = {
  created: "Nové",
  updated: "Upraveno",
  deleted: "Smazáno",
  completed: "Splněno",
  reopened: "Znovu otevřeno",
  closed: "Uzavřeno",
  done: "Splněno",
  skipped: "Přeskočeno",
  archived: "Archivováno",
  restored: "Obnoveno",
  snoozed: "Odloženo",
  cancelled: "Zrušeno",
  source_missing: "Zmizelo ze zdroje",
};

export function changeKindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? "Změna";
}

export type ChangeTone = "success" | "warning" | "neutral";

export function changeKindTone(kind: string): ChangeTone {
  if (kind === "completed" || kind === "done" || kind === "closed") return "success";
  if (kind === "deleted" || kind === "cancelled" || kind === "source_missing") return "warning";
  return "neutral";
}

/** Seskupení po pražských dnech (stejné jako Aktivita), nejnovější den první. */
export function groupChangesByDay(items: ChangeItem[]): Array<[string, ChangeItem[]]> {
  return groupByDay(items.map((item) => ({ timestamp: item.occurred_at, item }))).map(
    ([day, list]) => [day, list.map((x) => x.item)] as [string, ChangeItem[]],
  );
}

/** Vybrané filtry, které v novém období už nemají žádnou položku, zmizí (jinak by nešly odškrtnout). */
export function keepKnownFilters(selected: ReadonlyArray<string>, filters: ReadonlyArray<ChangeFilter>): string[] {
  const known = new Set(filters.map((f) => f.id));
  return selected.filter((id) => known.has(id));
}

/**
 * Debounce pro nové načtení po doménové události / resetu streamu (SSE, žádný polling).
 * Vrací `trigger` a `cancel`; časovač je injektovatelný kvůli testům.
 */
export function createRefetchScheduler(
  refetch: () => void,
  delay = REFETCH_DEBOUNCE_MS,
  timers: { set: (fn: () => void, ms: number) => unknown; clear: (h: unknown) => void } = {
    set: (fn, ms) => setTimeout(fn, ms),
    clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
  },
) {
  let handle: unknown = null;
  return {
    trigger() {
      if (handle !== null) timers.clear(handle);
      handle = timers.set(() => {
        handle = null;
        refetch();
      }, delay);
    },
    cancel() {
      if (handle !== null) timers.clear(handle);
      handle = null;
    },
  };
}
