// Game Enrichment A: registr herních obrázků, normalizace názvů, manifest a záložní monogramy.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  assetAlt, assetKey, assetSrc, CHARACTERS, EMPTY_MANIFEST, GAME_IMAGE_SIZES, imageBox, monogram, normalizeGameName,
  parseManifest, RESOURCES, safeAssetFile, TANKS,
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

test("tank aliases resolve to one stable key", () => {
  const cases = {
    "tank/object_268_v4": ["Object 268 Version 4", "Obj. 268 V4", "object 268 v4", "Object 268/4"],
    "tank/progetto_65": ["Progetto M40 mod. 65", "Progetto 65"],
    "tank/wz_111_5a": ["WZ-111 model 5A", "WZ-111 5A", "wz111 5a"],
    "tank/st_ii": ["ST-II", "ST 2", "st-ii"],
    "tank/fv215b_183": ["FV215b (183)", "FV215b 183", "FV 183"],
    "tank/t57_heavy": ["T57 Heavy Tank", "T57 Heavy", "T57"],
    "tank/object_279e": ["Object 279 (e)", "Object 279e", "Obj. 279 (e)"],
    "tank/tvp_t_50_51": ["TVP T 50/51", "TVP 50/51"],
  };
  for (const [key, names] of Object.entries(cases)) for (const n of names) assert.equal(assetKey("tank", n), key, n);
  assert.equal(assetKey("tank", "IS-7"), null, "neznámý tank → bez obrázku");
  assert.equal(assetKey("tank", ""), null);
});

test("registry covers the real tank and character names (prompt + fixtures)", () => {
  const tanks = ["Type 5 Heavy", "Type 71", "Strv 103B", "ST-II", "Object 268 Version 4", "Progetto 65", "WZ-111 model 5A",
    "T57 Heavy", "Object 261", "FV215b 183", "Dravec", "Object 140", "Grille 15", "TVP T 50/51", "Vz. 55",
    ...fixture("wot-grinds").map((g) => g.tank)];
  for (const t of tanks) assert.ok(assetKey("tank", t), `tank ${t}`);
  const chars = ["Thor", "White Fox", "Green Goblin", "Venom", "Storm", "Black Bolt", "Mephisto", "Carnage", "Valkyrie",
    "Luna Snow", "Magneto", "Mysterio", "Namor", "Ghost Rider", "Sentry", "Drax", "Doctor Voodoo", "Cyclops", "Shuri",
    "Satana", "Ghost Panther", ...fixture("mff-characters").map((c) => c.name)];
  for (const c of chars) assert.ok(assetKey("character", c), `postava ${c}`);
  assert.equal(assetKey("character", "Dr. Voodoo"), "character/doctor_voodoo");
  for (const r of Object.keys(fixture("wot-resources"))) assert.ok(assetKey("resource", r), r);
});

test("stable, unique slugs (file names)", () => {
  for (const reg of [TANKS, CHARACTERS, RESOURCES]) {
    for (const slug of Object.keys(reg)) assert.match(slug, /^[a-z0-9_]+$/);
  }
  const allNames = Object.values(TANKS).flatMap((e) => [e.name, ...(e.aliases ?? [])]);
  const keys = new Map();
  for (const n of allNames) {
    const k = assetKey("tank", n);
    assert.ok(k);
    keys.set(n, k);
  }
  assert.equal(new Set(Object.values(TANKS).map((e) => assetKey("tank", e.name))).size, Object.keys(TANKS).length, "žádná kolize názvů");
});

test("manifest: only safe local files, missing → fallback", () => {
  const m = parseManifest({ version: 1, assets: {
    "tank/kranvagn": { file: "wot/tanks/kranvagn.png", source: "https://api.worldoftanks.eu/…", attribution: "© Wargaming.net" },
    "character/luna_snow": { file: "mff/characters/luna_snow.webp" },
    "tank/evil": { file: "../../etc/passwd" },
    "tank/remote": { file: "https://evil.example/x.png" },
    "tank/script": { file: "wot/tanks/x.html" },
    "bogus key": { file: "wot/tanks/a.png" },
  } });
  assert.deepEqual(Object.keys(m.assets), ["tank/kranvagn", "character/luna_snow"]);
  assert.equal(assetSrc(m, "tank", "Kranvagn"), "/game-assets/wot/tanks/kranvagn.png");
  assert.equal(assetSrc(m, "character", "luna snow"), "/game-assets/mff/characters/luna_snow.webp");
  assert.equal(assetSrc(m, "tank", "TVP T 50/51"), null, "známý tank bez souboru → záložní");
  assert.equal(assetSrc(m, "tank", "IS-7"), null);
  for (const bad of [null, 1, "x", { version: 2, assets: {} }, { version: 1 }, { version: 1, assets: null }]) {
    assert.deepEqual(parseManifest(bad), EMPTY_MANIFEST);
  }
  assert.equal(safeAssetFile("wot/tanks/a.svg"), "wot/tanks/a.svg");
  assert.equal(safeAssetFile("/wot/tanks/a.png"), null);
  assert.equal(safeAssetFile("wot/../a.png"), null);
});

test("fallback monograms, alt text and sizes", () => {
  assert.equal(monogram("tank", "Kranvagn"), "KR");
  assert.equal(monogram("tank", "Object 279 (e)"), "O2");
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
