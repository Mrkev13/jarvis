// MRK-153: čisté funkce grafů statistik WoT.
import assert from "node:assert/strict";
import { test } from "node:test";

import { changeLabel, compactNumber, dayLabel, linePoints, nearestIndex, niceTicks, pct, stepPath, tickLabel } from "./wotStats.ts";

test("nice axis ticks", () => {
  assert.deepEqual(niceTicks(5100, 5180), [5100, 5120, 5140, 5160, 5180]);
  assert.deepEqual(niceTicks(0, 9), [0, 5, 10]);
  const flat = niceTicks(1000, 1000);
  assert.ok(flat[0] < 1000 && flat[flat.length - 1] > 1000, "stejná hodnota → osa kolem ní");
  assert.deepEqual(niceTicks(NaN, 1), []);
});

test("axis ticks always cover the data (review #136)", () => {
  assert.deepEqual(niceTicks(100, 149, 3), [100, 120, 140, 160]);
  assert.deepEqual(niceTicks(0, 49, 3), [0, 20, 40, 60]);
  const ranges = [[5100, 5149], [0, 1], [0, 49], [11875, 13125], [8_450_000, 8_700_000], [3, 997], [-120, 35], [0.2, 0.9]];
  for (const [lo, hi] of ranges) {
    const t = niceTicks(lo, hi, 3);
    assert.ok(t[0] <= lo && t[t.length - 1] >= hi, `${lo}–${hi} → ${t.join(",")}`);
  }
});

test("highest point stays inside the plot (review #136)", () => {
  const plot = { w: 320, h: 140, l: 44, r: 8, t: 10, b: 22 };
  const pts = [{ at: "2026-11-20T00:00:00Z", value: 5100 }, { at: "2026-11-22T00:00:00Z", value: 5149 }, { at: "2026-11-24T00:00:00Z", value: 5120 }];
  const ticks = niceTicks(5100, 5149, 3);
  const { pts: xy, sy } = linePoints(pts, plot, Date.parse("2026-11-20T00:00:00Z"), Date.parse("2026-11-27T00:00:00Z"), ticks);
  for (const p of xy) assert.ok(p.y >= plot.t && p.y <= plot.h - plot.b, `y=${p.y}`);
  // sloupce: DailyBars škáluje od 0 do poslední značky – 49 bitev se musí vejít
  const bars = niceTicks(0, 49, 3);
  assert.ok(sy(5149) >= plot.t);
  assert.ok(49 <= bars[bars.length - 1]);
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

test("axis tick labels never merge into the same text", () => {
  const sp = (x) => x.replace(/\s/g, " ");
  const gold = niceTicks(11875, 13125, 3);
  const labels = gold.map((t) => sp(tickLabel(t, gold[1] - gold[0])));
  assert.equal(new Set(labels).size, labels.length, labels.join(" | "));
  assert.equal(sp(tickLabel(8_600_000, 100_000)), "8,6 M");
  assert.equal(sp(tickLabel(190_000, 5000)), "190 k");
  assert.equal(sp(tickLabel(5240, 10)), "5 240");
});
