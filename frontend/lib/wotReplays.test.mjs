// Game Enrichment C: knihovna replayů – popisky, upload, štítky, filtry, ruční metadata (fixtures ze skutečného backendu).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  activeFilterCount, DEFAULT_FILTERS, duplicateReplayId, formatFileSize, normalizeTag, parserStatusMeta, PRESET_TAGS, replayDraftFrom,
  replayFileError, replayPatch, replayQuery, replayStats, replayTitle, replayUploadPath, resultMeta, tagLabel, tankTagShort, toggleTag,
} from "./wotReplays.ts";

const list = JSON.parse(readFileSync(new URL("../scripts/fixtures/wot-replays.json", import.meta.url), "utf8"));
const byId = (id) => list.items.find((r) => r.id === id);
const TODAY = "2026-10-07";

test("fixture: parsed / partial / unsupported from the real service", () => {
  assert.deepEqual(list.items.map((r) => r.parser_status).sort(), ["parsed", "parsed", "parsed", "partial", "unsupported"]);
  assert.deepEqual(list.preset_tags, [...PRESET_TAGS], "backend and frontend share the preset tags");
});

test("labels: tags, results, parser statuses", () => {
  assert.equal(tagLabel("close-game"), "Těsná bitva");
  assert.equal(tagLabel("mko"), "Mko");
  assert.equal(tagLabel("vlastní štítek"), "vlastní štítek");
  assert.equal(resultMeta("win").label, "Výhra");
  assert.equal(resultMeta(null), null);
  assert.equal(parserStatusMeta("parsed").tone, "success");
  assert.equal(parserStatusMeta("partial").label, "Načteno částečně");
  assert.equal(parserStatusMeta("unsupported").label, "Metadata nenačtena");
});

test("title: manual name → manifest name from tag → tag → filename → id", () => {
  assert.equal(replayTitle(byId(1)), "Progetto 65");
  assert.equal(replayTitle(byId(3), "Leopard 1"), "Leopard 1");
  assert.equal(replayTitle(byId(3)), "G89_Leopard1", "bez manifestu technický název, nic se nehádá");
  assert.equal(replayTitle(byId(5)), "20260930_novy_format.wotreplay");
  assert.equal(replayTitle({ id: 9, tank_name: null, tank_tag: null, original_filename: null }), "Replay #9");
  assert.equal(tankTagShort("italy:It13_Progetto_M35_mod_46"), "It13_Progetto_M35_mod_46");
  assert.equal(tankTagShort(null), null);
});

test("file size, stats without invented zeros", () => {
  assert.equal(formatFileSize(512), "512 B");
  assert.equal(formatFileSize(2048), "2 kB");
  assert.equal(formatFileSize(3.4 * 1024 * 1024), "3,4 MB");
  assert.deepEqual(replayStats(byId(1)).map((s) => [s.key, s.value]), [["damage", 5205], ["assist", 1754], ["kills", 5], ["base_xp", 1208]]);
  assert.deepEqual(replayStats(byId(4)), [], "partial = no stats");
});

test("upload validation, path and duplicate response", () => {
  assert.equal(replayFileError({ name: "bitva.wotreplay", size: 1000 }), null);
  assert.equal(replayFileError({ name: "BITVA.WOTREPLAY", size: 1000 }), null);
  assert.match(replayFileError({ name: "bitva.zip", size: 1000 }), /jen soubor \.wotreplay/);
  assert.match(replayFileError({ name: "bitva.wotreplay.exe", size: 1000 }), /jen soubor/);
  assert.match(replayFileError({ name: "x.wotreplay", size: 0 }), /prázdný/);
  assert.match(replayFileError({ name: "x.wotreplay", size: 51 * 1024 * 1024 }), /50 MB/);
  assert.equal(replayUploadPath("a b&c.wotreplay"), "/wot/replays?filename=a+b%26c.wotreplay");
  assert.equal(duplicateReplayId({ detail: { error: "duplicate", replay_id: 3 } }), 3);
  assert.equal(duplicateReplayId({ detail: { error: "invalid_file" } }), null);
  assert.equal(duplicateReplayId(null), null);
});

test("tags: same normalization as the backend", () => {
  assert.equal(normalizeTag("  Těsná   VÝHRA "), "těsná výhra");
  assert.equal(normalizeTag("close-game"), "close-game");
  assert.equal(normalizeTag("<script>"), null);
  assert.equal(normalizeTag("x".repeat(25)), null);
  assert.equal(normalizeTag(""), null);
  assert.deepEqual(toggleTag(["mko"], "carry"), ["mko", "carry"]);
  assert.deepEqual(toggleTag(["mko", "carry"], "mko"), ["carry"]);
});

test("filters → query string and active count", () => {
  assert.equal(replayQuery(DEFAULT_FILTERS), "");
  assert.equal(activeFilterCount(DEFAULT_FILTERS), 0);
  const f = { ...DEFAULT_FILTERS, q: " útesy ", tag: "mko", favorite: true, mastery: "none", sort: "played_asc" };
  assert.equal(replayQuery(f), "q=%C3%BAtesy&tag=mko&mastery=none&favorite=true&sort=played_asc");
  assert.equal(activeFilterCount(f), 4, "řazení není filtr");
});

test("manual edit: only changed fields, untouched date keeps the exact battle time", () => {
  const r = byId(1);
  const d = replayDraftFrom(r);
  assert.equal(d.played_on, "2026-09-14", "pražský den");
  assert.deepEqual(replayPatch(d, r, TODAY), { ok: true, body: {} });
  const res = replayPatch({ ...d, damage: "5 300", notes: " Upraveno ", tags: [...d.tags, "record"], linked_milestone_id: "", favorite: false }, r, TODAY);
  assert.deepEqual(res, { ok: true, body: { notes: "Upraveno", damage: 5300, favorite: false, tags: ["mko", "carry", "close-game", "record"], linked_milestone_id: null } });
  assert.deepEqual(replayPatch({ ...d, played_on: "2026-09-13" }, r, TODAY).body, { played_at: "2026-09-13" });
});

test("manual edit: partial replay gets manifest name, validation errors", () => {
  const r = byId(4);
  const d = replayDraftFrom(r, "Kranvagn");
  assert.equal(d.tank_name, "Kranvagn");
  assert.deepEqual(replayPatch({ ...d, kills: "3", mastery: "ace", battle_result: "win", linked_milestone_id: "4" }, r, TODAY).body,
    { tank_name: "Kranvagn", kills: 3, mastery: "ace", battle_result: "win", linked_milestone_id: 4 });
  const bad = replayPatch({ ...d, kills: "16", damage: "-1", played_on: "2027-01-01", tags: PRESET_TAGS.concat(["a", "b"]) }, r, TODAY);
  assert.equal(bad.ok, false);
  assert.deepEqual(Object.keys(bad.errors).sort(), ["damage", "kills", "played_on", "tags"]);
  assert.equal(replayPatch({ ...d, tank_name: "x".repeat(101) }, r, TODAY).errors.tank_name, "Tank: nejvýš 100 znaků.");
});

// Regrese z lokálního ověření: replay znal jen technický tag → frontend pošle lidský název z manifestu.
import { REPLAY_HEADER_PEEK_BYTES, replayUploadPath as uploadPath, replayVehicleTag } from "./wotReplays.ts";

function replayHead(header, { magic = [0x12, 0x32, 0x34, 0x11], blocks = 2, tail = 64 } = {}) {
  const json = new TextEncoder().encode(JSON.stringify(header));
  const out = new Uint8Array(12 + json.length + tail);
  out.set(magic, 0);
  const view = new DataView(out.buffer);
  view.setUint32(4, blocks, true);
  view.setUint32(8, json.length, true);
  out.set(json, 12);
  return out;
}

test("tag vozidla z hlavičky replaye (tvar klienta 2.x)", () => {
  const head = replayHead({ playerVehicle: "usa-A67_T57_58", mapDisplayName: "Overlord", clientVersionFromExe: "2.2.1.0" });
  assert.equal(replayVehicleTag(head), "usa:A67_T57_58");
  assert.equal(replayVehicleTag(replayHead({ playerVehicle: "italy-It08_Progetto_M40_mod_65" })), "italy:It08_Progetto_M40_mod_65");
});

test("nečitelná hlavička → bez názvu, nic se nehádá", () => {
  assert.equal(replayVehicleTag(replayHead({ playerVehicle: "usa-A67_T57_58" }, { magic: [0, 0, 0, 0] })), null, "jiná signatura");
  assert.equal(replayVehicleTag(new Uint8Array(0)), null);
  const full = replayHead({ playerVehicle: "usa-A67_T57_58" });
  assert.equal(replayVehicleTag(full.subarray(0, 20)), null, "useknutý blok");
  const broken = replayHead({ playerVehicle: "x" });
  broken[12] = 0x7b; broken[13] = 0x7b; // neplatný JSON
  assert.equal(replayVehicleTag(broken), null);
  assert.equal(replayVehicleTag(replayHead({ playerVehicle: "../../etc-passwd" })), null);
  assert.equal(replayVehicleTag(replayHead({ mapDisplayName: "Karélie" })), null, "bez vozidla");
  assert.ok(REPLAY_HEADER_PEEK_BYTES >= 64 * 1024);
});

test("upload posílá lidský název jen když je", () => {
  assert.equal(uploadPath("t57.wotreplay", "T57 Heavy"), "/wot/replays?filename=t57.wotreplay&tank_name=T57+Heavy");
  assert.equal(uploadPath("t57.wotreplay", null), "/wot/replays?filename=t57.wotreplay");
  assert.equal(uploadPath("t57.wotreplay"), "/wot/replays?filename=t57.wotreplay");
});
