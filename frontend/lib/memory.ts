/**
 * Paměť AI (dlouhodobé poznámky): české popisky kategorií, dotaz pro filtry a payload formuláře.
 * Roadmap 4B. Čisté funkce, testy: memory.test.mjs.
 */
import { filterQuery } from "./filters.ts";

const CATEGORY_LABELS: Record<string, string> = {
  context: "Kontext",
  preference: "Preference",
  goal: "Cíl",
  fact: "Fakt",
  habit: "Zvyk",
  rule: "Pravidlo",
  work: "Práce",
  note: "Poznámka",
};

/** Kategorie je volný text – známé dostanou český popisek, ostatní zůstávají. */
export function memoryCategoryLabel(category: string | null | undefined): string {
  const c = String(category ?? "").trim();
  return CATEGORY_LABELS[c.toLowerCase()] ?? (c || "–");
}

export type MemoryFilters = { q: string; area: string; category: string; includeInactive: boolean };

export const EMPTY_MEMORY_FILTERS: MemoryFilters = { q: "", area: "all", category: "all", includeInactive: false };

/** GET /memories – stejné parametry jako dřív (q, area, category, include_inactive). */
export function memoryQuery(f: MemoryFilters): string {
  return filterQuery({ q: f.q, area: f.area, category: f.category, include_inactive: f.includeInactive });
}

export type MemoryDraft = { area: string; category: string; content: string; importance: number; active: boolean };

/** Tělo POST /memory i PATCH /memory/{id}: prázdná oblast → general, kategorie → context. */
export function memoryPayload(d: MemoryDraft): MemoryDraft {
  return {
    area: d.area.trim() || "general",
    category: d.category.trim() || "context",
    content: d.content.trim(),
    importance: d.importance,
    active: d.active,
  };
}

/** Seřazené unikátní hodnoty (pro výběr oblasti/kategorie). */
export function distinctSorted(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((v): v is string => Boolean(v && v.trim())))).sort((a, b) => a.localeCompare(b, "cs"));
}
