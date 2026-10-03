// Roadmap 4G: režim Dnes – převzetí dat, skupiny časové osy, popisky, prázdný den.
import assert from "node:assert/strict";
import { test } from "node:test";

import { groupTimeline, isEmptyDay, itemsLabel, normalizeItem, normalizeToday, shortDate, STATUS_META, untilLabel } from "./today.ts";

const it = (id, extra = {}) => normalizeItem({ id, type: "reminder", title: id, status: "upcoming", ...extra });

test("item normalization is defensive", () => {
  assert.equal(normalizeItem(null), null);
  assert.equal(normalizeItem({ id: "x" }), null, "bez titulku nic");
  const n = normalizeItem({ id: "exam:1", title: "Test", status: "weird", severity: "boom", time: "7:5", href: "https://evil", priority: -1 });
  assert.equal(n.status, "open");
  assert.equal(n.severity, null);
  assert.equal(n.time, null);
  assert.equal(n.href, null, "jen odkazy v aplikaci");
  assert.equal(n.priority, null);
  assert.equal(normalizeItem({ id: "a", title: "b", href: "//evil.com" }).href, null);
  assert.equal(normalizeItem({ id: "a", title: "b", href: "/school?exam=1" }).href, "/school?exam=1");
});

test("payload normalization and partial errors", () => {
  const p = normalizeToday({ date: "2026-10-11", timeline: [{ id: "r:1", title: "A", time: "17:00", status: "upcoming" }, "junk"], errors: { priorities: "x", other: "y", attention: 5 } });
  assert.equal(p.timeline.length, 1);
  assert.deepEqual(p.errors, { priorities: "x" });
  assert.equal(p.summary.next, null);
  assert.deepEqual(normalizeToday(null).timeline, []);
  const withNext = normalizeToday({ summary: { next: { id: "r:1", title: "Fyzio", time: "17:00", status: "upcoming", minutes_until: 135 } } });
  assert.equal(withNext.summary.next.minutes_until, 135);
});

test("timeline groups: timed chronological, untimed, done", () => {
  const g = groupTimeline([
    it("b", { time: "16:15" }), it("done", { time: "08:00", status: "done" }), it("exam", { time: null, status: "open" }),
    it("a", { time: "09:30", status: "due" }), it("past", { time: "07:00", status: "past" }),
  ]);
  assert.deepEqual(g.timed.map((x) => x.id), ["past", "a", "b"], "proběhlé zůstávají v ose (chronologie)");
  assert.deepEqual(g.untimed.map((x) => x.id), ["exam"]);
  assert.deepEqual(g.done.map((x) => x.id), ["done"]);
});

test("Czech labels", () => {
  assert.equal(untilLabel(135), "za 2 h 15 min");
  assert.equal(untilLabel(120), "za 2 h");
  assert.equal(untilLabel(5), "za 5 min");
  assert.equal(untilLabel(0), "teď");
  assert.equal(untilLabel(null), "");
  assert.equal(itemsLabel(1), "1 položka");
  assert.equal(itemsLabel(3), "3 položky");
  assert.equal(itemsLabel(0), "0 položek");
  assert.equal(itemsLabel(7), "7 položek");
  assert.equal(shortDate("2026-10-16"), "pá 16. 10.");
  assert.equal(shortDate("2026-10-25"), "ne 25. 10.", "nezávislé na časové zóně prohlížeče");
  assert.equal(shortDate(null), "");
  for (const meta of Object.values(STATUS_META)) assert.ok(meta.label, "stav vždy i slovem");
});

test("empty day vs. day with only errors", () => {
  assert.equal(isEmptyDay(normalizeToday({ upcoming: [{ id: "x", title: "Zítra" }] })), true, "jen budoucí = prázdný den");
  assert.equal(isEmptyDay(normalizeToday({ errors: { timeline: "x" } })), false, "chyba není prázdný den");
  assert.equal(isEmptyDay(normalizeToday({ attention: [{ id: "x", title: "Po termínu" }] })), false);
});
