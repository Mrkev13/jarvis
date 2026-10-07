/**
 * Knihovna replayů WoT (Game Enrichment C) – typy, popisky, validace a tělo PATCH. Čistá logika bez Reactu
 * (testy: wotReplays.test.mjs). Backend: wot_replay_service.py (stejné limity, štítky a normalizace).
 */
import { filterQuery } from "./filters.ts";
import { pragueDayKey } from "./format.ts";
import { MILESTONE_LIMITS, NUMBER_LABELS, type MilestoneScreenshot, type NumberField } from "./wot.ts";

export type ParserStatus = "parsed" | "partial" | "unsupported";
export type BattleResult = "win" | "loss" | "draw";

export type ReplayMilestone = {
  id: number;
  tank: string;
  mastery: string | null;
  map_name: string | null;
  played_on: string | null;
  screenshots: MilestoneScreenshot[];
};

export type WotReplay = {
  id: number;
  original_filename: string | null;
  file_size: number;
  sha256: string;
  uploaded_at: string | null;
  played_at: string | null;
  tank_name: string | null;
  tank_tag: string | null;
  map_name: string | null;
  damage: number | null;
  assist: number | null;
  kills: number | null;
  base_xp: number | null;
  mastery: string | null;
  battle_result: BattleResult | null;
  game_version: string | null;
  notes: string | null;
  tags: string[];
  favorite: boolean;
  parser_status: ParserStatus;
  parser_version: string | null;
  parser_warnings: string[];
  linked_milestone_id: number | null;
  milestone: ReplayMilestone | null;
  download_url: string;
  created_at: string | null;
  updated_at: string | null;
};

export type ReplayList = {
  items: WotReplay[];
  total: number;
  facets: { tanks: string[]; maps: string[]; tags: string[] };
  preset_tags: string[];
};

// ---------- popisky ----------

export const PRESET_TAGS = ["mko", "carry", "spotting", "record", "mistake", "fun", "close-game"] as const;
const TAG_LABELS: Record<string, string> = {
  mko: "Mko",
  carry: "Carry",
  spotting: "Spotování",
  record: "Rekord",
  mistake: "Chyba",
  fun: "Zábava",
  "close-game": "Těsná bitva",
};
export function tagLabel(tag: string): string {
  return TAG_LABELS[tag] ?? tag;
}

export const RESULT_OPTIONS = [
  { value: "win", label: "Výhra", tone: "success" },
  { value: "loss", label: "Prohra", tone: "danger" },
  { value: "draw", label: "Remíza", tone: "neutral" },
] as const;
export function resultMeta(r: string | null | undefined) {
  return RESULT_OPTIONS.find((o) => o.value === r) ?? null;
}

/** Stav parseru → štítek. „parsed" se v seznamu neukazuje (běžný stav), jen v detailu. */
export function parserStatusMeta(s: string | null | undefined): { label: string; tone: "success" | "warning" | "neutral"; hint: string } {
  if (s === "parsed") return { label: "Načteno z replaye", tone: "success", hint: "Údaje se načetly z hlavičky replaye – můžeš je opravit." };
  if (s === "partial") return { label: "Načteno částečně", tone: "warning", hint: "Část údajů se z replaye načíst nepodařila – doplň je ručně." };
  return { label: "Metadata nenačtena", tone: "neutral", hint: "Replay je uložený, ale údaje z něj načíst nejdou – vyplň je ručně." };
}

/** „italy:It13_Progetto_M35_mod_46" → „It13_Progetto_M35_mod_46" (čitelnější záloha bez názvu). */
export function tankTagShort(tag: string | null | undefined): string | null {
  if (!tag) return null;
  return tag.split(":").slice(1).join(":") || tag;
}

/** Název k zobrazení: ruční název → název z manifestu (podle tagu) → tag → soubor. */
export function replayTitle(r: Pick<WotReplay, "id" | "tank_name" | "tank_tag" | "original_filename">, resolvedName?: string | null): string {
  return r.tank_name || resolvedName || tankTagShort(r.tank_tag) || r.original_filename || `Replay #${r.id}`;
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "–";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${(bytes / (1024 * 1024)).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} MB`;
}

export function replayStats(r: Pick<WotReplay, NumberField>) {
  return (["damage", "assist", "kills", "base_xp"] as NumberField[])
    .filter((k) => typeof r[k] === "number")
    .map((k) => ({ key: k, label: NUMBER_LABELS[k], value: r[k] as number }));
}

// ---------- upload ----------

export const REPLAY_EXT = ".wotreplay";
export const REPLAY_MAX_MB = 50;

/** Kontrola před nahráním (server ověřuje znovu – příponu, velikost i strukturu souboru). */
export function replayFileError(file: { name: string; size: number }): string | null {
  if (!file.name.toLowerCase().endsWith(REPLAY_EXT)) return `${file.name}: nahrát jde jen soubor .wotreplay.`;
  if (file.size === 0) return `${file.name}: prázdný soubor.`;
  if (file.size > REPLAY_MAX_MB * 1024 * 1024) return `${file.name}: větší než ${REPLAY_MAX_MB} MB.`;
  return null;
}

/** `tankName` = lidský název z manifestu Tankopedie; server ho uloží vedle technického tagu z hlavičky. */
export function replayUploadPath(filename: string, tankName?: string | null): string {
  const params = new URLSearchParams({ filename });
  if (tankName) params.set("tank_name", tankName);
  return `/wot/replays?${params.toString()}`;
}

const REPLAY_MAGIC = [0x12, 0x32, 0x34, 0x11];
/** Kolik bajtů souboru stačí na první blok hlavičky (skutečné hlavičky mají desítky kB). */
export const REPLAY_HEADER_PEEK_BYTES = 1024 * 1024;

/**
 * Technický tag vozidla z první hlavičky replaye („usa:A67_T57_58"), jen pro dohledání lidského názvu v manifestu
 * před uploadem. Stejná struktura a meze jako serverový parser; cokoli jiného → null (název se prostě nepošle).
 */
export function replayVehicleTag(head: Uint8Array): string | null {
  if (head.length < 12 || REPLAY_MAGIC.some((b, i) => head[i] !== b)) return null;
  const view = new DataView(head.buffer, head.byteOffset, head.byteLength);
  const blocks = view.getUint32(4, true);
  const size = view.getUint32(8, true);
  if (blocks < 1 || blocks > 16 || size === 0 || 12 + size > head.length) return null;
  try {
    const header = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(head.subarray(12, 12 + size))) as { playerVehicle?: unknown };
    const m = typeof header.playerVehicle === "string" ? /^([a-z]+)-([A-Za-z0-9_-]{1,80})$/.exec(header.playerVehicle) : null;
    return m ? `${m[1]}:${m[2]}` : null;
  } catch {
    return null;
  }
}

/** 409 z uploadu: `{detail: {error: "duplicate", replay_id}}` → id existujícího replaye. */
export function duplicateReplayId(body: unknown): number | null {
  const d = (body as { detail?: { error?: unknown; replay_id?: unknown } } | null)?.detail;
  return d && d.error === "duplicate" && typeof d.replay_id === "number" ? d.replay_id : null;
}

// ---------- štítky ----------

export const MAX_TAGS = 8;
/** Stejná normalizace jako backend: malá písmena, sloučené mezery, 1–24 znaků (písmena, číslice, mezera, pomlčka). */
export function normalizeTag(raw: string): string | null {
  const tag = raw.trim().toLowerCase().split(/\s+/).join(" ");
  return /^[\p{L}\p{N}_][\p{L}\p{N}_\- ]{0,23}$/u.test(tag) ? tag : null;
}

export function toggleTag(tags: ReadonlyArray<string>, tag: string): string[] {
  return tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag];
}

// ---------- filtry ----------

export type ReplayFilters = {
  q: string;
  tank: string;
  map: string;
  tag: string;
  mastery: string;
  result: string;
  favorite: boolean;
  sort: string;
};
export const DEFAULT_FILTERS: ReplayFilters = { q: "", tank: "", map: "", tag: "", mastery: "", result: "", favorite: false, sort: "played_desc" };
export const SORT_OPTIONS = [
  { value: "played_desc", label: "Nejnovější bitva" },
  { value: "played_asc", label: "Nejstarší bitva" },
  { value: "uploaded_desc", label: "Naposledy nahrané" },
] as const;

export function replayQuery(f: ReplayFilters): string {
  return filterQuery({
    q: f.q, tank: f.tank, map: f.map, tag: f.tag, mastery: f.mastery, result: f.result,
    favorite: f.favorite ? "true" : "", sort: f.sort === DEFAULT_FILTERS.sort ? "" : f.sort,
  });
}

export function activeFilterCount(f: ReplayFilters): number {
  return (["q", "tank", "map", "tag", "mastery", "result"] as const).filter((k) => f[k].trim() !== "").length + (f.favorite ? 1 : 0);
}

// ---------- ruční metadata ----------

export type ReplayDraft = {
  tank_name: string;
  map_name: string;
  played_on: string;
  damage: string;
  assist: string;
  kills: string;
  base_xp: string;
  mastery: string;
  battle_result: string;
  notes: string;
  tags: string[];
  favorite: boolean;
  linked_milestone_id: string;
};
export type ReplayErrors = Partial<Record<keyof ReplayDraft, string>>;

/** Koncept formuláře z replaye; prázdný název tanku předvyplní název z manifestu (podle tagu z replaye). */
export function replayDraftFrom(r: WotReplay, suggestedTank?: string | null): ReplayDraft {
  const n = (v: number | null) => (v === null || v === undefined ? "" : String(v));
  return {
    tank_name: r.tank_name ?? suggestedTank ?? "",
    map_name: r.map_name ?? "",
    played_on: r.played_at ? pragueDayKey(r.played_at) : "",
    damage: n(r.damage),
    assist: n(r.assist),
    kills: n(r.kills),
    base_xp: n(r.base_xp),
    mastery: r.mastery ?? "",
    battle_result: r.battle_result ?? "",
    notes: r.notes ?? "",
    tags: [...r.tags],
    favorite: r.favorite,
    linked_milestone_id: r.linked_milestone_id ? String(r.linked_milestone_id) : "",
  };
}

/**
 * Validace + tělo PATCH jen se změněnými poli (nic není povinné – replay je platný i bez metadat). Datum se pošle,
 * jen když se změnil den (jinak by se ztratil přesný čas bitvy z replaye).
 */
export function replayPatch(
  d: ReplayDraft,
  original: WotReplay,
  today: string,
): { ok: true; body: Record<string, unknown> } | { ok: false; errors: ReplayErrors } {
  const errors: ReplayErrors = {};
  const before = replayDraftFrom(original);
  const body: Record<string, unknown> = {};
  const text = (k: "tank_name" | "map_name" | "notes", max: number, label: string) => {
    const v = d[k].trim();
    if (v.length > max) errors[k] = `${label}: nejvýš ${max} znaků.`;
    else if (v !== (original[k] ?? "")) body[k] = v || null;
  };
  text("tank_name", 100, "Tank");
  text("map_name", 100, "Mapa");
  text("notes", 2000, "Poznámka");
  for (const f of Object.keys(MILESTONE_LIMITS) as NumberField[]) {
    const raw = d[f].trim().replace(/\s/g, "");
    if (raw === before[f]) continue;
    if (!raw) {
      body[f] = null;
      continue;
    }
    const v = Number(raw);
    if (!Number.isInteger(v) || v < 0 || v > MILESTONE_LIMITS[f]) errors[f] = `${NUMBER_LABELS[f]}: celé číslo 0–${MILESTONE_LIMITS[f].toLocaleString("cs-CZ")}.`;
    else body[f] = v;
  }
  if (d.played_on !== before.played_on) {
    if (d.played_on && (!/^\d{4}-\d{2}-\d{2}$/.test(d.played_on) || d.played_on > today || d.played_on < "2010-01-01")) {
      errors.played_on = "Datum nemůže být v budoucnu.";
    } else body.played_at = d.played_on || null;
  }
  if (d.mastery !== before.mastery) body.mastery = d.mastery || null;
  if (d.battle_result !== before.battle_result) body.battle_result = d.battle_result || null;
  if (d.favorite !== original.favorite) body.favorite = d.favorite;
  if (d.tags.length > MAX_TAGS) errors.tags = `Nejvýš ${MAX_TAGS} štítků.`;
  else if (d.tags.join("\n") !== original.tags.join("\n")) body.tags = d.tags;
  if (d.linked_milestone_id !== before.linked_milestone_id) body.linked_milestone_id = d.linked_milestone_id ? Number(d.linked_milestone_id) : null;
  return Object.keys(errors).length ? { ok: false, errors } : { ok: true, body };
}
