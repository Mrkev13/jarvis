// MRK-127: WoW – postup k cíli, popisky a kontrola formuláře.
import assert from "node:assert/strict";
import { test } from "node:test";

import { levelLabel, professionLabel, syncedAgo, syncTone, targetProgress, validateCharacterForm } from "./lib.ts";

test("progress to the target level", () => {
  assert.equal(targetProgress({ level: 30, target_level: 60 }), 50);
  assert.equal(targetProgress({ level: 70, target_level: 60 }), 100);
  assert.equal(targetProgress({ level: null, target_level: 60 }), null);
  assert.equal(targetProgress({ level: 30, target_level: null }), null);
});

test("level label", () => {
  assert.equal(levelLabel({ level: 42, target_level: 60, levels_to_go: 18, at_target: false }), "Level 42 / 60 · zbývá 18");
  assert.equal(levelLabel({ level: 60, target_level: 60, levels_to_go: 0, at_target: true }), "Level 60 / 60 · cíl splněn");
  assert.equal(levelLabel({ level: 12, target_level: null, levels_to_go: null, at_target: false }), "Level 12");
  assert.equal(levelLabel({ level: null, target_level: 60, levels_to_go: null, at_target: false }), "Level zatím neznámý");
});

test("sync tone and profession label", () => {
  assert.equal(syncTone("ok"), "success");
  assert.equal(syncTone("not_found"), "danger");
  assert.equal(syncTone("error"), "warning");
  assert.equal(professionLabel({ name: "Mining", skill: 150, max: 300 }), "Mining 150/300");
  assert.equal(professionLabel({ name: "Fishing", skill: null, max: null }), "Fishing");
});

test("synced ago", () => {
  const now = new Date("2026-11-23T12:00:00Z");
  assert.equal(syncedAgo(null, now), "ještě nenačteno");
  assert.equal(syncedAgo("2026-11-23T11:59:30Z", now), "právě teď");
  assert.equal(syncedAgo("2026-11-23T11:30:00Z", now), "před 30 min");
  assert.equal(syncedAgo("2026-11-23T09:00:00Z", now), "před 3 h");
  assert.equal(syncedAgo("2026-11-22T10:00:00Z", now), "včera");
});

test("character form validation", () => {
  assert.equal(validateCharacterForm("Thrallík", "Pyrewood Village", "60"), null);
  assert.match(validateCharacterForm("a", "x", ""), /2–12 písmen/);
  assert.match(validateCharacterForm("Thrall", " ", ""), /realm/);
  assert.match(validateCharacterForm("Thrall", "x", "200"), /1–100/);
});

// Codex review #91: „Obnovit vše" nehlásí úspěch, když se nic nenačetlo.
test("batch refresh message", async () => {
  const { batchMessage } = await import("./lib.ts");
  assert.deepEqual(batchMessage({ synced: 3, results: { ok: 3 }, due: 3, remaining: 0 }), { tone: "success", text: "Aktualizováno: 3." });
  assert.deepEqual(batchMessage({ synced: 0, results: { unavailable: 1 }, due: 1, remaining: 0 }),
    { tone: "warning", text: "Nic se neaktualizovalo · selhalo: 1× API neodpovídá." });
  // zbytek nad limit dávky není chyba – úspěch s informací
  assert.deepEqual(batchMessage({ synced: 10, results: { ok: 10 }, due: 12, remaining: 2 }),
    { tone: "success", text: "Aktualizováno: 10 · zbývá 2 (další se načtou při příští obnově)." });
  assert.equal(batchMessage({ synced: 0, skipped: "not_configured" }).tone, "warning");
});
