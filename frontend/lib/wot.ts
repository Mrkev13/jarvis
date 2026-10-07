// World of Tanks modul: české popisky, payloady pro backend a odvozená čísla grindů (čistá logika, bez Reactu).
import type { Tone } from "./ui.ts";

export type WotResources = {
  credits?: number;
  gold?: number;
  bonds?: number;
  free_xp?: number;
};

export type WotGrind = {
  id?: number;
  tank: string;
  xp_remaining: number;
  priority: string;
  status: string;
  /** Game Enrichment B: výchozí zbývající XP (základ průběhu), začátek grindu, průběh v % (null = neznámý). */
  xp_start?: number | null;
  started_at?: string | null;
  progress?: number | null;
};

export type GrindDraft = {
  tank: string;
  xp_remaining: string;
  priority: string;
  status: string;
};

export const RESOURCE_KEYS = ["credits", "gold", "bonds", "free_xp"] as const;
export type ResourceKey = (typeof RESOURCE_KEYS)[number];

/** Herní měny zůstávají pod herními názvy (Credits, Gold, Bonds, Free XP). */
export const RESOURCE_LABELS: Record<ResourceKey, string> = {
  credits: "Credits",
  gold: "Gold",
  bonds: "Bonds",
  free_xp: "Free XP",
};

export const GRIND_PRIORITIES = [
  { value: "low", label: "Nízká" },
  { value: "medium", label: "Střední" },
  { value: "high", label: "Vysoká" },
] as const;

export const GRIND_STATUSES = [
  { value: "active", label: "Aktivní" },
  { value: "paused", label: "Pozastaveno" },
  { value: "completed", label: "Dokončeno" },
] as const;

export function emptyGrindDraft(): GrindDraft {
  return { tank: "", xp_remaining: "", priority: "medium", status: "active" };
}

export function grindStatusMeta(status: string | null | undefined): { tone: Tone; label: string } {
  const s = String(status || "active").toLowerCase();
  if (s === "completed") return { tone: "success", label: "Dokončeno" };
  if (s === "paused") return { tone: "neutral", label: "Pozastaveno" };
  if (s === "active") return { tone: "accent", label: "Aktivní" };
  return { tone: "neutral", label: String(status) };
}

/** Jeden POST /wot/resource na každou vyplněnou měnu: { resource, amount }. */
export function resourceEntries(draft: WotResources): { resource: ResourceKey; amount: number }[] {
  return RESOURCE_KEYS.filter((k) => draft[k] !== undefined && draft[k] !== null).map((k) => ({
    resource: k,
    amount: Number(draft[k]),
  }));
}

/** Validace + tělo POST /wot/grind. Vrací chyby polí (česky), nebo hotové tělo. */
export function grindBody(
  draft: GrindDraft,
):
  | { ok: true; body: { tank: string; xp_remaining: number; priority: string; status: string } }
  | { ok: false; errors: { tank?: string; xp_remaining?: string } } {
  const errors: { tank?: string; xp_remaining?: string } = {};
  if (!draft.tank.trim()) errors.tank = "Vyplň název tanku.";
  if (draft.xp_remaining === "") errors.xp_remaining = "Vyplň zbývající XP.";
  if (errors.tank || errors.xp_remaining) return { ok: false, errors };
  return {
    ok: true,
    body: {
      tank: draft.tank.trim(),
      xp_remaining: Number(draft.xp_remaining),
      priority: draft.priority,
      status: draft.status,
    },
  };
}


/** Součet zbývajícího XP aktivních grindů. */
export function activeXpRemaining(grinds: WotGrind[]): number {
  return grinds
    .filter((g) => String(g.status).toLowerCase() === "active")
    .reduce((sum, g) => sum + (Number.isFinite(g.xp_remaining) ? g.xp_remaining : 0), 0);
}

// ===================== Game Enrichment B: splnění, historie, milníky =====================

/** Délka oslavy „GRIND COMPLETE" (ms). Při omezeném pohybu 0 → hned statický splněný stav. */
export const CELEBRATION_MS = 1300;

export function celebrationDuration(reducedMotion: boolean): number {
  return reducedMotion ? 0 : CELEBRATION_MS;
}

export function isCompleted(g: Pick<WotGrind, "status">): boolean {
  return String(g.status || "").toLowerCase() === "completed";
}

/** Aktivní (a pozastavené) grindy; splněné patří do historie. */
export function activeGrinds(grinds: WotGrind[]): WotGrind[] {
  return grinds.filter((g) => !isCompleted(g));
}

/** Průběh v %: z backendu, splněný = 100, jinak dopočet z xp_start; neznámý základ = null (nic se nevymýšlí). */
export function grindProgress(g: WotGrind): number | null {
  if (isCompleted(g)) return 100;
  if (typeof g.progress === "number" && Number.isFinite(g.progress)) return Math.max(0, Math.min(100, Math.round(g.progress)));
  const start = Number(g.xp_start);
  if (!Number.isFinite(start) || start <= 0) return null;
  const rem = Math.max(0, Number(g.xp_remaining) || 0);
  return Math.max(0, Math.min(100, Math.round(((start - rem) / start) * 100)));
}

export type CompletedGrind = {
  id: string;
  completion_id: number | null;
  grind_id: number | null;
  tank: string;
  completed_at: string | null;
  started_at: string | null;
  xp_start: number | null;
  xp_remaining_before: number | null;
  duration_days: number | null;
  legacy: boolean;
};

/** Historie: nejnovější splnění první, záznamy bez data (dřívější „Dokončeno") na konci. */
export function sortCompletions(list: CompletedGrind[]): CompletedGrind[] {
  return [...list].sort((a, b) => {
    if (a.completed_at && b.completed_at) return b.completed_at.localeCompare(a.completed_at);
    if (a.completed_at) return -1;
    if (b.completed_at) return 1;
    return a.tank.localeCompare(b.tank, "cs");
  });
}

export function durationLabel(days: number | null | undefined): string | null {
  if (days === null || days === undefined || !Number.isFinite(days) || days < 0) return null;
  if (days === 0) return "za méně než den";
  if (days === 1) return "za 1 den";
  return days < 5 ? `za ${days} dny` : `za ${days} dní`;
}

// ---------- milníky („Mko") ----------

export const MASTERY_OPTIONS = [
  { value: "ace", label: "Mistr (Mko)" },
  { value: "first", label: "1. třída" },
  { value: "second", label: "2. třída" },
  { value: "third", label: "3. třída" },
] as const;
export type Mastery = (typeof MASTERY_OPTIONS)[number]["value"];

export function masteryLabel(m: string | null | undefined): string | null {
  return MASTERY_OPTIONS.find((o) => o.value === m)?.label ?? null;
}

export type MilestoneScreenshot = {
  id: number;
  url: string;
  caption: string | null;
  original_name: string | null;
  position: number;
  created_at: string | null;
};

export type WotMilestone = {
  id: number;
  milestone_type: string;
  mastery: Mastery | null;
  tank: string;
  map_name: string | null;
  played_on: string | null;
  damage: number | null;
  assist: number | null;
  kills: number | null;
  base_xp: number | null;
  notes: string | null;
  favorite: boolean;
  created_at: string | null;
  updated_at: string | null;
  screenshots: MilestoneScreenshot[];
  /** Game Enrichment C: propojené replaye (id v knihovně replayů). */
  replay_ids?: number[];
};

export type MilestoneDraft = {
  tank: string;
  map_name: string;
  played_on: string;
  damage: string;
  assist: string;
  kills: string;
  base_xp: string;
  mastery: string;
  notes: string;
  favorite: boolean;
};

export function emptyMilestoneDraft(): MilestoneDraft {
  return { tank: "", map_name: "", played_on: "", damage: "", assist: "", kills: "", base_xp: "", mastery: "ace", notes: "", favorite: false };
}

export function milestoneDraftFrom(m: WotMilestone): MilestoneDraft {
  const n = (v: number | null) => (v === null || v === undefined ? "" : String(v));
  return {
    tank: m.tank,
    map_name: m.map_name ?? "",
    played_on: m.played_on ?? "",
    damage: n(m.damage),
    assist: n(m.assist),
    kills: n(m.kills),
    base_xp: n(m.base_xp),
    mastery: m.mastery ?? "",
    notes: m.notes ?? "",
    favorite: m.favorite,
  };
}

/** Stejné limity jako backend (wot_service.FIELD_LIMITS). */
export const MILESTONE_LIMITS = { damage: 100_000, assist: 100_000, kills: 15, base_xp: 10_000 } as const;
export type NumberField = keyof typeof MILESTONE_LIMITS;
export const NUMBER_LABELS: Record<NumberField, string> = { damage: "Poškození", assist: "Asistence", kills: "Zničení", base_xp: "Základní XP" };

export type MilestoneErrors = Partial<Record<keyof MilestoneDraft, string>>;

/** Validace + tělo POST/PATCH /wot/milestones. Povinný je jen tank (smysluplný záznam), čísla celá v limitech. */
export function milestoneBody(
  d: MilestoneDraft,
  today: string,
): { ok: true; body: Record<string, unknown> } | { ok: false; errors: MilestoneErrors } {
  const errors: MilestoneErrors = {};
  const tank = d.tank.trim();
  if (!tank) errors.tank = "Vyplň tank.";
  else if (tank.length > 100) errors.tank = "Název tanku je moc dlouhý.";
  const body: Record<string, unknown> = {
    tank,
    map_name: d.map_name.trim() || null,
    played_on: d.played_on || null,
    mastery: d.mastery || null,
    notes: d.notes.trim() || null,
    favorite: d.favorite,
  };
  for (const f of Object.keys(MILESTONE_LIMITS) as NumberField[]) {
    const raw = d[f].trim().replace(/\s/g, "");
    if (!raw) {
      body[f] = null;
      continue;
    }
    const v = Number(raw);
    if (!Number.isInteger(v) || v < 0 || v > MILESTONE_LIMITS[f]) {
      errors[f] = `${NUMBER_LABELS[f]}: celé číslo 0–${MILESTONE_LIMITS[f].toLocaleString("cs-CZ")}.`;
    } else body[f] = v;
  }
  if (d.played_on && (!/^\d{4}-\d{2}-\d{2}$/.test(d.played_on) || d.played_on > today)) errors.played_on = "Datum nemůže být v budoucnu.";
  return Object.keys(errors).length ? { ok: false, errors } : { ok: true, body };
}

/** Statistiky karty v pevném pořadí; chybějící hodnoty se vynechají (nevymýšlí se nuly). */
export function milestoneStats(m: Pick<WotMilestone, NumberField>): { key: NumberField; label: string; value: number }[] {
  return (["damage", "assist", "kills", "base_xp"] as NumberField[])
    .filter((k) => typeof m[k] === "number")
    .map((k) => ({ key: k, label: NUMBER_LABELS[k], value: m[k] as number }));
}

/** Oblíbené (legendární) první, pak nejnovější bitva. */
export function sortMilestones(list: WotMilestone[]): WotMilestone[] {
  return [...list].sort((a, b) => {
    if (a.favorite !== b.favorite) return a.favorite ? -1 : 1;
    return (b.played_on ?? "").localeCompare(a.played_on ?? "") || b.id - a.id;
  });
}

// ---------- screenshoty ----------

export const SCREENSHOT_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const SCREENSHOT_MAX_MB = 10;

/** Kontrola před nahráním (server ověřuje znovu podle obsahu souboru). */
export function screenshotFileError(file: { name: string; type: string; size: number }): string | null {
  if (!(SCREENSHOT_TYPES as readonly string[]).includes(file.type)) return `${file.name}: jen PNG, JPEG nebo WebP.`;
  if (file.size > SCREENSHOT_MAX_MB * 1024 * 1024) return `${file.name}: větší než ${SCREENSHOT_MAX_MB} MB.`;
  if (file.size === 0) return `${file.name}: prázdný soubor.`;
  return null;
}

export function screenshotUploadPath(milestoneId: number, filename: string, caption?: string): string {
  const q = new URLSearchParams({ filename });
  if (caption && caption.trim()) q.set("caption", caption.trim());
  return `/wot/milestones/${milestoneId}/screenshots?${q.toString()}`;
}

/** Index v galerii po šipce (dokola). */
export function galleryStep(index: number, count: number, dir: 1 | -1): number {
  if (count <= 0) return 0;
  return (index + dir + count) % count;
}

