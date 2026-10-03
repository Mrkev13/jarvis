// Roadmap 4B: pomocné funkce stránky Práce.
import assert from "node:assert/strict";
import { test } from "node:test";

import { formatCzkExact } from "./format.ts";

import { estimateEarnings, financeSyncMeta, groupSessionsByDay } from "./work.ts";

const s = (id, date, hours, earnings, extra = {}) => ({
  id, date, hours, earnings, project: "", description: "", hourly_rate: 0, ...extra,
});

test("groups sessions by day, newest day first, keeps API order within a day", () => {
  const days = groupSessionsByDay([
    s(1, "2026-10-06", 4, 800),
    s(5, "2026-10-09", 5, 1250),
    s(8, "2026-10-09", 1.5, 375),
    s(2, "2026-10-08", 3, 600),
  ]);
  assert.deepEqual(days.map((d) => d.date), ["2026-10-09", "2026-10-08", "2026-10-06"]);
  assert.deepEqual(days[0].sessions.map((x) => x.id), [5, 8]);
  assert.equal(days[0].hours, 6.5);
  assert.equal(days[0].earnings, 1625);
});

test("day totals avoid float noise and ignore missing numbers", () => {
  const [day] = groupSessionsByDay([s(1, "2026-10-01", 0.1, 0.1), s(2, "2026-10-01", 0.2, null)]);
  assert.equal(day.hours, 0.3);
  assert.equal(day.earnings, 0.1);
});

test("empty input gives no days", () => {
  assert.deepEqual(groupSessionsByDay([]), []);
});

test("finance sync label", () => {
  assert.equal(financeSyncMeta({ finance_transaction_id: 3, sync_to_finance: true, earnings: 10 }).tone, "success");
  assert.equal(financeSyncMeta({ finance_transaction_id: null, sync_to_finance: true, earnings: 10 }).tone, "warning");
  assert.equal(financeSyncMeta({ finance_transaction_id: null, sync_to_finance: true, earnings: 0 }), null);
  assert.equal(financeSyncMeta({ finance_transaction_id: null, sync_to_finance: false, earnings: 10 }), null);
});

test("earnings estimate", () => {
  assert.equal(estimateEarnings("7.5", "300"), 2250);
  assert.equal(estimateEarnings("", "300"), null);
  assert.equal(estimateEarnings("2", "abc"), null);
});

test("day total and rows reconcile when shown with formatCzkExact (Roadmap 4B.1)", () => {
  const s = { project: "XYZ", description: "", hourly_rate: 375, hours: 6.5, earnings: 2437.5, date: "2026-10-10" };
  const [day] = groupSessionsByDay([{ ...s, id: 1 }, { ...s, id: 2 }]);
  const nb = (x) => x.replace(/ /g, " ");
  assert.deepEqual(day.sessions.map((x) => nb(formatCzkExact(x.earnings))), ["2 437,50 Kč", "2 437,50 Kč"]);
  assert.equal(nb(formatCzkExact(day.earnings)), "4 875 Kč");
});
