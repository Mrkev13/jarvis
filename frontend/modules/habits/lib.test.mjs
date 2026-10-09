// MRK-21: Návyky – formuláře, zápis dne, souhrn z dashboardu a manifest (registr bez centrálních úprav).
import assert from "node:assert/strict";
import { test } from "node:test";

import { createBody, emptyHabitForm, entryBody, entryMeasure, percent, shortDay, STATE_META, summaryFrom } from "./lib.ts";
import { HABITS_UI } from "./manifest.ts";
import { MODULES, MODULE_UI, createModuleAccess, manifestFlags } from "../../lib/modules.ts";
import { NAV_PAGES, navPagesFor } from "../../lib/navigation.ts";
import { SEARCH_TARGET_PARAMS, GROUP_ORDER } from "../../lib/search.ts";
import { WIDGETS, availableWidgets } from "../../lib/dashboardLayout.ts";
import { actionLabel, normalizeItem, successMessage, TYPE_LABELS } from "../../lib/today.ts";
import { areaMeta } from "../../lib/areas.ts";

test("create form: name required, target only for count/duration, duration defaults to minutes", () => {
  assert.throws(() => createBody(emptyHabitForm()), /název/);
  assert.deepEqual(createBody({ name: "  Rehab   koleno ", kind: "check", target: "5", unit: "x" }), { name: "Rehab koleno", kind: "check" });
  assert.deepEqual(createBody({ name: "Voda", kind: "count", target: "2,5", unit: "l" }), { name: "Voda", kind: "count", target_value: 2.5, unit: "l" });
  assert.deepEqual(createBody({ name: "Čtení", kind: "duration", target: "20", unit: "" }), { name: "Čtení", kind: "duration", target_value: 20, unit: "min" });
  assert.throws(() => createBody({ name: "Voda", kind: "count", target: "-1", unit: "l" }), /kladné/);
});

test("entry body: done with value or minutes, skipped never carries a value", () => {
  assert.deepEqual(entryBody("check", "done"), { state: "done" });
  assert.deepEqual(entryBody("count", "done", "2,5"), { state: "done", value: 2.5 });
  assert.deepEqual(entryBody("duration", "done", "25"), { state: "done", duration_minutes: 25 });
  assert.deepEqual(entryBody("duration", "skipped", "25"), { state: "skipped" });
  assert.deepEqual(entryBody("count", "done", ""), { state: "done" });
  assert.throws(() => entryBody("count", "done", "abc"), /číslo/);
});

test("display helpers", () => {
  assert.equal(entryMeasure({ unit: "l" }, { id: 1, date: "2026-10-07", state: "done", value: 2.5, duration_minutes: null, note: null }), "2,5 l");
  assert.equal(entryMeasure({ unit: "min" }, { id: 1, date: "2026-10-07", state: "done", value: null, duration_minutes: 25, note: null }), "25 min");
  assert.equal(entryMeasure({ unit: null }, null), "");
  assert.equal(percent(2, 3), 67);
  assert.equal(percent(0, 0), 0);
  assert.equal(shortDay("2026-10-07"), "st 7. 10.");
  assert.equal(STATE_META.missed.label, "vynecháno");
  assert.deepEqual(summaryFrom({ habits: { total: 3, done: 1, skipped: 1, open: 1, week_done: 4, week_expected: 6 } }),
    { total: 3, done: 1, skipped: 1, open: 1, week_done: 4, week_expected: 6 });
  assert.equal(summaryFrom({ habits: null }), null, "vypnutý modul");
});

test("framework: Habits registers only through the manifest + registry line", () => {
  assert.equal(MODULE_UI.habits, HABITS_UI);
  const def = MODULES.find((m) => m.id === "habits");
  assert.ok(def.implemented && def.routes.includes("/habits"));
  assert.ok(NAV_PAGES.some((p) => p.href === "/habits" && p.module === "habits"), "navigace z manifestu");
  assert.ok(SEARCH_TARGET_PARAMS.includes("habit") && GROUP_ORDER.includes("habits"), "vyhledávání z manifestu");
  assert.ok(WIDGETS.some((w) => w.id === "habits_today"), "widget z manifestu");
  assert.equal(TYPE_LABELS.habit, "Návyk");
  assert.equal(areaMeta("habits").label, "Návyky");
  assert.equal(areaMeta("habits").bg, HABITS_UI.area.bg);
});

test("disabled module: no nav page, no widget", () => {
  const off = createModuleAccess({ ...manifestFlags(), habits: false });
  assert.ok(!navPagesFor(off).some((p) => p.href === "/habits"));
  assert.ok(!availableWidgets(off).some((w) => w.id === "habits_today"));
  assert.equal(off.allowsPath("/habits"), false);
  const on = createModuleAccess(manifestFlags());
  assert.ok(availableWidgets(on).some((w) => w.id === "habits_today"));
});

test("Today: module actions are taken from the manifest (complete + skip), unknown ones dropped", () => {
  const item = normalizeItem({ id: "habit:3", type: "habit", title: "Rehab", status: "open", actions: ["complete", "skip", "teleport"] });
  assert.deepEqual(item.actions, ["complete", "skip"]);
  assert.equal(actionLabel(item, "complete"), "Splnit návyk: Rehab");
  assert.equal(actionLabel(item, "skip"), "Přeskočit návyk: Rehab");
  assert.equal(successMessage(item, "skip"), "Návyk „Rehab“ je pro dnešek přeskočený.");
  // jádro beze změny: připomínka nedostane akce modulu
  const reminder = normalizeItem({ id: "reminder:1", type: "reminder", title: "Lék", actions: ["complete", "skip"] });
  assert.deepEqual(reminder.actions, ["complete"]);
  assert.equal(actionLabel(reminder, "complete"), "Dokončit připomínku: Lék");
});
