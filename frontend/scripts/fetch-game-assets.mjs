#!/usr/bin/env node
// Game Enrichment A – stažení skutečných herních obrázků do lokální cache public/game-assets (gitignore).
//
//   WG_APPLICATION_ID=xxxx WG_REGION=eu node scripts/fetch-game-assets.mjs   # obnoví vše (tanky, měny, portréty)
//   … --force                                                             # znovu stáhnout i už uložené obrázky
//   node scripts/fetch-game-assets.mjs --manifest-only                      # jen přepsat manifest z existujících souborů
//
// Zdroje:
// - tanky: oficiální Wargaming Tankopedia API (encyclopedia/vehicles) – VŠECHNA vozidla, pole images.big_icon
//   (160×100 PNG; API ho vrací jako http:// → povýší se na https, jen oficiální hosty). Soubor wot/tanks/<tank_id>.png,
//   do manifestu jde název, short_name, národ a tier; aplikace k nim názvy grindů přiřadí sama (lib/gameAssets.ts
//   resolveTank). Nový tank v grindu = žádná úprava kódu, jen tenhle skript. Uložené obrázky se nestahují znovu.
// - ikony měn: oficiální styl portálu worldoftanks.eu, kde jsou ikony vložené jako SVG (data URI) – adresa stylu
//   se najde na stránce Tankopedie, záloha v game-assets.sources.json; SVG se ověří (isSafeSvg).
// - portréty MFF: explicitní https URL z oficiálních zdrojů v game-assets.sources.json (zatím prázdné).
// Nic se nestahuje za běhu aplikace; aplikace čte jen manifest a lokální soubory. application_id se nikam neukládá.
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { buildTankIndex, CHARACTERS, MANIFEST_VERSION, RESOURCES, TANKOPEDIA_HOSTS, tankopediaImageUrl } from "../lib/gameAssets.ts";
import { extractCssSvg, findPortalStylesheet, isOfficialUrl, isSafeSvg, PORTAL_HOSTS } from "../lib/gameAssetSources.ts";

const ROOT = fileURLToPath(new URL("../public/game-assets/", import.meta.url));
const SOURCES = JSON.parse(readFileSync(new URL("./game-assets.sources.json", import.meta.url), "utf8"));
const DIRS = { tank: "wot/tanks", resource: "wot/resources", character: "mff/characters" };
const REGISTRY = { resource: RESOURCES, character: CHARACTERS };
const EXT = { "image/png": "png", "image/webp": "webp", "image/jpeg": "jpg", "image/svg+xml": "svg" };
const MAX_BYTES = 600 * 1024;
const MAX_TEXT_BYTES = 5 * 1024 * 1024;
const CONCURRENCY = 6;
const manifestOnly = process.argv.includes("--manifest-only");
const force = process.argv.includes("--force");
const appId = process.env.WG_APPLICATION_ID || "";

const log = (...a) => console.log("[game-assets]", ...a);
for (const d of Object.values(DIRS)) mkdirSync(ROOT + d, { recursive: true });

/** Uloží soubor <slug>.<ext> a smaže starší varianty téhož slugu s jinou příponou (žádné dvojice v manifestu). */
function writeAsset(dir, slug, ext, buf) {
  for (const f of readdirSync(ROOT + dir)) if (f.startsWith(`${slug}.`) && f !== `${slug}.${ext}`) unlinkSync(`${ROOT}${dir}/${f}`);
  writeFileSync(`${ROOT}${dir}/${slug}.${ext}`, buf);
  return `${dir}/${slug}.${ext}`;
}

/** Stáhne obrázek: jen https, volitelně jen z povolených hostů (i po přesměrování), obrázkový MIME, limit velikosti. */
async function download(url, kind, slug, allowedHosts = null) {
  if (!/^https:\/\//.test(url)) throw new Error(`jen https URL: ${url}`);
  if (allowedHosts && !isOfficialUrl(url, allowedHosts)) throw new Error(`neoficiální host: ${new URL(url).hostname}`);
  const res = await fetch(url, { redirect: "follow" });
  if (allowedHosts && !isOfficialUrl(res.url, allowedHosts)) throw new Error("přesměrování mimo oficiální host");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const type = (res.headers.get("content-type") || "").split(";")[0].trim();
  const ext = EXT[type];
  if (!ext) throw new Error(`není obrázek (${type || "bez typu"})`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > MAX_BYTES) throw new Error(`moc velký (${Math.round(buf.length / 1024)} kB) – použij miniaturu`);
  return writeAsset(DIRS[kind], slug, ext, buf);
}

/** Text (HTML / CSS) z oficiálního hostu – stejná pravidla jako u obrázků. */
async function fetchText(url, hosts) {
  if (!isOfficialUrl(url, hosts)) throw new Error(`neoficiální zdroj: ${url}`);
  const res = await fetch(url, { redirect: "follow" });
  if (!isOfficialUrl(res.url, hosts)) throw new Error("přesměrování mimo oficiální host");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const text = await res.text();
  if (text.length > MAX_TEXT_BYTES) throw new Error("odpověď je moc velká");
  return text;
}

/** Spustí úlohy s omezeným souběhem (ohleduplně k CDN Wargamingu). */
async function pool(items, worker) {
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, items.length) }, async () => {
    while (next < items.length) await worker(items[next++]);
  }));
}

const sourceOf = {}; // klíč měny / postavy → { source, attribution }
const stats = { vehicles: 0, downloaded: 0, cached: 0, failed: [], pruned: 0, resources: [] };

/** Všechna vozidla z Tankopedie → soubory wot/tanks/<tank_id>.png + položky manifestu. null = přeskočeno. */
async function fetchTanks() {
  if (!appId) {
    log("WG_APPLICATION_ID není nastavené – tanky z Tankopedie přeskakuji (manifest převezme předchozí stav).");
    return null;
  }
  const region = process.env.WG_REGION || "eu";
  const host = region === "com" || region === "na" ? "api.worldoftanks.com" : region === "asia" ? "api.worldoftanks.asia" : "api.worldoftanks.eu";
  const vehicles = [];
  for (let page = 1; page < 30; page++) {
    const url = `https://${host}/wot/encyclopedia/vehicles/?application_id=${encodeURIComponent(appId)}&fields=tank_id,name,short_name,nation,tier,images&language=en&limit=100&page_no=${page}`;
    const body = await (await fetch(url)).json();
    if (body.status !== "ok") throw new Error(`Tankopedia: ${body.error?.message ?? "chyba"}`);
    vehicles.push(...Object.values(body.data || {}));
    if (page >= (body.meta?.page_total ?? 1)) break;
  }
  stats.vehicles = vehicles.length;
  log(`Tankopedia: ${vehicles.length} vozidel`);

  const existing = new Map(); // tank_id → soubor
  for (const f of readdirSync(ROOT + DIRS.tank)) {
    const m = /^(\d+)\.(png|webp|jpg)$/.exec(f);
    if (m) existing.set(m[1], `${DIRS.tank}/${f}`);
  }
  const tanks = {};
  await pool(vehicles, async (v) => {
    const id = String(v.tank_id);
    const url = tankopediaImageUrl(v.images?.big_icon);
    let path = existing.get(id);
    if (!url) {
      stats.failed.push(`${v.name}: bez oficiální ikony`);
    } else if (!path || force) {
      try {
        path = await download(url, "tank", id, TANKOPEDIA_HOSTS);
        stats.downloaded++;
      } catch (e) {
        stats.failed.push(`${v.name}: ${e.message}`);
      }
    } else {
      stats.cached++;
    }
    if (!path) return;
    tanks[id] = {
      name: v.name,
      short_name: v.short_name || v.name,
      nation: v.nation,
      tier: v.tier,
      path,
      ...(url ? { source: url } : {}),
      attribution: SOURCES.attribution?.wot,
    };
  });
  // vozidla, která z Tankopedie zmizela (nebo staré soubory podle slugů) → pryč z cache
  for (const f of readdirSync(ROOT + DIRS.tank)) {
    const id = /^(\d+)\./.exec(f)?.[1];
    if (!id || !tanks[id]) {
      unlinkSync(`${ROOT}${DIRS.tank}/${f}`);
      stats.pruned++;
    }
  }
  return tanks;
}

/** Ikony měn z oficiálního stylu portálu WoT (SVG vložené do CSS). */
async function fetchResourceIcons() {
  const cfg = SOURCES.resources || {};
  const candidates = [];
  try {
    const found = findPortalStylesheet(await fetchText(cfg.portal_page, PORTAL_HOSTS));
    if (found) candidates.push(found);
    else log("! portál: odkaz na styl nenalezen, zkouším uloženou adresu");
  } catch (e) {
    log(`! portál: ${e.message}, zkouším uloženou adresu`);
  }
  if (cfg.stylesheet && !candidates.includes(cfg.stylesheet)) candidates.push(cfg.stylesheet);
  let css = null;
  let cssUrl = null;
  for (const url of candidates) {
    try {
      css = await fetchText(url, PORTAL_HOSTS);
      cssUrl = url;
      break;
    } catch (e) {
      log(`! styl ${url}: ${e.message}`);
    }
  }
  if (!css) {
    log("! ikony měn: oficiální styl není dostupný – zůstávají uložené / záložní monogramy");
    return;
  }
  for (const [key, selector] of Object.entries(cfg.icons || {})) {
    if (!RESOURCES[key]) continue;
    const svg = extractCssSvg(css, selector);
    if (!svg) {
      log(`! ${RESOURCES[key].name}: ikona (${selector}) ve stylu není`);
      continue;
    }
    if (!isSafeSvg(svg)) {
      log(`! ${RESOURCES[key].name}: SVG neprošlo kontrolou bezpečnosti`);
      continue;
    }
    writeAsset(DIRS.resource, key, "svg", svg);
    sourceOf[`resource/${key}`] = { source: `${cssUrl} ${selector}`, attribution: SOURCES.attribution?.wot };
    stats.resources.push(RESOURCES[key].name);
  }
}

async function fetchListed(kind, list, attribution) {
  for (const [slug, url] of Object.entries(list || {})) {
    if (!url) continue;
    if (!REGISTRY[kind][slug]) {
      log(`! ${slug}: není v registru lib/gameAssets.ts`);
      continue;
    }
    try {
      await download(url, kind, slug);
      sourceOf[`${kind}/${slug}`] = { source: url, attribution };
      log(`✓ ${REGISTRY[kind][slug].name}`);
    } catch (e) {
      log(`! ${slug}: ${e.message}`);
    }
  }
}

function readPrevious() {
  try {
    const m = JSON.parse(readFileSync(ROOT + "manifest.json", "utf8"));
    return m.version === MANIFEST_VERSION ? m : {};
  } catch {
    return {};
  }
}

function writeManifest(tanks) {
  const previous = readPrevious();
  const assets = {};
  for (const kind of ["resource", "character"]) {
    const dir = DIRS[kind];
    for (const f of readdirSync(ROOT + dir)) {
      const m = /^([a-z0-9_]+)\.(png|webp|jpg|jpeg|svg)$/.exec(f);
      if (!m || !REGISTRY[kind][m[1]]) continue;
      const key = `${kind}/${m[1]}`;
      const meta = sourceOf[key] ?? previous.assets?.[key] ?? {};
      assets[key] = { file: `${dir}/${f}`, ...(meta.source ? { source: meta.source } : {}), ...(meta.attribution ? { attribution: meta.attribution } : {}) };
    }
  }
  // bez application_id (nebo jen --manifest-only) se převezmou předchozí tanky, jejichž soubory pořád existují
  const wotTanks = tanks ?? Object.fromEntries(Object.entries(previous.wot_tanks ?? {}).filter(([, t]) => t?.path && existsSync(ROOT + t.path)));
  const json = JSON.stringify({ version: MANIFEST_VERSION, generated_at: new Date().toISOString(), assets, wot_tanks: wotTanks });
  if (appId && json.includes(appId)) throw new Error("manifest by obsahoval application_id – nezapsáno");
  writeFileSync(ROOT + "manifest.json", json);
  const index = buildTankIndex(Object.entries(wotTanks).map(([id, t]) => ({ vehicle_id: id, ...t })));
  const ambiguous = [...index.byName, ...index.byShort].filter(([, ids]) => ids.length > 1).map(([k]) => k);
  log(`manifest: ${Object.keys(wotTanks).length} tanků, ${Object.keys(assets).length} dalších assetů, ${(json.length / 1024).toFixed(0)} kB`);
  if (ambiguous.length) log(`  nejednoznačné názvy (záložní monogram, dokud je nerozliší alias): ${[...new Set(ambiguous)].join(", ")}`);
}

function cacheSize() {
  let bytes = 0;
  let files = 0;
  for (const dir of Object.values(DIRS)) for (const f of readdirSync(ROOT + dir)) {
    bytes += statSync(`${ROOT}${dir}/${f}`).size;
    files++;
  }
  return { files, mb: (bytes / 1024 / 1024).toFixed(1) };
}

let tanks = null;
if (!manifestOnly) {
  tanks = await fetchTanks().catch((e) => {
    log(`! Tankopedia: ${e.message}`);
    return null;
  });
  await fetchResourceIcons();
  await fetchListed("character", SOURCES.characters, SOURCES.attribution?.mff);
}
writeManifest(tanks);
if (!manifestOnly) {
  const size = cacheSize();
  log(`souhrn: vozidel ${stats.vehicles}, staženo ${stats.downloaded}, z cache ${stats.cached}, odstraněno ${stats.pruned}, chyb ${stats.failed.length}; měny: ${stats.resources.join(", ") || "žádné"}; cache ${size.files} souborů / ${size.mb} MB`);
  for (const f of stats.failed) log(`  ! ${f}`);
}
