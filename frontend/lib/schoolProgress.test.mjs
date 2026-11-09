// MRK-86: popisky a tóny pro zápočet a docházku (výpočty dělá backend).
import assert from "node:assert/strict";
import { test } from "node:test";

import { absenceTone, creditTone, examsSummary, parseAbsenceLimit, shortDate, weekLabel, weekState } from "./schoolProgress.ts";

test("credit and absence tones", () => {
  assert.deepEqual(["pending", "passed", "failed"].map(creditTone), ["neutral", "success", "danger"]);
  assert.equal(absenceTone({ level: "exceeded", warning: "x" }), "danger");
  assert.equal(absenceTone({ level: "last", warning: "x" }), "warning");
  assert.equal(absenceTone({ level: "exceeded", warning: null }), "neutral", "splněný zápočet nevaruje");
  assert.equal(absenceTone({ level: null, warning: null }), "neutral");
});

test("dates without timezone shifts", () => {
  assert.equal(shortDate("2026-11-09"), "9. 11.");
  assert.equal(weekLabel("2026-01-05"), "týden od 5. 1.");
});

test("week state from the recorded weeks", () => {
  const p = { attendance: { weeks: [{ week_start: "2026-11-09", present: false }, { week_start: "2026-11-02", present: true }] } };
  assert.equal(weekState(p, "2026-11-09"), false);
  assert.equal(weekState(p, "2026-11-02"), true);
  assert.equal(weekState(p, "2026-10-26"), null);
});

test("exam summary", () => {
  assert.equal(examsSummary({ open: 0, closed: 0, passed: 0, failed: 0, results: [] }), null);
  assert.equal(examsSummary({ open: 1, closed: 2, passed: 1, failed: 1, results: [] }), "Zkoušky: 2 uzavřené (1 složeno, 1 nesloženo), 1 čeká");
  assert.equal(examsSummary({ open: 0, closed: 1, passed: 0, failed: 0, results: [] }), "Zkoušky: 1 uzavřená");
  assert.equal(examsSummary({ open: 0, closed: 5, passed: 5, failed: 0, results: [] }), "Zkoušky: 5 uzavřených (5 složeno)");
});

test("absence limit input", () => {
  assert.equal(parseAbsenceLimit(""), null);
  assert.equal(parseAbsenceLimit(" 3 "), 3);
  assert.equal(parseAbsenceLimit("0"), 0);
  for (const bad of ["-1", "53", "2.5", "abc", "100"]) assert.equal(parseAbsenceLimit(bad), "invalid", bad);
});
