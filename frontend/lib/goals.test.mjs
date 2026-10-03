// Roadmap 4B: české popisky cílů sdílené stránkou Cíle a Plannerem.
import assert from "node:assert/strict";
import { test } from "node:test";

import { goalPaceMeta, goalSourceMeta, goalStatusMeta, goalTrackingLabel } from "./goals.ts";

test("goal statuses have Czech labels and calm tones", () => {
  assert.deepEqual(goalStatusMeta("completed"), { label: "Splněný", tone: "success" });
  assert.equal(goalStatusMeta("PAUSED").label, "Pozastavený");
  assert.equal(goalStatusMeta("weird").label, "weird");
  assert.equal(goalStatusMeta(null).label, "–");
});

test("tracking label names the source in Czech", () => {
  assert.equal(goalTrackingLabel("manual"), "Ručně");
  assert.equal(goalTrackingLabel("automatic", "work_month_hours"), "Automaticky · Práce – hodiny tento měsíc");
  assert.equal(goalTrackingLabel("automatic", "unknown_src"), "Automaticky · unknown_src");
  assert.equal(goalSourceMeta("finance_balance")?.unit, "Kč");
});

test("pace: stagnation wins over behind; unknown says nothing", () => {
  assert.equal(goalPaceMeta(true, "behind")?.label, "Stagnuje");
  assert.equal(goalPaceMeta(false, "behind")?.tone, "warning");
  assert.equal(goalPaceMeta(false, "on_track")?.label, "Na cestě");
  assert.equal(goalPaceMeta(false, "unknown"), null);
});
