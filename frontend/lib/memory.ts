/**
 * Paměť AI (dlouhodobé poznámky): české popisky kategorií, dotaz pro filtry a payload formuláře.
 * Roadmap 4B. Čisté funkce, testy: memory.test.mjs.
 */
import { filterQuery } from "./filters.ts";

/** Popisky kategorií žijí v lib/labels.ts (jedno kanonické mapování). */
export { memoryCategoryLabel } from "./labels.ts";

export type MemoryFilters = { q: string; area: string; category: string; includeInactive: boolean };

export const EMPTY_MEMORY_FILTERS: MemoryFilters = { q: "", area: "all", category: "all", includeInactive: false };

/** GET /memories – stejné parametry jako dřív (q, area, category, include_inactive). */
export function memoryQuery(f: MemoryFilters): string {
  return filterQuery({ q: f.q, area: f.area, category: f.category, include_inactive: f.includeInactive });
}

export type MemoryKind = "fact" | "temporary" | "decision";

export type MemoryDraft = {
  area: string;
  category: string;
  content: string;
  importance: number;
  active: boolean;
  /** MRK-117: druh a platnost (jen při přidání; `expiresLocal` = hodnota datetime-local v pražském čase). */
  kind?: MemoryKind;
  expiresLocal?: string;
};

export const MEMORY_KIND_LABELS: Record<MemoryKind, string> = { fact: "Fakt", temporary: "Dočasná", decision: "Rozhodnutí" };

export function memoryKindLabel(kind: string | null | undefined): string {
  return MEMORY_KIND_LABELS[(kind ?? "fact") as MemoryKind] ?? String(kind);
}

/** Tělo POST /memory i PATCH /memory/{id}: prázdná oblast → general, kategorie → context. Druh/platnost jen když jsou. */
export function memoryPayload(d: MemoryDraft): Record<string, unknown> {
  const body: Record<string, unknown> = {
    area: d.area.trim() || "general",
    category: d.category.trim() || "context",
    content: d.content.trim(),
    importance: d.importance,
    active: d.active,
  };
  if (d.kind) body.kind = d.kind;
  // datetime-local je čas prohlížeče (Praha) → ISO s „Z"; backend ho uloží jako naive UTC
  if (d.expiresLocal && !Number.isNaN(Date.parse(d.expiresLocal))) body.expires_at = new Date(d.expiresLocal).toISOString();
  return body;
}

/** Kontrola před odesláním: dočasná potřebuje platnost v budoucnu. Vrací chybu česky nebo null. */
export function validateMemoryDraft(d: MemoryDraft, now: Date = new Date()): string | null {
  if (!d.content.trim()) return "Vyplň obsah poznámky.";
  const expires = d.expiresLocal ? Date.parse(d.expiresLocal) : NaN;
  if (d.kind === "temporary" && Number.isNaN(expires)) return "Dočasná vzpomínka potřebuje datum platnosti.";
  if (!Number.isNaN(expires) && expires <= now.getTime()) return "Platnost musí být v budoucnosti.";
  return null;
}

export type MemoryValidity = { expired: boolean; label: string | null };

/** „Platí do 29. 11. 2026 23:59" / „Vypršela 20. 11. …" – `expiresAt` je naive UTC z backendu (bez „Z"). */
export function memoryValidity(expiresAt: string | null | undefined, now: Date = new Date(), format: (d: Date) => string = defaultFormat): MemoryValidity {
  if (!expiresAt) return { expired: false, label: null };
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(expiresAt) ? expiresAt : `${expiresAt}Z`;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return { expired: false, label: null };
  const expired = t <= now.getTime();
  return { expired, label: `${expired ? "Vypršela" : "Platí do"} ${format(new Date(t))}` };
}

function defaultFormat(d: Date): string {
  return d.toLocaleString("cs-CZ", { timeZone: "Europe/Prague", day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export type ValidityFilter = "all" | "valid" | "expired";

export function matchesValidity(expiresAt: string | null | undefined, filter: ValidityFilter, now: Date = new Date()): boolean {
  if (filter === "all") return true;
  const { expired } = memoryValidity(expiresAt, now);
  return filter === "expired" ? expired : !expired;
}

/** Seřazené unikátní hodnoty (pro výběr oblasti/kategorie). */
export function distinctSorted(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((v): v is string => Boolean(v && v.trim())))).sort((a, b) => a.localeCompare(b, "cs"));
}
