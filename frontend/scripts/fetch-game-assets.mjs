#!/usr/bin/env node
// Game Enrichment A – stažení skutečných herních obrázků do lokální cache public/game-assets (gitignore).
//
//   WG_APPLICATION_ID=xxxx WG_REGION=eu node scripts/fetch-game-assets.mjs   # tanky z Tankopedie + zdroje z JSON
//   node scripts/fetch-game-assets.mjs --manifest-only                      # jen přepsat manifest z existujících souborů
//
// Zdroje:
// - tanky: oficiální Wargaming Tankopedia API (encyclopedia/vehicles, pole images.big_icon 160×100 PNG z CDN
//   Wargamingu); application_id zdarma na https://developers.wargaming.net. Shoda podle registru v lib/gameAssets.ts
//   (oficiální název + aliasy, normalizace stejná jako v aplikaci). Ruční výjimky: tank_overrides v sources JSON.
// - ikony měn a portréty MFF: explicitní https URL z oficiálních zdrojů v scripts/game-assets.sources.json.
// - soubory, které do složek nakopíruješ ručně (<slug>.png|webp|jpg|svg), se do manifestu zapíšou taky.
// Nic se nestahuje z libovolných URL za běhu aplikace; aplikace čte jen manifest a lokální soubory.
import { mkdirSync, readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { assetKey, CHARACTERS, normalizeGameName, RESOURCES, TANKS } from "../lib/gameAssets.ts";

const ROOT = fileURLToPath(new URL("../public/game-assets/", import.meta.url));
const SOURCES = JSON.parse(readFileSync(new URL("./game-assets.sources.json", import.meta.url), "utf8"));
const DIRS = { tank: "wot/tanks", resource: "wot/resources", character: "mff/characters" };
const REGISTRY = { tank: TANKS, resource: RESOURCES, character: CHARACTERS };
const EXT = { "image/png": "png", "image/webp": "webp", "image/jpeg": "jpg", "image/svg+xml": "svg" };
const MAX_BYTES = 600 * 1024;
const manifestOnly = process.argv.includes("--manifest-only");

const log = (...a) => console.log("[game-assets]", ...a);
for (const d of Object.values(DIRS)) mkdirSync(ROOT + d, { recursive: true });

async function download(url, kind, slug) {
  if (!/^https:\/\//.test(url)) throw new Error(`jen https URL: ${url}`);
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const type = (res.headers.get("content-type") || "").split(";")[0].trim();
  const ext = EXT[type];
  if (!ext) throw new Error(`není obrázek (${type || "bez typu"})`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > MAX_BYTES) throw new Error(`moc velký (${Math.round(buf.length / 1024)} kB) – použij miniaturu`);
  const file = `${DIRS[kind]}/${slug}.${ext}`;
  writeFileSync(ROOT + file, buf);
  return file;
}

const sourceOf = {}; // klíč → { source, attribution }

async function fetchTanks() {
  const appId = process.env.WG_APPLICATION_ID;
  if (!appId) {
    log("WG_APPLICATION_ID není nastavené – tanky z Tankopedie přeskakuji.");
    return;
  }
  const region = process.env.WG_REGION || "eu";
  const host = region === "com" || region === "na" ? "api.worldoftanks.com" : region === "asia" ? "api.worldoftanks.asia" : "api.worldoftanks.eu";
  const vehicles = [];
  for (let page = 1; page < 20; page++) {
    const url = `https://${host}/wot/encyclopedia/vehicles/?application_id=${encodeURIComponent(appId)}&fields=name,short_name,images&language=en&limit=100&page_no=${page}`;
    const body = await (await fetch(url)).json();
    if (body.status !== "ok") throw new Error(`Tankopedia: ${body.error?.message ?? "chyba"}`);
    vehicles.push(...Object.values(body.data || {}));
    if (page >= (body.meta?.page_total ?? 1)) break;
  }
  log(`Tankopedia: ${vehicles.length} vozidel`);
  const byName = new Map();
  for (const v of vehicles) {
    for (const n of [v.name, v.short_name]) {
      const key = assetKey("tank", n);
      if (key && !byName.has(key)) byName.set(key, v);
    }
  }
  for (const slug of Object.keys(TANKS)) {
    const key = `tank/${slug}`;
    const override = SOURCES.tank_overrides?.[slug];
    const url = override || byName.get(key)?.images?.big_icon;
    if (!url) {
      log(`! ${TANKS[slug].name}: v Tankopedii nenalezen (zkus alias v lib/gameAssets.ts nebo tank_overrides)`);
      continue;
    }
    try {
      await download(url, "tank", slug);
      sourceOf[key] = { source: url, attribution: SOURCES.attribution?.wot };
      log(`✓ ${TANKS[slug].name}`);
    } catch (e) {
      log(`! ${TANKS[slug].name}: ${e.message}`);
    }
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

function writeManifest() {
  const previous = existsSync(ROOT + "manifest.json") ? JSON.parse(readFileSync(ROOT + "manifest.json", "utf8")) : { assets: {} };
  const assets = {};
  for (const [kind, dir] of Object.entries(DIRS)) {
    for (const f of readdirSync(ROOT + dir)) {
      const m = /^([a-z0-9_]+)\.(png|webp|jpg|jpeg|svg)$/.exec(f);
      if (!m || !REGISTRY[kind][m[1]]) continue;
      const key = `${kind}/${m[1]}`;
      const meta = sourceOf[key] ?? previous.assets?.[key] ?? {};
      assets[key] = { file: `${dir}/${f}`, ...(meta.source ? { source: meta.source } : {}), ...(meta.attribution ? { attribution: meta.attribution } : {}) };
    }
  }
  writeFileSync(ROOT + "manifest.json", JSON.stringify({ version: 1, generated_at: new Date().toISOString(), assets }, null, 1));
  log(`manifest: ${Object.keys(assets).length} assetů → public/game-assets/manifest.json`);
}

if (!manifestOnly) {
  await fetchTanks().catch((e) => log(`! Tankopedia: ${e.message}`));
  await fetchListed("resource", SOURCES.resources, SOURCES.attribution?.wot);
  await fetchListed("character", SOURCES.characters, SOURCES.attribution?.mff);
}
writeManifest();
// Kontrola registru: normalizované názvy musí být unikátní (jinak by se obrázek přiřadil špatnému tanku).
const seen = new Map();
for (const [slug, e] of Object.entries(TANKS)) {
  const n = normalizeGameName(e.name);
  if (seen.has(n)) log(`! kolize názvů: ${slug} × ${seen.get(n)}`);
  seen.set(n, slug);
}
