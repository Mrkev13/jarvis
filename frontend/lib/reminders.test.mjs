// Phase D: pomocné funkce připomínek – pražský čas nezávisle na pásmu prohlížeče/serveru.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createBody,
  defaultDueLocal,
  emptyForm,
  formatPrague,
  groupReminders,
  snoozeOptions,
  stateLabel,
  toPragueInputValue,
} from "./reminders.ts";

test("datetime-local value is Prague wall clock in summer and winter", () => {
  assert.equal(toPragueInputValue(new Date("2026-10-05T06:00:00Z")), "2026-10-05T08:00"); // SELČ
  assert.equal(toPragueInputValue(new Date("2026-12-05T07:00:00Z")), "2026-12-05T08:00"); // SEČ
  assert.equal(toPragueInputValue(new Date("2026-03-29T01:30:00Z")), "2026-03-29T03:30"); // po jarním posunu
});

test("default due is about an hour ahead, rounded to a quarter hour (Prague)", () => {
  assert.equal(defaultDueLocal(new Date("2026-10-04T12:07:00Z")), "2026-10-04T15:15");
});

test("formatPrague shows the Prague time", () => {
  assert.match(formatPrague("2026-10-05T06:00:00Z"), /8:00|08:00/);
  assert.equal(formatPrague(null), "–");
});

test("create body for one-time, daily and weekly reminders", () => {
  const base = { ...emptyForm(new Date("2026-10-04T12:00:00Z")), title: " fyzio " };
  assert.deepEqual(createBody({ ...base, dueLocal: "2026-10-05T08:00" }), {
    title: "fyzio", note: undefined, recurrence: "none", due_local: "2026-10-05T08:00",
  });
  assert.deepEqual(createBody({ ...base, mode: "daily", timeLocal: "07:30" }), {
    title: "fyzio", note: undefined, recurrence: "daily", time_local: "07:30",
  });
  assert.deepEqual(createBody({ ...base, mode: "weekly", timeLocal: "19:00", weekdays: [6, 0, 6] }), {
    title: "fyzio", note: undefined, recurrence: "weekly", time_local: "19:00", weekdays: "0,6",
  });
});

test("create body validation", () => {
  const base = emptyForm(new Date("2026-10-04T12:00:00Z"));
  assert.throws(() => createBody({ ...base, title: "  " }));
  assert.throws(() => createBody({ ...base, title: "x", dueLocal: "" }));
  assert.throws(() => createBody({ ...base, title: "x", mode: "weekly", weekdays: [] }));
});

test("snooze options include tomorrow 8:00 in Prague", () => {
  const opts = snoozeOptions(new Date("2026-10-04T22:30:00Z")); // 5. 10. 00:30 v Praze
  assert.deepEqual(opts.map((o) => o.label), ["+15 min", "+1 h", "Zítra 8:00"]);
  assert.deepEqual(opts[2].body, { until_local: "2026-10-06T08:00" });
});

test("grouping puts due reminders first and history separately", () => {
  const mk = (id, status, state, due_at) => ({ id, title: `r${id}`, note: "", status, state, due_at,
    due_local: "", due_label: "", next_label: "", recurrence: "none", recurrence_label: "" });
  const groups = groupReminders([
    mk(1, "scheduled", "scheduled", "2026-10-06T06:00:00Z"),
    mk(2, "fired", "due", "2026-10-04T06:00:00Z"),
    mk(3, "done", "done", "2026-10-01T06:00:00Z"),
    mk(4, "scheduled", "scheduled", "2026-10-05T06:00:00Z"),
  ]);
  assert.deepEqual(groups.due.map((r) => r.id), [2]);
  assert.deepEqual(groups.upcoming.map((r) => r.id), [4, 1]);
  assert.deepEqual(groups.history.map((r) => r.id), [3]);
  assert.equal(stateLabel(groups.due[0]), "Teď");
  assert.equal(stateLabel(groups.history[0]), "Hotovo");
});
