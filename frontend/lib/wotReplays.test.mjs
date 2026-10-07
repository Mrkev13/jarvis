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
