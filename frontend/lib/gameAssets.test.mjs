// Game Enrichment A: normalizace názvů, dynamické párování tanků s Tankopedií, manifest a záložní monogramy.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  assetAlt, assetKey, assetSrc, CHARACTERS, EMPTY_MANIFEST, GAME_IMAGE_SIZES, imageBox, monogram, normalizeGameName,
  parseManifest, resolveTank, RESOURCES, safeAssetFile, TANK_ALIASES, tankopediaImageUrl,
} from "./gameAssets.ts";

const fixture = (name) => JSON.parse(readFileSync(new URL(`../scripts/fixtures/${name}.json`, import.meta.url), "utf8"));

test("normalization: diacritics, punctuation, Obj./Dr., roman numerals, version", () => {
  assert.equal(normalizeGameName("  Obj. 268  Version 4 "), "object 268 v 4");
  assert.equal(normalizeGameName("Object 268 V4"), "object 268 v4");
  assert.equal(normalizeGameName("ST-II"), "st 2");
  assert.equal(normalizeGameName("Dr. Voodoo"), "doctor voodoo");
  assert.equal(normalizeGameName("Šťastný Tank"), "stastny tank");
  assert.equal(normalizeGameName(null), "");
});

const MANIFEST_FIXTURE = fixture("game-assets-manifest");
const manifest = parseManifest(MANIFEST_FIXTURE);
const tankId = (name) => resolveTank(manifest.tanks, name)?.vehicle_id ?? null;

test("dynamic Tankopedia resolution: the four real grinds, no registry", () => {
  // Vz. 55 #2929, Konštrukta T-34/100 #1649 (short T-34/100), Hirschkäfer #40977, CAV mod. 71 #6817 (short CAV 71)
  for (const [name, id] of [["VZ.55", "2929"], ["Vz.55", "2929"], ["Vz. 55", "2929"], ["T34/100", "1649"], ["Hirschkäfer", "40977"],
    ["Hirschkafer", "40977"], ["CAV 71", "6817"]]) assert.equal(tankId(name), id, name);
  assert.equal(assetSrc(manifest, "tank", "T34/100"), "/game-assets/wot/tanks/1649.png");
});

test("resolution tiers: exact name, short_name, separator-insensitive only when unique", () => {
  assert.equal(tankId("Konštrukta T-34/100"), "1649", "1) přesný název");
  assert.equal(tankId("CAV mod. 71"), "6817", "1) přesný název");
  assert.equal(tankId("Obj. 279 (e)"), "46849", "2) short_name");
  assert.equal(tankId("Object 279 (e)"), "46849", "2) short_name po normalizaci Obj. = Object");
  assert.equal(tankId("Obj. 268 V4"), "20225", "Version 4 = V4 normalizací");
  assert.equal(tankId("FV215b 183"), "9297", "2) short_name");
  // T-34 (SSSR, #1) a T34 (USA, #2849) se liší jen pomlčkou – nesmí se spojit
  assert.equal(tankId("T-34"), "1");
  assert.equal(tankId("T34"), "2849");
  // stejný název dvou vozidel → raději monogram než špatný tank
  assert.equal(tankId("IS-2"), null, "nejednoznačné → záložní");
});

test("aliases only for true naming differences, targets exist in Tankopedia", () => {
  for (const [alias, id] of [["268 V4", "20225"], ["279e", "46849"], ["FV 183", "9297"], ["TVP 50/51", "2417"], ["T57 Heavy Tank", "14881"]]) {
    assert.equal(tankId(alias), id, alias);
  }
  const names = new Set(Object.values(MANIFEST_FIXTURE.wot_tanks).map((t) => normalizeGameName(t.name)));
  for (const official of Object.values(TANK_ALIASES)) assert.ok(names.has(normalizeGameName(official)), `cíl aliasu ${official}`);
  assert.ok(Object.keys(TANK_ALIASES).length <= 8, "aliasy jen výjimečně");
});

test("future / non-registry tank resolves from the manifest without a code change", () => {
  assert.equal(tankId("Leopard 1"), "14609");
  // vozidlo, které přibude do Tankopedie později: stačí nový manifest ze skriptu
  const later = parseManifest({ ...MANIFEST_FIXTURE, wot_tanks: { ...MANIFEST_FIXTURE.wot_tanks,
    50593: { name: "Lion", short_name: "Lion", nation: "italy", tier: 8, path: "wot/tanks/50593.png" } } });
  assert.equal(resolveTank(later.tanks, "Lion")?.vehicle_id, "50593");
  assert.equal(assetSrc(later, "tank", "lion"), "/game-assets/wot/tanks/50593.png");
  assert.equal(tankId("Lion"), null, "bez nového manifestu ho aplikace nezná");
});

test("unknown tank → fallback", () => {
  for (const n of ["IS-7", "Neexistující tank", "", null, undefined, "T57"]) assert.equal(assetSrc(manifest, "tank", n), null, String(n));
});

test("characters and resources: Luna → Luna Snow, official currency icons", () => {
  assert.equal(assetKey("character", "Luna"), "character/luna_snow");
  assert.equal(assetKey("character", "Luna Snow"), "character/luna_snow");
  assert.equal(assetSrc(manifest, "character", "Luna"), "/game-assets/mff/characters/luna_snow.png");
  assert.equal(assetSrc(manifest, "character", "Thor"), null, "bez portrétu → monogram");
  assert.equal(assetKey("character", "Dr. Voodoo"), "character/doctor_voodoo");
  for (const c of fixture("mff-characters").map((x) => x.name)) assert.ok(assetKey("character", c), c);
  for (const r of Object.keys(fixture("wot-resources"))) {
    assert.ok(assetKey("resource", r), r);
    assert.equal(assetSrc(manifest, "resource", r), `/game-assets/wot/resources/${r}.svg`);
  }
  assert.deepEqual(Object.keys(RESOURCES), ["credits", "gold", "bonds", "free_xp"]);
  assert.ok(Object.keys(CHARACTERS).every((s) => /^[a-z0-9_]+$/.test(s)));
});

test("manifest: only safe local files, wrong version → empty", () => {
  const m = parseManifest({ version: 2, assets: {
    "character/luna_snow": { file: "mff/characters/luna_snow.webp" },
    "resource/evil": { file: "../../etc/passwd" },
    "resource/remote": { file: "https://evil.example/x.png" },
    "resource/script": { file: "wot/resources/x.html" },
    "tank/old_slug": { file: "wot/tanks/kranvagn.png" },
    "bogus key": { file: "wot/tanks/a.png" },
  }, wot_tanks: {
    2433: { name: "Kranvagn", short_name: "Kranvagn", path: "wot/tanks/2433.png", source: "https://api.worldoftanks.eu/static/x/2433.png" },
    1: { name: "Escape", path: "wot/tanks/../../x.png" },
    2: { name: "Elsewhere", path: "mff/characters/x.png" },
    3: { name: "Remote", path: "https://evil.example/x.png" },
    abc: { name: "Bad id", path: "wot/tanks/abc.png" },
    4: { path: "wot/tanks/4.png" },
    5: { name: "Plain http source", path: "wot/tanks/5.png", source: "http://evil.example/5.png" },
  } });
  assert.deepEqual(Object.keys(m.assets), ["character/luna_snow"]);
  assert.deepEqual([...m.tanks.entries.keys()].sort(), ["2433", "5"]);
  assert.equal(m.tanks.entries.get("5").source, undefined, "jen https zdroj se převezme");
  assert.equal(assetSrc(m, "tank", "Kranvagn"), "/game-assets/wot/tanks/2433.png");
  for (const bad of [null, 1, "x", { version: 1, assets: {} }, { version: 3 }, MANIFEST_FIXTURE.wot_tanks]) {
    assert.equal(parseManifest(bad), EMPTY_MANIFEST);
  }
  assert.equal(parseManifest({ version: 2 }).tanks.entries.size, 0);
  assert.equal(safeAssetFile("wot/tanks/a.svg"), "wot/tanks/a.svg");
  assert.equal(safeAssetFile("/wot/tanks/a.png"), null);
  assert.equal(safeAssetFile("wot/../a.png"), null);
});

test("fallback monograms, alt text and sizes", () => {
  assert.equal(monogram("tank", "Kranvagn"), "KR");
  assert.equal(monogram("tank", "Object 279 (e)"), "O279");
  assert.equal(monogram("tank", "Type 71"), "T71");
  assert.equal(monogram("tank", "Object 268 Version 4"), "O268");
  assert.equal(monogram("tank", "TVP T 50/51"), "TT");
  assert.equal(monogram("character", "Luna Snow"), "LS");
  assert.equal(monogram("character", "Thor"), "TH");
  assert.equal(monogram("resource", "free_xp"), "XP");
  assert.equal(monogram("resource", "credits"), "Cr");
  assert.equal(monogram("tank", ""), "?");
  assert.equal(assetAlt("tank", "Kranvagn"), "Tank Kranvagn");
  assert.equal(assetAlt("character", "Thor"), "Portrét: Thor");
  assert.equal(assetAlt("resource", "credits"), "", "ikona u popisku je dekorativní");
  assert.deepEqual(Object.values(GAME_IMAGE_SIZES), [24, 40, 56, 88]);
  assert.deepEqual(imageBox("tank", "sm"), { width: 64, height: 40 });
  assert.deepEqual(imageBox("character", "md"), { width: 56, height: 56 });
});

// Regrese: Tankopedia vrací images.big_icon jako http:// → skript (jen https) nestáhl ani jeden tank.
test("tankopedia image URL: http upgraded to https only on official Wargaming hosts", () => {
  const icon = "/static/2.77.0/wot/encyclopedia/vehicle/ussr-R169_ST_II.png";
  assert.equal(tankopediaImageUrl(`http://api.worldoftanks.eu${icon}`), `https://api.worldoftanks.eu${icon}`);
  assert.equal(tankopediaImageUrl(`https://api.worldoftanks.eu${icon}`), `https://api.worldoftanks.eu${icon}`);
  assert.equal(tankopediaImageUrl(`http://api.worldoftanks.com${icon}`), `https://api.worldoftanks.com${icon}`);
  assert.equal(tankopediaImageUrl(`http://api.worldoftanks.asia${icon}`), `https://api.worldoftanks.asia${icon}`);
  // cizí hosty se nepovyšují (skript je pak odmítne), podvržené domény taky ne
  assert.equal(tankopediaImageUrl("http://example.com/tank.png"), null);
  assert.equal(tankopediaImageUrl("http://api.worldoftanks.eu.evil.com/x.png"), null);
  assert.equal(tankopediaImageUrl("http://evilworldoftanks.eu/x.png"), null);
  assert.equal(tankopediaImageUrl("ftp://api.worldoftanks.eu/x.png"), null);
  assert.equal(tankopediaImageUrl(undefined), null);
  assert.equal(tankopediaImageUrl("nesmysl"), null);
});
