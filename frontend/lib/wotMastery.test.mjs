// MRK-106: tabulka M-ek – filtry, řazení, možnosti filtrů, štítek odznaku.
import assert from "node:assert/strict";
import { test } from "node:test";

import { EMPTY_FILTER, filterMastery, markText, masteryOptions, sortMastery, tierLabel } from "./wotMastery.ts";

const row = (tank_id, name, tier, nation, mark, extra = {}) => ({
  tank_id, name, short_name: null, tag: null, tier, nation, nation_label: { ussr: "SSSR", germany: "Německo" }[nation] ?? nation,
  type: null, type_label: null, mark, mark_label: ["–", "III", "II", "I", "M"][mark], battles: 10 * tank_id, ace_count: mark === 4 ? 1 : 0,
  ace_detected_at: null, ace_milestone_id: null, pending_replay: false, ...extra,
});
const ROWS = [row(1, "IS-3", 8, "ussr", 2), row(2, "Object 279 (e)", 10, "ussr", 4), row(3, "Tiger II", 8, "germany", 4), row(4, "Löwe", 8, "germany", 0)];

test("filters: tier, nation, missing only, search without diacritics", () => {
  assert.deepEqual(filterMastery(ROWS, { ...EMPTY_FILTER, tier: 8, missingOnly: true }).map((r) => r.name), ["IS-3", "Löwe"]);
  assert.deepEqual(filterMastery(ROWS, { ...EMPTY_FILTER, nation: "germany" }).map((r) => r.tank_id), [3, 4]);
  assert.deepEqual(filterMastery(ROWS, { ...EMPTY_FILTER, q: "lowe" }).map((r) => r.tank_id), [4]);
  assert.equal(filterMastery(ROWS, EMPTY_FILTER).length, 4);
});

test("sorting", () => {
  assert.deepEqual(sortMastery(ROWS, "tier").map((r) => r.tank_id), [2, 3, 1, 4]);
  assert.deepEqual(sortMastery(ROWS, "mark").map((r) => r.tank_id), [2, 3, 1, 4]);
  assert.deepEqual(sortMastery(ROWS, "battles").map((r) => r.tank_id), [4, 3, 2, 1]);
  assert.deepEqual(sortMastery(ROWS, "name").map((r) => r.name), ["IS-3", "Löwe", "Object 279 (e)", "Tiger II"]);
});

test("filter options and labels", () => {
  const o = masteryOptions(ROWS);
  assert.deepEqual(o.tiers, [10, 8]);
  assert.deepEqual(o.nations, [{ value: "germany", label: "Německo" }, { value: "ussr", label: "SSSR" }]);
  assert.equal(tierLabel(10), "X");
  assert.equal(tierLabel(null), "–");
  assert.equal(markText({ mark: 4, mark_label: "M", ace_count: 3 }), "M ×3");
  assert.equal(markText({ mark: 4, mark_label: "M", ace_count: 1 }), "M");
  assert.equal(markText({ mark: 2, mark_label: "II", ace_count: 0 }), "II");
});
