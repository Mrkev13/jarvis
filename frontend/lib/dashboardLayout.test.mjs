// Roadmap 4F: Řídicí centrum na míru – registr, výchozí rozložení, validace uloženého, úpravy, desktopové bloky.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CORE_WIDGETS, MODULE_WIDGETS, DESKTOP_UNITS, defaultLayout, hiddenWidgets, isDefaultLayout, LAYOUT_STORAGE_KEY, moveWidget, needsDashboardData,
  normalizeLayout, packDesktop, WIDGET_IDS, parseStoredLayout, serializeLayout, setWidgetSize, setWidgetVisible, visiblePosition,
  visibleWidgets, WIDGET_SIZES, WIDGETS,
} from "./dashboardLayout.ts";

const ids = (layout) => layout.widgets.map((w) => w.id);
const DEFAULT_IDS = ["daily_briefing", "weekly_review", "today", "attention", "key_metrics", "goals", "upcoming", "work", "finance", "games", "quick_actions"];
// MRK-21: widgety modulů (manifest) jsou ve výchozím stavu skryté → výchozí viditelné rozložení 4B.1 se nemění
const MODULE_IDS = MODULE_WIDGETS.map((w) => w.id);

test("registry: unique semantic ids, sane defaults", () => {
  const all = WIDGETS.map((w) => w.id);
  assert.equal(new Set(all).size, all.length, "unikátní id");
  assert.equal(new Set(WIDGETS.map((w) => w.defaultOrder)).size, WIDGETS.length, "unikátní výchozí pořadí");
  for (const w of WIDGETS) {
    assert.match(w.id, /^[a-z][a-z_]*$/, `${w.id}: sémantické id`);
    assert.ok(w.title.trim(), w.id);
    assert.ok(w.allowedSizes.length >= 1, w.id);
    assert.ok(w.allowedSizes.every((s) => WIDGET_SIZES.includes(s)), w.id);
    assert.ok(w.allowedSizes.includes(w.defaultSize), `${w.id}: výchozí velikost je povolená`);
  }
  assert.equal(LAYOUT_STORAGE_KEY, "standa-hub:dashboard-layout:v1");
  assert.deepEqual(CORE_WIDGETS.map((w) => w.id).sort(), [...WIDGET_IDS].sort(), "jádro = seznam id s komponentami");
  for (const w of MODULE_WIDGETS) {
    assert.equal(w.modules?.length, 1, `${w.id}: widget modulu patří jednomu modulu`);
    assert.ok(w.id.startsWith(`${w.modules[0]}_`), `${w.id}: id s prefixem modulu`);
  }
});

test("default layout: all widgets visible in the 4B.1 order", () => {
  const d = defaultLayout();
  assert.equal(d.version, 1);
  assert.deepEqual(ids(d).filter((id) => !MODULE_IDS.includes(id)), DEFAULT_IDS);
  assert.deepEqual(visibleWidgets(d).map((w) => w.id), DEFAULT_IDS, "viditelné = 4B.1");
  assert.ok(d.widgets.filter((w) => MODULE_IDS.includes(w.id)).every((w) => !w.visible), "widgety modulů skryté");
  assert.deepEqual(d.widgets.map((w) => w.order), d.widgets.map((_, i) => (i + 1) * 10));
  assert.ok(isDefaultLayout(d));
});

test("default desktop packing reproduces the 4B.1 balance", () => {
  const blocks = packDesktop(visibleWidgets(defaultLayout()));
  assert.deepEqual(
    blocks.map((b) => b.columns.map((c) => c.ids)),
    [
      [["daily_briefing", "today"], ["weekly_review", "attention"]],
      [["key_metrics"]],
      [["goals"], ["upcoming"], ["work", "finance"]],
      [["games", "quick_actions"]],
    ],
  );
  assert.deepEqual(blocks[0].columns.map((c) => c.units), [4, 2]);
});

test("packing: rows never exceed the grid; mismatched rows start a new block", () => {
  const blocks = packDesktop([
    { id: "a", size: "medium" }, { id: "b", size: "medium" }, // [M,M]
    { id: "c", size: "large" }, { id: "d", size: "small" },   // [L,S] – jiný tvar
    { id: "e", size: "full" },
  ]);
  assert.deepEqual(blocks.map((b) => b.columns.map((c) => c.ids)), [[["a"], ["b"]], [["c"], ["d"]], [["e"]]]);
  for (const b of blocks) assert.ok(b.columns.reduce((s, c) => s + c.units, 0) <= 6);
  assert.deepEqual(Object.values(DESKTOP_UNITS), [2, 3, 4, 6]);
});

test("validation: malformed, missing and old versions fall back to defaults", () => {
  for (const raw of [null, undefined, 42, "x", [], {}, { version: 2, widgets: [] }, { version: 0, widgets: [] }, { widgets: [] }, { version: 1, widgets: "nope" }, { version: 1, widgets: [] }]) {
    assert.deepEqual(normalizeLayout(raw), defaultLayout(), JSON.stringify(raw));
  }
  assert.deepEqual(parseStoredLayout("{not json"), defaultLayout());
  assert.deepEqual(parseStoredLayout(null), defaultLayout());
});

test("validation: unknown ids dropped, duplicates keep the first, invalid sizes reset", () => {
  const raw = {
    version: 1,
    widgets: [
      { id: "finance", visible: false, order: 1, size: "medium" },
      { id: "obsolete_widget", visible: true, order: 2, size: "small" },
      { id: "finance", visible: true, order: 3, size: "small" },
      { id: "work", visible: "yes", order: 4, size: "full" },     // full Práce nepodporuje
      { id: "games", visible: true, order: 5, size: "gigantic" },
      { id: 7 },
      "junk",
    ],
  };
  const l = normalizeLayout(raw);
  assert.ok(!ids(l).includes("obsolete_widget"));
  assert.equal(ids(l).filter((i) => i === "finance").length, 1);
  const get = (id) => l.widgets.find((w) => w.id === id);
  assert.deepEqual([get("finance").visible, get("finance").size], [false, "medium"], "platná volba zachována");
  assert.equal(get("work").size, "small", "nepovolená velikost → výchozí");
  assert.equal(get("work").visible, true, "neplatná viditelnost → výchozí");
  assert.equal(get("games").size, "full");
  assert.deepEqual(ids(l).filter((i) => ["finance", "work", "games"].includes(i)), ["finance", "work", "games"], "uživatelské pořadí zachováno");
  assert.equal(l.widgets.length, WIDGETS.length, "chybějící widgety doplněny");
});

test("validation: a widget added later lands next to its default neighbour", () => {
  const stored = { version: 1, widgets: defaultLayout().widgets.filter((w) => w.id !== "weekly_review").reverse().map((w, i) => ({ ...w, order: i })) };
  const l = normalizeLayout(stored);
  const order = ids(l);
  assert.equal(order.length, WIDGETS.length);
  assert.equal(order.indexOf("weekly_review"), order.indexOf("daily_briefing") + 1, "za předchůdcem ve výchozím pořadí");
  // nový widget v budoucím registru
  const future = [...WIDGETS, { id: "habits", title: "Návyky", area: null, defaultVisible: true, defaultOrder: 35, defaultSize: "small", allowedSizes: ["small"], usesDashboardData: false }];
  const withNew = normalizeLayout(JSON.parse(serializeLayout(defaultLayout())), future);
  assert.equal(ids(withNew).indexOf("habits"), ids(withNew).indexOf("today") + 1);
  const first = normalizeLayout({ version: 1, widgets: [{ id: "games", visible: true, order: 1, size: "full" }] });
  assert.equal(ids(first)[0], "daily_briefing", "bez předchůdce na začátek");
});

test("round trip through storage keeps choices", () => {
  let l = setWidgetSize(moveWidget(setWidgetVisible(defaultLayout(), "goals", false), "finance", -1), "finance", "medium");
  const back = parseStoredLayout(serializeLayout(l));
  assert.deepEqual(back, l);
  assert.ok(!isDefaultLayout(back));
});

test("reorder moves among visible widgets and stops at edges", () => {
  const d = defaultLayout();
  assert.equal(moveWidget(d, "daily_briefing", -1), d, "první nahoru nic");
  assert.equal(moveWidget(d, "quick_actions", 1), d, "poslední dolů nic");
  const down = moveWidget(d, "daily_briefing", 1);
  assert.deepEqual(ids(down).slice(0, 2), ["weekly_review", "daily_briefing"]);
  const hidden = setWidgetVisible(d, "weekly_review", false);
  const skip = moveWidget(hidden, "daily_briefing", 1);
  assert.deepEqual(ids(skip).slice(0, 3), ["today", "weekly_review", "daily_briefing"], "skrytý se přeskočí");
  assert.equal(moveWidget(hidden, "weekly_review", 1), hidden, "skrytý se neposouvá");
  assert.equal(moveWidget(d, "nope", 1), d);
  assert.deepEqual(visiblePosition(skip, "daily_briefing"), { index: 2, count: 10 });
});

test("hide / show and the dashboard data request", () => {
  let l = defaultLayout();
  l = setWidgetVisible(l, "games", false);
  assert.deepEqual(hiddenWidgets(l).map((w) => w.id).filter((id) => !MODULE_IDS.includes(id)), ["games"]);
  assert.equal(visibleWidgets(l).length, DEFAULT_IDS.length - 1);
  l = setWidgetVisible(l, "games", true);
  assert.ok(isDefaultLayout(l));
  const onlySelfFetching = WIDGETS.reduce((acc, w) => (w.usesDashboardData ? setWidgetVisible(acc, w.id, false) : acc), defaultLayout());
  assert.equal(needsDashboardData(onlySelfFetching), false, "bez widgetů z /dashboard žádný dotaz");
  assert.equal(needsDashboardData(defaultLayout()), true);
});

test("sizes: only allowed sizes are applied", () => {
  const d = defaultLayout();
  assert.equal(setWidgetSize(d, "work", "full"), d);
  assert.equal(setWidgetSize(d, "nope", "small"), d);
  assert.equal(setWidgetSize(d, "work", "medium").widgets.find((w) => w.id === "work").size, "medium");
});

test("reset = default layout", () => {
  const changed = setWidgetVisible(moveWidget(defaultLayout(), "games", -1), "finance", false);
  assert.ok(!isDefaultLayout(changed));
  assert.deepEqual(normalizeLayout(JSON.parse(serializeLayout(defaultLayout()))), defaultLayout());
});
