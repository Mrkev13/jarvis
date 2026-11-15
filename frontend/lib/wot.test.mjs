import assert from "node:assert/strict";
import { test } from "node:test";

import {
  activeXpRemaining,
  emptyGrindDraft,
  grindBody,
  grindStatusMeta,
  masterySummary,
  resourceEntries,
} from "./wot.ts";

test("resourceEntries posílá jen vyplněné měny v pevném pořadí", () => {
  assert.deepEqual(resourceEntries({ gold: 12500, credits: 8450000, free_xp: undefined }), [
    { resource: "credits", amount: 8450000 },
    { resource: "gold", amount: 12500 },
  ]);
  assert.deepEqual(resourceEntries({}), []);
});

test("grindBody validuje a skládá stejné tělo jako dřív", () => {
  const empty = grindBody(emptyGrindDraft());
  assert.equal(empty.ok, false);
  assert.ok(!empty.ok && empty.errors.tank && empty.errors.xp_remaining);

  const res = grindBody({ tank: "  Kranvagn ", xp_remaining: "64000", priority: "high", status: "paused" });
  assert.deepEqual(res, {
    ok: true,
    body: { tank: "Kranvagn", xp_remaining: 64000, priority: "high", status: "paused" },
  });
  assert.equal(grindBody({ ...emptyGrindDraft(), tank: "T-100 LT", xp_remaining: "0" }).ok, true);
});

test("grindStatusMeta dává české popisky", () => {
  assert.deepEqual(grindStatusMeta("completed"), { tone: "success", label: "Dokončeno" });
  assert.deepEqual(grindStatusMeta("paused"), { tone: "neutral", label: "Pozastaveno" });
  assert.deepEqual(grindStatusMeta("active"), { tone: "accent", label: "Aktivní" });
  assert.equal(grindStatusMeta("weird").label, "weird");
});


test("activeXpRemaining sčítá jen aktivní grindy", () => {
  assert.equal(
    activeXpRemaining([
      { tank: "A", xp_remaining: 128000, priority: "high", status: "active" },
      { tank: "B", xp_remaining: 64000, priority: "medium", status: "active" },
      { tank: "C", xp_remaining: 5000, priority: "low", status: "paused" },
    ]),
    192000,
  );
});

// ===================== Game Enrichment B =====================
import {
  activeGrinds, celebrationDuration, CELEBRATION_MS, durationLabel, emptyMilestoneDraft, galleryStep, grindProgress,
  masteryLabel, milestoneBody, milestoneDraftFrom, milestoneStats, screenshotFileError, screenshotUploadPath,
  sortCompletions, sortMilestones, grindStatusOptions, grindSummary,
} from "./wot.ts";

test("aktivní → splněný: splněné odcházejí z aktivních, průběh 100 %", () => {
  const grinds = [
    { id: 1, tank: "Kranvagn", xp_remaining: 52000, priority: "high", status: "active", xp_start: 104000 },
    { id: 2, tank: "T-100 LT", xp_remaining: 0, priority: "low", status: "completed" },
    { id: 3, tank: "Pauza", xp_remaining: 10, priority: "low", status: "paused", xp_start: null },
  ];
  assert.deepEqual(activeGrinds(grinds).map((g) => g.id), [1, 3]);
  assert.equal(grindProgress(grinds[0]), 50);
  assert.equal(grindProgress(grinds[1]), 100);
  assert.equal(grindProgress(grinds[2]), null, "bez základu průběh neznámý");
  assert.equal(grindProgress({ ...grinds[0], progress: 80 }), 80, "průběh ze serveru má přednost");
});

test("oslava splnění: 1,3 s, při omezeném pohybu hned", () => {
  assert.equal(celebrationDuration(false), CELEBRATION_MS);
  assert.ok(CELEBRATION_MS >= 1000 && CELEBRATION_MS <= 1500);
  assert.equal(celebrationDuration(true), 0);
});

test("historie: nejnovější první, bez data na konci; délka česky", () => {
  const c = (id, tank, at) => ({ id, tank, completed_at: at, completion_id: null, grind_id: null, started_at: null, xp_start: null, xp_remaining_before: null, duration_days: null, legacy: !at });
  const sorted = sortCompletions([c("a", "Old", "2026-09-01T10:00:00Z"), c("b", "Legacy", null), c("c", "New", "2026-10-07T10:00:00Z")]);
  assert.deepEqual(sorted.map((x) => x.tank), ["New", "Old", "Legacy"]);
  assert.equal(durationLabel(0), "za méně než den");
  assert.equal(durationLabel(3), "za 3 dny");
  assert.equal(durationLabel(12), "za 12 dní");
  assert.equal(durationLabel(null), null);
});

test("milník: povinný jen tank, čísla v limitech, datum ne v budoucnu", () => {
  const d = { ...emptyMilestoneDraft(), tank: " Progetto 65 ", map_name: "Útesy", damage: "5 205", assist: "1754", kills: "5", base_xp: "1208", played_on: "2026-09-14" };
  const ok = milestoneBody(d, "2026-10-07");
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.body, { tank: "Progetto 65", map_name: "Útesy", played_on: "2026-09-14", mastery: "ace", notes: null, favorite: false, damage: 5205, assist: 1754, kills: 5, base_xp: 1208 });
  const minimal = milestoneBody({ ...emptyMilestoneDraft(), tank: "ELC EVEN 90" }, "2026-10-07");
  assert.equal(minimal.ok, true);
  assert.equal(minimal.body.damage, null);
  const bad = milestoneBody({ ...emptyMilestoneDraft(), kills: "16", damage: "-1", base_xp: "1.5", played_on: "2026-12-01" }, "2026-10-07");
  assert.equal(bad.ok, false);
  assert.deepEqual(Object.keys(bad.errors).sort(), ["base_xp", "damage", "kills", "played_on", "tank"]);
});

test("karta milníku: statistiky bez vymyšlených nul, oblíbené první, mistr", () => {
  assert.deepEqual(milestoneStats({ damage: 1594, assist: 5975, kills: 2, base_xp: 1412 }).map((s) => s.label), ["Poškození", "Asistence", "Zničení", "Základní XP"]);
  assert.deepEqual(milestoneStats({ damage: 5205, assist: null, kills: null, base_xp: null }).map((s) => s.key), ["damage"]);
  assert.equal(masteryLabel("ace"), "Mistr (Mko)");
  assert.equal(masteryLabel(null), null);
  const m = (id, fav, played) => ({ id, favorite: fav, played_on: played });
  assert.deepEqual(sortMilestones([m(1, false, "2026-10-01"), m(2, true, "2026-09-01"), m(3, false, "2026-10-05")]).map((x) => x.id), [2, 3, 1]);
  const draft = milestoneDraftFrom({ id: 1, tank: "Progetto 65", map_name: null, played_on: null, damage: 5205, assist: null, kills: 5, base_xp: null, mastery: "ace", notes: null, favorite: true, screenshots: [] });
  assert.equal(draft.damage, "5205");
  assert.equal(draft.assist, "");
  assert.equal(draft.favorite, true);
});

test("screenshoty: typ a velikost před nahráním, cesta s metadaty, galerie dokola", () => {
  assert.equal(screenshotFileError({ name: "a.png", type: "image/png", size: 1000 }), null);
  assert.match(screenshotFileError({ name: "a.gif", type: "image/gif", size: 1000 }), /PNG, JPEG nebo WebP/);
  assert.match(screenshotFileError({ name: "a.png", type: "image/png", size: 11 * 1024 * 1024 }), /10 MB/);
  assert.match(screenshotFileError({ name: "a.png", type: "image/png", size: 0 }), /prázdný/);
  assert.equal(screenshotUploadPath(4, "Útesy 1.png", " Mko! "), "/wot/milestones/4/screenshots?filename=%C3%9Atesy+1.png&caption=Mko%21");
  assert.equal(galleryStep(2, 3, 1), 0);
  assert.equal(galleryStep(0, 3, -1), 2);
  assert.equal(galleryStep(0, 0, 1), 0);
});

// Regrese B (lokální ověření): nový grind „Dokončeno" zmizel bez historie; hlavička během oslavy ukazovala starý stav.
test("formulář nového grindu nenabízí Dokončeno, úprava ano", () => {
  assert.deepEqual(grindStatusOptions("create").map((o) => o.value), ["active", "paused"]);
  assert.deepEqual(grindStatusOptions("edit").map((o) => o.value), ["active", "paused", "completed"]);
});

test("souhrn hlavičky nepočítá grind, který server právě splnil", () => {
  const grinds = [
    { id: 1, tank: "VZ.55", xp_remaining: 205988, priority: "high", status: "active" },
    { id: 8, tank: "Kranvagn", xp_remaining: 1000, priority: "low", status: "active" },
    { id: 9, tank: "Pauza", xp_remaining: 500, priority: "low", status: "paused" },
  ];
  assert.deepEqual(grindSummary(grinds), { activeCount: 2, remaining: 206988 });
  assert.deepEqual(grindSummary(grinds, 8), { activeCount: 1, remaining: 205988 });
  assert.deepEqual(grindSummary(grinds, null), { activeCount: 2, remaining: 206988 });
  assert.deepEqual(grindSummary([grinds[1]], 8), { activeCount: 0, remaining: 0 });
});

test("masterySummary počítá každé Mko, i opakované na stejném tanku, a jen Mistr", () => {
  const m = (tank, mastery, milestone_type = "mastery") => ({ tank, mastery, milestone_type });
  const summary = masterySummary([
    m("Kranvagn", "ace"), m("Kranvagn", "ace"), m("Škoda T 56", "ace"), m("Kranvagn", "first"),
    m("IS-7", null), m("Bat.-Châtillon 25 t", "ace"),
  ]);
  assert.equal(summary.total, 4);
  assert.equal(summary.tanks, 3);
  assert.deepEqual(summary.byTank[0], { tank: "Kranvagn", count: 2 });
  assert.deepEqual(summary.byTank.map((t) => t.tank).slice(1), ["Bat.-Châtillon 25 t", "Škoda T 56"]);
  assert.deepEqual(masterySummary([]), { total: 0, tanks: 0, byTank: [] });
});
