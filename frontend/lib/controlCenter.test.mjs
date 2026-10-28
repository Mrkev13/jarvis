// MRK-78: Řídicí centrum jako hlavní denní obrazovka – výběr „Co hoří", „Můj den", volno a „Od včera" bez duplicit.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { burningItems, changesPreviewPath, dayItems, latestChanges, nextFreeBlock } from "./controlCenter.ts";
import { normalizeToday } from "./today.ts";

const fixture = (name) => JSON.parse(readFileSync(new URL(`../scripts/fixtures/${name}.json`, import.meta.url), "utf8"));
const today = normalizeToday(fixture("today"));
const upcoming = fixture("dashboard").upcoming;

test("Co hoří: attention first, then school deadlines within 7 days, each record once", () => {
  const items = burningItems(today, upcoming, 20);
  const refs = items.map((i) => i.ref);
  assert.equal(new Set(refs).size, refs.length, "žádná duplicita");
  // pozornost z /today v pořadí serveru, pak termíny podle blízkosti; assignment:1 a exam:3 už jsou v pozornosti
  assert.deepEqual(refs, ["assignment:1", "exam:3", "reminder:5", "goal:1", "calendar_event:41"]);
  assert.ok(!refs.some((r) => ["assignment:3", "assignment:4", "assignment:5"].includes(r)), "termíny za víc než 7 dní ne");
  const moodle = items.find((i) => i.ref === "calendar_event:41");
  assert.deepEqual([moodle.label, moodle.tone, moodle.meta, moodle.href], ["zítra", "warning", "Fyzika", "/calendar?event=41"]);
  assert.equal(items[0].tone, "danger");
  assert.equal(items[0].label, "po termínu");
});

test("Co hoří: nothing from today's timeline, limit and empty inputs", () => {
  const withTimeline = { ...today, timeline: [...today.timeline, { ...today.attention[0] }] };
  assert.ok(!burningItems(withTimeline, upcoming).some((i) => i.ref === today.attention[0].id), "co je v ose, patří do Můj den");
  assert.equal(burningItems(today, upcoming, 2).length, 2);
  assert.deepEqual(burningItems(null, null), []);
  const overdue = burningItems(null, [{ type: "exam", id: 9, title: "Zkouška", area: "school", date: "2026-10-01", days_left: -3, overdue: true }]);
  assert.deepEqual([overdue[0].label, overdue[0].tone, overdue[0].href], ["před 3 dny", "danger", "/school?exam=9"]);
  assert.deepEqual(burningItems(null, [{ type: "goal_target", id: 1, title: "Cíl", area: "goals", date: "x", days_left: 1, overdue: false }]), [], "cíle mají vlastní kartu");
});

test("Můj den: open items, timed chronologically, next first", () => {
  const ids = dayItems(today, 10).map((i) => i.id);
  assert.deepEqual(ids, ["reminder:1", "reminder:7", "assignment:8", "exam:4"], "hotové a proběhlé ne, další první");
  assert.equal(dayItems(today, 2).length, 2);
  assert.deepEqual(dayItems(null), []);
});

test("next free block: the running one counts from now, finished ones are skipped", () => {
  const blocks = [
    { local_start: "08:00", local_end: "10:00", duration_minutes: 120 },
    { local_start: "13:00", local_end: "15:00", duration_minutes: 120 },
    { local_start: "17:00", local_end: "22:00", duration_minutes: 300 },
  ];
  assert.deepEqual(nextFreeBlock(blocks, "14:30"), { ...blocks[1], from: "14:30" });
  assert.deepEqual(nextFreeBlock(blocks, "15:00"), { ...blocks[2], from: "17:00" });
  assert.equal(nextFreeBlock(blocks, "22:10"), null);
  assert.equal(nextFreeBlock(blocks, ""), null);
  assert.equal(nextFreeBlock(null, "10:00"), null);
});

test("Od včera: 24 h window rounded to a minute, newest five", () => {
  const now = Date.parse("2026-10-11T12:30:42.123Z");
  assert.equal(changesPreviewPath(now), "/changes?since=2026-10-10T12%3A30%3A00Z&limit=5");
  assert.equal(changesPreviewPath(now + 10_000), changesPreviewPath(now), "stejná URL v rámci minuty");
  const items = Array.from({ length: 7 }, (_, i) => ({ id: `e${i}`, occurred_at: `2026-10-11T0${i}:00:00Z` }));
  assert.deepEqual(latestChanges(items).map((i) => i.id), ["e6", "e5", "e4", "e3", "e2"]);
  assert.deepEqual(latestChanges(undefined), []);
});
