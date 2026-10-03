/**
 * Marvel Future Fight – čisté pomocné funkce stránky /mff (Roadmap 4B): popisky, výpočet buildu,
 * filtry/řazení, validace a tělo POST /mff/character. Bez Reactu (testy: mff.test.mjs).
 */
import type { Tone } from "./ui.ts";

export const ROLE_OPTIONS = ["ABX", "ABL", "GBR", "World Boss", "PvP", "Dispatch", "Other"] as const;
export type RoleOption = (typeof ROLE_OPTIONS)[number];

export const TIER_OPTIONS = ["T1", "T2", "T2.5", "T3", "T4", "Transcendent"];
export const PRIORITY_OPTIONS = ["high", "medium", "low"];
export const STATUS_OPTIONS = ["built", "building", "planned", "inactive"];

export const BUILD_BUCKET_OPTIONS = ["all", "100", "80-99", "50-79", "under-50"] as const;
export type BuildBucket = (typeof BUILD_BUCKET_OPTIONS)[number];
export const BUILD_BUCKET_LABELS: Record<BuildBucket, string> = {
  all: "Vše",
  "100": "100 %",
  "80-99": "80–99 %",
  "50-79": "50–79 %",
  "under-50": "< 50 %",
};

export const SORT_OPTIONS = [
  { id: "default", label: "Výchozí (priorita, nejnižší build, jméno)" },
  { id: "priority", label: "Priorita" },
  { id: "build_asc", label: "Build od nejnižšího" },
  { id: "build_desc", label: "Build od nejvyššího" },
  { id: "tier", label: "Tier" },
  { id: "name", label: "Jméno (A–Z)" },
] as const;
export type SortId = (typeof SORT_OPTIONS)[number]["id"];

export type MffSummary = {
  tracked_characters: number;
  t4_count: number;
  t3_count: number;
  priority_count: number;
  built_count: number;
  fully_built_t4_count: number;
  average_build_completeness: number;
};

export type MffCharacterItem = {
  id: number;
  name: string;
  tier: string;
  level: number;
  uniform: string;
  ctp: string;
  artifact: string;
  priority: string;
  status: string;
  notes: string;
  role: string;
  team: string;
  uru_state: string;
  iso8_set: string;
  build_completeness: number;
  updated_at?: string | null;
  roles: string[];
  team_supports: string;
  uru_slots_total: number;
  uru_slots_filled: number;
  odin_blessings_count: number;
};

/** Stav buildu → český popisek + tón. Neznámé hodnoty zůstanou čitelné (bez podtržítek). */
export function statusMeta(status: string | null | undefined): { tone: Tone; label: string } {
  const s = String(status || "").trim().toLowerCase();
  if (s === "built") return { tone: "success", label: "Postaveno" };
  if (s === "building" || s === "in_progress") return { tone: "info", label: "Rozpracováno" };
  if (s === "planned") return { tone: "neutral", label: "Plánováno" };
  if (s === "inactive") return { tone: "neutral", label: "Neaktivní" };
  return { tone: "neutral", label: s ? s.replace(/_/g, " ") : "Bez stavu" };
}

export function isTierT4(tier: string | undefined | null): boolean {
  const t = (tier || "").trim().toLowerCase().replace(/\s+/g, "");
  return t === "t4" || t === "transcendent" || t === "tier4";
}

/** 8 sledovaných komponent: T4, Level 80, Uniform, CTP, Artifact, plné Uru, ISO-8 set, Team supports. */
export function computeBuildCompleteness(input: {
  tier: string;
  level: number;
  uniform: string;
  ctp: string;
  artifact: string;
  uru_slots_total: number;
  uru_slots_filled: number;
  iso8_set: string;
  team_supports: string;
}): number {
  let completed = 0;
  if (isTierT4(input.tier)) completed++;
  if ((input.level || 0) >= 80) completed++;
  if ((input.uniform || "").trim()) completed++;
  if ((input.ctp || "").trim()) completed++;
  if ((input.artifact || "").trim()) completed++;
  const ut = Number(input.uru_slots_total) || 0;
  const uf = Number(input.uru_slots_filled) || 0;
  if (ut > 0 && uf >= ut) completed++;
  if ((input.iso8_set || "").trim()) completed++;
  if ((input.team_supports || "").trim()) completed++;
  return Math.round((completed / 8) * 100);
}

export function buildBucketMatches(bc: number, bucket: BuildBucket): boolean {
  switch (bucket) {
    case "all":
      return true;
    case "100":
      return bc >= 100;
    case "80-99":
      return bc >= 80 && bc < 100;
    case "50-79":
      return bc >= 50 && bc < 80;
    case "under-50":
      return bc < 50;
  }
}

/** Doplní chybějící pole odpovědi /mff/characters (stejně jako dřív při načtení). */
export function normalizeCharacters(raw: MffCharacterItem[]): MffCharacterItem[] {
  return raw.map((c) => ({
    ...c,
    roles: Array.isArray(c.roles) ? c.roles : [],
    team_supports: c.team_supports || c.team || "",
    uru_slots_total: Number(c.uru_slots_total) || 20,
    uru_slots_filled: Number(c.uru_slots_filled) || 0,
    odin_blessings_count: Number(c.odin_blessings_count) || 0,
    build_completeness: Math.max(0, Math.min(100, Number(c.build_completeness) || 0)),
  }));
}

export type CharacterFilters = {
  tier: string;
  priority: string;
  status: string;
  roles: string[];
  build: BuildBucket;
  sort: SortId;
};

const PRIO_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
const TIER_ORDER: Record<string, number> = { transcendent: 6, t4: 5, t3: 4, "t2.5": 3, t25: 3, t2: 2, t1: 1 };

export function filterAndSortCharacters(characters: MffCharacterItem[], f: CharacterFilters): MffCharacterItem[] {
  let list = [...characters];
  if (f.tier !== "all") list = list.filter((c) => c.tier === f.tier);
  if (f.priority !== "all") list = list.filter((c) => (c.priority || "").toLowerCase() === f.priority);
  if (f.status !== "all") list = list.filter((c) => (c.status || "").toLowerCase() === f.status);
  if (f.roles.length > 0) {
    list = list.filter((c) => {
      const charRoles = Array.isArray(c.roles) ? c.roles.map((r) => String(r)) : [];
      return f.roles.every((r) => charRoles.includes(r));
    });
  }
  if (f.build !== "all") list = list.filter((c) => buildBucketMatches(c.build_completeness, f.build));
  const prio = (c: MffCharacterItem) => PRIO_ORDER[(c.priority || "").toLowerCase()] ?? 9;
  const tierRank = (c: MffCharacterItem) => TIER_ORDER[(c.tier || "").toLowerCase().replace(/\s+/g, "")] ?? 0;
  list.sort((a, b) => {
    switch (f.sort) {
      case "priority":
        return prio(a) - prio(b) || a.name.localeCompare(b.name);
      case "build_asc":
        return a.build_completeness - b.build_completeness || a.name.localeCompare(b.name);
      case "build_desc":
        return b.build_completeness - a.build_completeness || a.name.localeCompare(b.name);
      case "tier":
        return tierRank(b) - tierRank(a) || a.name.localeCompare(b.name);
      case "name":
        return a.name.localeCompare(b.name);
      case "default":
      default:
        return prio(a) - prio(b) || a.build_completeness - b.build_completeness || a.name.localeCompare(b.name);
    }
  });
  return list;
}

/** Hodnoty formuláře nové postavy (vše jako text z inputů). */
export type CharacterForm = {
  name: string;
  tier: string;
  level: string;
  uniform: string;
  ctp: string;
  artifact: string;
  teamSupports: string;
  roles: RoleOption[];
  uruSlotsFilled: string;
  uruSlotsTotal: string;
  odinBlessings: string;
  iso8Set: string;
  priority: string;
  status: string;
  notes: string;
};

export function emptyCharacterForm(): CharacterForm {
  return {
    name: "",
    tier: "T3",
    level: "80",
    uniform: "",
    ctp: "",
    artifact: "",
    teamSupports: "",
    roles: [],
    uruSlotsFilled: "0",
    uruSlotsTotal: "20",
    odinBlessings: "0",
    iso8Set: "",
    priority: "medium",
    status: "planned",
    notes: "",
  };
}

/** Živý odhad buildu z formuláře (stejné zaokrouhlení jako dřív). */
export function formBuildCompleteness(f: CharacterForm): number {
  return computeBuildCompleteness({
    tier: f.tier,
    level: Math.max(1, parseInt(f.level || "0", 10) || 0),
    uniform: f.uniform,
    ctp: f.ctp,
    artifact: f.artifact,
    uru_slots_total: Math.max(0, parseInt(f.uruSlotsTotal || "0", 10) || 0),
    uru_slots_filled: Math.max(0, parseInt(f.uruSlotsFilled || "0", 10) || 0),
    iso8_set: f.iso8Set,
    team_supports: f.teamSupports,
  });
}

export type CharacterFormErrors = Partial<Record<"name" | "level" | "uruSlotsTotal" | "uruSlotsFilled" | "odinBlessings", string>>;

export function validateCharacterForm(f: CharacterForm): CharacterFormErrors {
  const errs: CharacterFormErrors = {};
  if (!f.name.trim()) errs.name = "Zadej jméno postavy.";
  const lv = parseInt(f.level || "0", 10);
  if (!isFinite(lv) || lv < 1) errs.level = "Level musí být alespoň 1.";
  const ut = parseInt(f.uruSlotsTotal || "0", 10);
  const uf = parseInt(f.uruSlotsFilled || "0", 10);
  if (!isFinite(ut) || ut < 0) errs.uruSlotsTotal = "Počet Uru slotů nesmí být záporný.";
  if (!isFinite(uf) || uf < 0) errs.uruSlotsFilled = "Počet zaplněných Uru slotů nesmí být záporný.";
  if (isFinite(ut) && isFinite(uf) && uf > ut) errs.uruSlotsFilled = "Zaplněných slotů nesmí být víc než celkem.";
  const ob = parseInt(f.odinBlessings || "0", 10);
  if (!isFinite(ob) || ob < 0) errs.odinBlessings = "Počet Odin's Blessings nesmí být záporný.";
  return errs;
}

/** Tělo POST /mff/character – názvy polí a odvozené hodnoty beze změny. */
export function characterPayload(f: CharacterForm) {
  const levelNum = parseInt(f.level, 10);
  const ut = parseInt(f.uruSlotsTotal || "20", 10) || 0;
  const uf = parseInt(f.uruSlotsFilled || "0", 10) || 0;
  const ob = parseInt(f.odinBlessings || "0", 10) || 0;
  return {
    name: f.name.trim(),
    tier: f.tier,
    level: isFinite(levelNum) ? Math.max(1, levelNum) : 80,
    uniform: f.uniform.trim(),
    ctp: f.ctp.trim(),
    artifact: f.artifact.trim(),
    priority: f.priority,
    status: f.status,
    notes: f.notes.trim(),
    role: f.roles.join(" · "),
    team: f.teamSupports.trim(),
    uru_state: ut > 0 ? `${uf}/${ut}` : "",
    iso8_set: f.iso8Set.trim(),
    build_completeness: formBuildCompleteness(f),
    roles: f.roles,
    team_supports: f.teamSupports.trim(),
    uru_slots_total: ut,
    uru_slots_filled: uf,
    odin_blessings_count: ob,
  };
}

export type CharacterPayload = ReturnType<typeof characterPayload>;
