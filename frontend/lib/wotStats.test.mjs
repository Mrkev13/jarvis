// MRK-153: čisté funkce grafů statistik WoT.
import assert from "node:assert/strict";
import { test } from "node:test";

import { changeLabel, compactNumber, dayLabel, linePoints, nearestIndex, niceTicks, pct, stepPath } from "./wotStats.ts";

test("nice axis ticks", () => {
  assert.deepEqual(niceTicks(5100, 5180), [5100, 5120, 5140, 5160, 5180]);
  assert.deepEqual(niceTicks(0, 9), [0, 5, 10]);
  const flat = niceTicks(1000, 1000);
  assert.ok(flat[0] < 1000 && flat[flat.length - 1] > 1000, "stejná hodnota → osa kolem ní");
  assert.deepEqual(niceTicks(NaN, 1), []);
});

test("step line runs to the end of the axis", () => {
  const plot = { w: 200, h: 100, l: 20, r: 10, t: 10, b: 20 };
  const x0 = Date.parse("2026-11-20T00:00:00Z");
  const x1 = Date.parse("2026-11-27T00:00:00Z");
  const { pts } = linePoints([{ at: "2026-11-20T00:00:00Z", value: 10 }, { at: "2026-11-23T12:00:00Z", value: 20 }], plot, x0, x1, [10, 20]);
  assert.equal(pts.length, 3);
  assert.equal(pts[0].x, 20);
  assert.equal(pts[2].x, 190, "poslední stav trvá do konce osy");
  assert.equal(pts[0].y, 80);
  assert.equal(pts[1].y, 10);
  assert.equal(stepPath(pts), "M20.0,80.0H105.0V10.0H190.0V10.0");
  assert.equal(nearestIndex([20, 105, 190], 120), 1);
});

test("labels", () => {
  assert.equal(compactNumber(8_450_000), "8,5 M");
  assert.equal(compactNumber(184_000), "184 k");
  assert.equal(compactNumber(3210.6).replace(/\s/g, " "), "3 211");
  assert.equal(compactNumber(null), "–");
  assert.equal(pct(57.14), "57,1 %");
  assert.equal(dayLabel("2026-11-07"), "7. 11.");
  assert.equal(changeLabel([{ at: "a", value: 5100 }, { at: "b", value: 5180 }]), "+80");
  assert.equal(changeLabel([{ at: "a", value: 2_000_000 }, { at: "b", value: 800_000 }]), "−1,2 M");
  assert.equal(changeLabel([{ at: "a", value: 1 }, { at: "b", value: 1 }]), "beze změny");
  assert.equal(changeLabel([{ at: "a", value: 1 }]), null);
});
