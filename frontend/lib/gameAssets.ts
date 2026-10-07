/**
 * Herní obrázky (Game Enrichment A) – normalizace názvů, rozlišení tanků podle Tankopedie a cesty k lokálním
 * assetům. Čistá logika bez Reactu (testy: gameAssets.test.mjs), sdílená se skriptem scripts/fetch-game-assets.mjs.
 *
 * Assety NEJSOU v repozitáři (autorská práva Wargaming / Netmarble / Marvel): skript je stáhne z oficiálních
 * zdrojů do public/game-assets/ (gitignore) a zapíše manifest.json. Aplikace manifest načte za běhu; co
 * v něm není (nebo se nenačte), ukáže čitelný záložní monogram. Žádné generované „podobné" obrázky.
 *
 * Tanky nemají ruční registr: manifest obsahuje všechna vozidla z Tankopedie (název, short_name, soubor) a název
 * grindu se k nim přiřadí za běhu (`resolveTank`). Nový tank = jen znovu spustit skript, žádná úprava kódu.
 */

export type GameAssetKind = "tank" | "character" | "resource";
export type GameImageSize = "xs" | "sm" | "md" | "lg";

/** Výška obrázku v px (tank má šířku 1,6× – poměr ikon z Tankopedie 160 × 100). */
export const GAME_IMAGE_SIZES: Record<GameImageSize, number> = { xs: 24, sm: 40, md: 56, lg: 88 };
export const TANK_ASPECT = 1.6;

export function imageBox(kind: GameAssetKind, size: GameImageSize): { width: number; height: number } {
  const h = GAME_IMAGE_SIZES[size];
  return { width: kind === "tank" ? Math.round(h * TANK_ASPECT) : h, height: h };
}

interface RegistryEntry {
  /** Oficiální název (zobrazuje se v dokumentaci, podle něj se páruje). */
  name: string;
  /** Další zápisy, které uživatel používá („Dr. Voodoo", „Luna"…). */
  aliases?: string[];
}

/** MFF postavy (sledované v aplikaci + fixtures). Portréty nemají veřejné API → pevný seznam se slugy. */
export const CHARACTERS: Record<string, RegistryEntry> = {
  thor: { name: "Thor" },
  white_fox: { name: "White Fox" },
  green_goblin: { name: "Green Goblin" },
  venom: { name: "Venom" },
  storm: { name: "Storm" },
  black_bolt: { name: "Black Bolt" },
  mephisto: { name: "Mephisto" },
  carnage: { name: "Carnage" },
  valkyrie: { name: "Valkyrie" },
  luna_snow: { name: "Luna Snow", aliases: ["Luna"] },
  magneto: { name: "Magneto" },
  mysterio: { name: "Mysterio" },
  namor: { name: "Namor" },
  ghost_rider: { name: "Ghost Rider" },
  sentry: { name: "Sentry", aliases: ["The Sentry"] },
  drax: { name: "Drax", aliases: ["Drax the Destroyer"] },
  doctor_voodoo: { name: "Doctor Voodoo", aliases: ["Dr. Voodoo", "Brother Voodoo"] },
  cyclops: { name: "Cyclops" },
  shuri: { name: "Shuri" },
  satana: { name: "Satana" },
  ghost_panther: { name: "Ghost Panther" },
  captain_marvel: { name: "Captain Marvel" },
  black_widow: { name: "Black Widow" },
};

/** Měny WoT – klíče shodné s backendem (WotResource.resource). */
export const RESOURCES: Record<string, RegistryEntry> = {
  credits: { name: "Credits" },
  gold: { name: "Gold" },
  bonds: { name: "Bonds" },
  free_xp: { name: "Free XP" },
};

/** Monogram záložní ikony měny (neutrální text, ne napodobenina herní grafiky). */
export const RESOURCE_MONOGRAMS: Record<string, string> = { credits: "Cr", gold: "G", bonds: "B", free_xp: "XP" };

/**
 * Ruční aliasy tanků – JEN skutečné rozdíly v pojmenování, které normalizace ani short_name z Tankopedie nepokryjí
 * (zápis uživatele → oficiální název v Tankopedii). Běžné varianty („VZ.55", „T34/100", „Obj. 268 V4",
 * „Hirschkafer") se párují samy.
 */
export const TANK_ALIASES: Record<string, string> = {
  "268 V4": "Object 268 Version 4",
  "279e": "Object 279 early", // short_name „Obj. 279 (e)" pokryje „Object 279 (e)", ale ne holé „279e"
  "FV 183": "FV215b (183)",
  "TVP 50/51": "TVP T 50/51",
  "T57 Heavy Tank": "T57 Heavy", // starší oficiální název
};

const ROMAN: Record<string, string> = { i: "1", ii: "2", iii: "3", iv: "4", v: "5", vi: "6", vii: "7", viii: "8", ix: "9", x: "10" };

/**
 * Název → porovnávací tvar: bez diakritiky a interpunkce, malá písmena, „Obj." = „Object", „Dr." = „Doctor",
 * samostatné římské číslice jako arabské („ST-II" = „ST 2"), „Version"/„Ver." = „V".
 */
export function normalizeGameName(raw: string | null | undefined): string {
  const s = String(raw ?? "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/\bobj\b\.?/g, "object ")
    .replace(/\bdr\b\.?/g, "doctor ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
  return s
    .split(/\s+/)
    .map((w) => (w === "version" || w === "ver" ? "v" : ROMAN[w] ?? w))
    .join(" ");
}

/** Bez mezer – „WZ-111 5A" = „WZ111 5A", „T34/100" = „T-34/100". Jen jako poslední, jednoznačný stupeň. */
function compact(s: string): string {
  return normalizeGameName(s).replace(/\s+/g, "");
}

function buildRegistryIndex(registry: Record<string, RegistryEntry>): Map<string, string> {
  const index = new Map<string, string>();
  for (const [slug, entry] of Object.entries(registry)) {
    for (const n of [entry.name, ...(entry.aliases ?? []), slug.replace(/_/g, " ")]) {
      const key = compact(n);
      if (key && !index.has(key)) index.set(key, slug);
    }
  }
  return index;
}

const REGISTRY_INDEX: Record<"character" | "resource", Map<string, string>> = {
  character: buildRegistryIndex(CHARACTERS),
  resource: buildRegistryIndex(RESOURCES),
};

/** Klíč assetu postavy / měny („character/luna_snow"), nebo null. Tanky se řeší přes manifest (`resolveTank`). */
export function assetKey(kind: "character" | "resource", name: string | null | undefined): string | null {
  const slug = REGISTRY_INDEX[kind].get(compact(name ?? ""));
  return slug ? `${kind}/${slug}` : null;
}

/** Vozidlo z Tankopedie v manifestu (skript ho zapíše, aplikace ho jen čte). */
export interface TankEntry {
  vehicle_id: string;
  name: string;
  short_name: string;
  nation?: string;
  tier?: number;
  /** Relativní cesta uvnitř /game-assets („wot/tanks/7169.png"). */
  path: string;
  source?: string;
  attribution?: string;
}

/** Vyhledávací index tanků: normalizovaný název / short_name / tvar bez mezer → id vozidel. */
export interface TankIndex {
  entries: Map<string, TankEntry>;
  byName: Map<string, string[]>;
  byShort: Map<string, string[]>;
  byCompact: Map<string, string[]>;
  /** Game Enrichment C: technický název vozidla z replaye („sweden:S16_Kranvagn") → id; z názvu souboru Tankopedie. */
  byTag: Map<string, string[]>;
}

function addTo(map: Map<string, string[]>, key: string, id: string) {
  if (!key) return;
  const list = map.get(key);
  if (!list) map.set(key, [id]);
  else if (!list.includes(id)) list.push(id);
}

export function buildTankIndex(tanks: TankEntry[]): TankIndex {
  const index: TankIndex = { entries: new Map(), byName: new Map(), byShort: new Map(), byCompact: new Map(), byTag: new Map() };
  for (const t of tanks) {
    index.entries.set(t.vehicle_id, t);
    addTo(index.byName, normalizeGameName(t.name), t.vehicle_id);
    addTo(index.byShort, normalizeGameName(t.short_name), t.vehicle_id);
    addTo(index.byCompact, compact(t.name), t.vehicle_id);
    addTo(index.byCompact, compact(t.short_name), t.vehicle_id);
    const tag = tankTagFromSource(t.source);
    if (tag) addTo(index.byTag, tag, t.vehicle_id);
  }
  return index;
}

/**
 * Obrázky Tankopedie se jmenují `<národ>-<tag>.png` („…/vehicle/sweden-S16_Kranvagn.png") – stejný tag, jaký
 * nese replay (`playerVehicle`). Z URL v manifestu tak jde tag spárovat s názvem vozidla bez dalšího registru.
 */
export function tankTagFromSource(source: string | null | undefined): string | null {
  const m = /\/([a-z]+)-([A-Za-z0-9_-]{1,80})\.png$/.exec(source ?? "");
  return m ? `${m[1]}:${m[2]}` : null;
}

/** Tag vozidla z replaye („sweden:S16_Kranvagn") → vozidlo z manifestu; neznámý / nejednoznačný → null. */
export function resolveTankTag(index: TankIndex, tag: string | null | undefined): TankEntry | null {
  const ids = index.byTag.get(String(tag ?? "").trim());
  return ids?.length === 1 ? index.entries.get(ids[0]) ?? null : null;
}

/** Výsledek stupně: jednoznačné vozidlo, nejednoznačné (stop – raději monogram než špatný tank), nebo nic. */
function pick(index: TankIndex, ids: string[] | undefined): TankEntry | "ambiguous" | null {
  if (!ids?.length) return null;
  return ids.length === 1 ? index.entries.get(ids[0]) ?? null : "ambiguous";
}

const ALIAS_INDEX = new Map(Object.entries(TANK_ALIASES).map(([alias, official]) => [normalizeGameName(alias), normalizeGameName(official)]));

/**
 * Název grindu → vozidlo z Tankopedie. Pořadí: 1) přesný normalizovaný název, 2) short_name, 3) ruční alias,
 * 4) tvar bez mezer/pomlček – jen když určí jediné vozidlo („T34/100" = „T-34/100"; „T34" ≠ „T-34", ty se
 * rozliší už v 1.). Nejednoznačný stupeň končí monogramem, nikdy se nehádá.
 */
export function resolveTank(index: TankIndex, name: string | null | undefined): TankEntry | null {
  const key = normalizeGameName(name);
  if (!key) return null;
  const aliased = ALIAS_INDEX.get(key);
  const tiers = [index.byName.get(key), index.byShort.get(key), aliased ? index.byName.get(aliased) : undefined, index.byCompact.get(compact(key))];
  for (const ids of tiers) {
    const hit = pick(index, ids);
    if (hit === "ambiguous") return null;
    if (hit) return hit;
  }
  return null;
}

export interface ManifestEntry {
  file: string;
  source?: string;
  attribution?: string;
}
export interface GameAssetManifest {
  version: number;
  /** Měny a postavy („resource/credits", „character/luna_snow"). */
  assets: Record<string, ManifestEntry>;
  tanks: TankIndex;
}
export const MANIFEST_VERSION = 2;
export const EMPTY_MANIFEST: GameAssetManifest = { version: MANIFEST_VERSION, assets: {}, tanks: buildTankIndex([]) };
export const MANIFEST_URL = "/game-assets/manifest.json";

/** Jen bezpečná relativní cesta k obrázku uvnitř /game-assets (žádné URL, žádné „..", jen obrázkové přípony). */
export function safeAssetFile(file: unknown): string | null {
  if (typeof file !== "string") return null;
  if (!/^[a-z0-9_]+(\/[a-z0-9_]+)*\/[a-z0-9_.-]+\.(png|webp|jpg|jpeg|svg)$/.test(file) || file.includes("..")) return null;
  return file;
}

const str = (v: unknown, max: number): string | null => (typeof v === "string" && v.length > 0 && v.length <= max ? v : null);

function parseTank(id: string, value: unknown): TankEntry | null {
  if (!/^\d{1,10}$/.test(id) || typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  const name = str(v.name, 120);
  const path = safeAssetFile(v.path);
  if (!name || !path || !path.startsWith("wot/tanks/")) return null;
  return {
    vehicle_id: id,
    name,
    short_name: str(v.short_name, 120) ?? name,
    ...(typeof v.nation === "string" ? { nation: v.nation } : {}),
    ...(typeof v.tier === "number" ? { tier: v.tier } : {}),
    path,
    ...(typeof v.source === "string" && v.source.startsWith("https://") ? { source: v.source } : {}),
    ...(typeof v.attribution === "string" ? { attribution: v.attribution } : {}),
  };
}

/** Manifest ze serveru → ověřený tvar; nesmysl / jiná verze → prázdný (všude záložní monogram). */
export function parseManifest(raw: unknown): GameAssetManifest {
  if (typeof raw !== "object" || raw === null || (raw as { version?: unknown }).version !== MANIFEST_VERSION) return EMPTY_MANIFEST;
  const { assets, wot_tanks: wotTanks } = raw as { assets?: unknown; wot_tanks?: unknown };
  const out: Record<string, ManifestEntry> = {};
  if (typeof assets === "object" && assets !== null) {
    for (const [key, value] of Object.entries(assets as Record<string, unknown>)) {
      if (!/^(character|resource)\/[a-z0-9_]+$/.test(key) || typeof value !== "object" || value === null) continue;
      const file = safeAssetFile((value as { file?: unknown }).file);
      if (!file) continue;
      const v = value as { source?: unknown; attribution?: unknown };
      out[key] = {
        file,
        ...(typeof v.source === "string" ? { source: v.source } : {}),
        ...(typeof v.attribution === "string" ? { attribution: v.attribution } : {}),
      };
    }
  }
  const tanks: TankEntry[] = [];
  if (typeof wotTanks === "object" && wotTanks !== null) {
    for (const [id, value] of Object.entries(wotTanks as Record<string, unknown>)) {
      const t = parseTank(id, value);
      if (t) tanks.push(t);
    }
  }
  return { version: MANIFEST_VERSION, assets: out, tanks: buildTankIndex(tanks) };
}

/** URL obrázku (lokální, same-origin) nebo null → záložní monogram. */
export function assetSrc(manifest: GameAssetManifest, kind: GameAssetKind, name: string | null | undefined): string | null {
  if (kind === "tank") {
    const tank = resolveTank(manifest.tanks, name);
    return tank ? `/game-assets/${tank.path}` : null;
  }
  const key = assetKey(kind, name);
  const entry = key ? manifest.assets[key] : undefined;
  return entry ? `/game-assets/${entry.file}` : null;
}

/** Hosty oficiálního Tankopedia API (stejné, na které se skript ptá). */
export const TANKOPEDIA_HOSTS = ["api.worldoftanks.eu", "api.worldoftanks.com", "api.worldoftanks.asia"];

/**
 * Tankopedia vrací `images.big_icon` jako http:// – tentýž soubor je na stejném hostu i přes https. Povýší
 * jen oficiální hosty; cokoli jiného → null (skript stahuje výhradně https).
 */
export function tankopediaImageUrl(raw: string | null | undefined): string | null {
  let url: URL;
  try {
    url = new URL(String(raw ?? ""));
  } catch {
    return null;
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || !TANKOPEDIA_HOSTS.includes(url.hostname)) return null;
  url.protocol = "https:";
  return url.toString();
}

/** Čitelný monogram pro záložní obrázek: „Kranvagn" → „KR", „Object 279 (e)" → „O279", „Luna Snow" → „LS". */
export function monogram(kind: GameAssetKind, name: string | null | undefined): string {
  if (kind === "resource") {
    const key = assetKey("resource", name)?.split("/")[1];
    return (key && RESOURCE_MONOGRAMS[key]) || String(name ?? "?").slice(0, 2);
  }
  const words = String(name ?? "")
    .replace(/[()]/g, " ")
    .split(/[\s/]+/)
    .map((w) => w.replace(/[^\p{L}\p{N}]/gu, ""))
    .filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  // „Object 279 (e)" → „O279", „Type 71" → „T71" (ne „O2", které se plete s „02")
  if (kind === "tank" && /^\d+$/.test(words[1])) return (words[0][0] + words[1]).slice(0, 4).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Alt text: obrázek nese identitu tanku / postavy; ikona měny je u textového popisku dekorativní (alt=""). */
export function assetAlt(kind: GameAssetKind, name: string): string {
  if (kind === "tank") return `Tank ${name}`;
  if (kind === "character") return `Portrét: ${name}`;
  return "";
}
