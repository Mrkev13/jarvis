// Škola: popisky, dny do termínu (bez posunu pásma), řazení termínů.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assignmentStatusMeta,
  creditsLabel,
  daysUntil,
  deadlineMeta,
  examStatusMeta,
  examTypeLabel,
  isDoneStatus,
  isExamClosed,
  sortByDate,
} from "./school.ts";

test("daysUntil counts calendar days from the local date", () => {
  const today = new Date(2026, 9, 3, 23, 30); // 3. 10. 2026 pozdě večer místního času
  assert.equal(daysUntil("2026-10-03", today), 0);
  assert.equal(daysUntil("2026-10-04", today), 1);
  assert.equal(daysUntil("2026-10-06", today), 3);
  assert.equal(daysUntil("2026-10-02", today), -1);
  assert.equal(daysUntil("2026-09-25", today), -8);
  assert.equal(daysUntil(null, today), null);
  assert.equal(daysUntil("", today), null);
  assert.equal(daysUntil("nesmysl", today), null);
});

test("daysUntil is not shifted across DST changes", () => {
  const beforeWinter = new Date(2026, 9, 24, 0, 5); // den před přechodem na zimní čas
  assert.equal(daysUntil("2026-10-26", beforeWinter), 2);
  const beforeSummer = new Date(2026, 2, 28, 23, 59);
  assert.equal(daysUntil("2026-03-30", beforeSummer), 2);
});

test("deadlineMeta marks overdue and soon deadlines", () => {
  assert.deepEqual(deadlineMeta(-2, "assignment"), { tone: "danger", prefix: "Po termínu", overdue: true });
  assert.deepEqual(deadlineMeta(-2, "exam"), { tone: "warning", prefix: "Proběhlo", overdue: true });
  assert.equal(deadlineMeta(0, "assignment").tone, "warning");
  assert.equal(deadlineMeta(3, "exam").tone, "warning");
  assert.equal(deadlineMeta(4, "exam").tone, "neutral");
  assert.equal(deadlineMeta(null, "assignment").tone, "neutral");
  assert.deepEqual(deadlineMeta(-5, "assignment", true), { tone: "neutral", prefix: null, overdue: false });
});

test("status and type labels are Czech", () => {
  assert.deepEqual(assignmentStatusMeta("done"), { label: "Hotovo", tone: "success" });
  assert.equal(assignmentStatusMeta("in_progress").label, "Rozpracováno");
  assert.equal(assignmentStatusMeta("todo").label, "K vypracování");
  assert.equal(assignmentStatusMeta("weird").label, "weird");
  assert.equal(examStatusMeta("upcoming").label, "Nadcházející");
  assert.deepEqual(examStatusMeta("failed"), { label: "Nesplněno", tone: "danger" });
  assert.equal(examTypeLabel("oral"), "Ústní zkouška");
  assert.equal(examTypeLabel("custom"), "custom");
  assert.ok(isDoneStatus("DONE"));
  assert.ok(!isDoneStatus("todo"));
  assert.ok(isExamClosed("failed"));
  assert.ok(!isExamClosed("upcoming"));
});

test("sortByDate puts missing dates last and keeps order on ties", () => {
  const items = [
    { id: 1, d: "2026-10-14" },
    { id: 2, d: null },
    { id: 3, d: "2026-10-02" },
    { id: 4, d: "2026-10-14" },
  ];
  assert.deepEqual(sortByDate(items, (x) => x.d).map((x) => x.id), [3, 1, 4, 2]);
  assert.deepEqual(sortByDate(items, (x) => x.d, true).map((x) => x.id), [1, 4, 3, 2]);
});

test("creditsLabel uses Czech plural", () => {
  assert.equal(creditsLabel(1), "1 kredit");
  assert.equal(creditsLabel(3), "3 kredity");
  assert.equal(creditsLabel(5), "5 kreditů");
});
