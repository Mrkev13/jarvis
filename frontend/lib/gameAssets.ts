/**
 * Herní obrázky (Game Enrichment A) – registr, normalizace názvů a cesty k lokálním assetům. Čistá logika
 * bez Reactu (testy: gameAssets.test.mjs), sdílená se skriptem scripts/fetch-game-assets.mjs.
 *
 * Assety NEJSOU v repozitáři (autorská práva Wargaming / Netmarble / Marvel): skript je stáhne z oficiálních
 * zdrojů do public/game-assets/ (gitignore) a zapíše manifest.json. Aplikace manifest načte za běhu; co
 * v něm není (nebo se nenačte), ukáže čitelný záložní monogram. Žádné generované „podobné" obrázky.
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
  /** Oficiální název (podle něj skript hledá v Tankopedii / zobrazuje se v dokumentaci). */
  name: string;
  /** Další zápisy, které uživatel používá („Obj. 268 V4", „Progetto 65"…). */
  aliases?: string[];
}

/**
 * Tanky – stabilní slug = název souboru. Pokrývá tanky z reálných dat (zadání 4G) i z fixtures.
 * Nový tank: přidat sem → spustit skript (stáhne ikonu z Tankopedie) → hotovo.
 */
export const TANKS: Record<string, RegistryEntry> = {
  type_5_heavy: { name: "Type 5 Heavy" },
  type_71: { name: "Type 71" },
  strv_103b: { name: "Strv 103B", aliases: ["Strv 103 B"] },
  st_ii: { name: "ST-II", aliases: ["ST 2"] },
  object_268_v4: { name: "Object 268 Version 4", aliases: ["Object 268 V4", "Obj. 268 V4", "Object 268/4", "268 V4"] },
  progetto_65: { name: "Progetto M40 mod. 65", aliases: ["Progetto 65", "Progetto M40 65"] },
  wz_111_5a: { name: "WZ-111 model 5A", aliases: ["WZ-111 5A", "WZ 111 5A"] },
  t57_heavy: { name: "T57 Heavy Tank", aliases: ["T57 Heavy", "T57"] },
  object_261: { name: "Object 261", aliases: ["Obj. 261"] },
  fv215b_183: { name: "FV215b (183)", aliases: ["FV215b 183", "FV 183", "FV215B183"] },
  dravec: { name: "Dravec" },
  object_140: { name: "Object 140", aliases: ["Obj. 140"] },
  grille_15: { name: "Grille 15" },
  tvp_t_50_51: { name: "TVP T 50/51", aliases: ["TVP 50/51", "TVP T50/51"] },
  vz_55: { name: "Vz. 55", aliases: ["VZ 55", "Vz55"] },
  object_279e: { name: "Object 279 (e)", aliases: ["Object 279e", "Obj. 279 (e)", "279e"] },
  kranvagn: { name: "Kranvagn" },
  t_100_lt: { name: "T-100 LT", aliases: ["T100 LT"] },
};

/** MFF postavy (sledované v aplikaci + fixtures). */
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
  luna_snow: { name: "Luna Snow" },
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

/** Bez mezer – „WZ-111 5A" = „WZ111 5A", „FV215b 183" = „FV215B183". */
function compact(s: string): string {
  return normalizeGameName(s).replace(/\s+/g, "");
}

function buildIndex(registry: Record<string, RegistryEntry>): Map<string, string> {
  const index = new Map<string, string>();
  for (const [slug, entry] of Object.entries(registry)) {
    for (const n of [entry.name, ...(entry.aliases ?? []), slug.replace(/_/g, " ")]) {
      const key = compact(n);
      if (key && !index.has(key)) index.set(key, slug);
    }
  }
  return index;
}

const INDEX: Record<GameAssetKind, Map<string, string>> = {
  tank: buildIndex(TANKS),
  character: buildIndex(CHARACTERS),
  resource: buildIndex(RESOURCES),
};

/** Stabilní klíč assetu („tank/kranvagn") pro název z aplikace, nebo null (neznámý → záložní monogram). */
export function assetKey(kind: GameAssetKind, name: string | null | undefined): string | null {
  const slug = INDEX[kind].get(compact(name ?? ""));
  return slug ? `${kind}/${slug}` : null;
}

export interface ManifestEntry {
  file: string;
  source?: string;
  attribution?: string;
}
export interface GameAssetManifest {
  version: number;
  assets: Record<string, ManifestEntry>;
}
export const EMPTY_MANIFEST: GameAssetManifest = { version: 1, assets: {} };
export const MANIFEST_URL = "/game-assets/manifest.json";

/** Jen bezpečná relativní cesta k obrázku uvnitř /game-assets (žádné URL, žádné „..", jen obrázkové přípony). */
export function safeAssetFile(file: unknown): string | null {
  if (typeof file !== "string") return null;
  if (!/^[a-z0-9_]+(\/[a-z0-9_]+)*\/[a-z0-9_.-]+\.(png|webp|jpg|jpeg|svg)$/.test(file) || file.includes("..")) return null;
  return file;
}

/** Manifest ze serveru → ověřený tvar; nesmysl / jiná verze → prázdný (všude záložní monogram). */
export function parseManifest(raw: unknown): GameAssetManifest {
  if (typeof raw !== "object" || raw === null || (raw as { version?: unknown }).version !== 1) return EMPTY_MANIFEST;
  const assets = (raw as { assets?: unknown }).assets;
  if (typeof assets !== "object" || assets === null) return EMPTY_MANIFEST;
  const out: Record<string, ManifestEntry> = {};
  for (const [key, value] of Object.entries(assets as Record<string, unknown>)) {
    if (!/^(tank|character|resource)\/[a-z0-9_]+$/.test(key) || typeof value !== "object" || value === null) continue;
    const file = safeAssetFile((value as { file?: unknown }).file);
    if (!file) continue;
    const v = value as { source?: unknown; attribution?: unknown };
    out[key] = {
      file,
      ...(typeof v.source === "string" ? { source: v.source } : {}),
      ...(typeof v.attribution === "string" ? { attribution: v.attribution } : {}),
    };
  }
  return { version: 1, assets: out };
}

/** URL obrázku (lokální, same-origin) nebo null → záložní monogram. */
export function assetSrc(manifest: GameAssetManifest, kind: GameAssetKind, name: string | null | undefined): string | null {
  const key = assetKey(kind, name);
  const entry = key ? manifest.assets[key] : undefined;
  return entry ? `/game-assets/${entry.file}` : null;
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
