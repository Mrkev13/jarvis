/**
 * MRK-106: tabulka M-ek všech tanků (backend `GET /wot/mastery`, snapshot z Wargaming API) – čisté funkce pro filtry
 * a řazení (testy: wotMastery.test.mjs). API zná jen NEJVYŠŠÍ odznak na tank; `ace_count` = M milníky v Hubu
 * (včetně opakovaných ručních).
 */
export type MasteryMark = 0 | 1 | 2 | 3 | 4;

export type MasteryRow = {
  tank_id: number;
  name: string;
  short_name: string | null;
  tag: string | null;
  tier: number | null;
  nation: string | null;
  nation_label: string | null;
  type: string | null;
  type_label: string | null;
  mark: MasteryMark;
  mark_label: string;
  battles: number | null;
  ace_count: number;
  ace_detected_at: string | null;
  ace_milestone_id: number | null;
  pending_replay: boolean;
};

export type MasteryOverview = {
  config: { configured: boolean; region: string | null };
  summary: {
    tanks: number;
    with_ace: number;
    by_mark: Record<"M" | "I" | "II" | "III" | "–", number>;
    last_synced_at: string | null;
    pending_replays: number;
  };
  tanks: MasteryRow[];
};

export type MasteryFilter = { tier: number | null; nation: string | null; missingOnly: boolean; q: string };
export type MasterySort = "tier" | "mark" | "name" | "battles";

export const EMPTY_FILTER: MasteryFilter = { tier: null, nation: null, missingOnly: false, q: "" };

const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"];
export function tierLabel(tier: number | null | undefined): string {
  return tier != null && ROMAN[tier] ? ROMAN[tier] : "–";
}

const norm = (s: string | null | undefined) => (s ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Filtr tabulky: tier, národ, „jen bez M“ (= co dohrát) a hledání v názvu. */
export function filterMastery(rows: MasteryRow[], f: MasteryFilter): MasteryRow[] {
  const q = norm(f.q.trim());
  return rows.filter((r) =>
    (f.tier == null || r.tier === f.tier) &&
    (f.nation == null || r.nation === f.nation) &&
    (!f.missingOnly || r.mark < 4) &&
    (!q || norm(r.name).includes(q) || norm(r.short_name).includes(q)));
}

/** Řazení: tier (nejvyšší nahoře), odznak (nejlepší nahoře), název, počet bitev. Stabilní dorovnání názvem. */
export function sortMastery(rows: MasteryRow[], by: MasterySort): MasteryRow[] {
  const name = (a: MasteryRow, b: MasteryRow) => a.name.localeCompare(b.name, "cs");
  const cmp: Record<MasterySort, (a: MasteryRow, b: MasteryRow) => number> = {
    tier: (a, b) => (b.tier ?? 0) - (a.tier ?? 0) || b.mark - a.mark || name(a, b),
    mark: (a, b) => b.mark - a.mark || (b.tier ?? 0) - (a.tier ?? 0) || name(a, b),
    name,
    battles: (a, b) => (b.battles ?? 0) - (a.battles ?? 0) || name(a, b),
  };
  return [...rows].sort(cmp[by]);
}

/** Možnosti filtrů z dat: tiery sestupně, národy podle názvu. */
export function masteryOptions(rows: MasteryRow[]): { tiers: number[]; nations: { value: string; label: string }[] } {
  const tiers = [...new Set(rows.map((r) => r.tier).filter((t): t is number => t != null))].sort((a, b) => b - a);
  const nations = new Map<string, string>();
  for (const r of rows) if (r.nation) nations.set(r.nation, r.nation_label ?? r.nation);
  return { tiers, nations: [...nations].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label, "cs")) };
}

/** „M ×3“ když Hub ví o opakovaných M (ruční milníky), jinak jen štítek odznaku. */
export function markText(r: Pick<MasteryRow, "mark" | "mark_label" | "ace_count">): string {
  return r.mark === 4 && r.ace_count > 1 ? `M ×${r.ace_count}` : r.mark_label;
}
