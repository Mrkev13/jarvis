import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CHANGES_LIMIT,
  changeKindLabel,
  changeKindTone,
  changesQuery,
  createRefetchScheduler,
  groupChangesByDay,
  keepKnownFilters,
} from "./changes.ts";

const NOW = Date.parse("2026-10-08T12:00:30.500Z");

test("changesQuery: since rounded to the minute, limit, sorted module list only when selected", () => {
  const q = new URLSearchParams(changesQuery("24h", [], NOW));
  assert.equal(q.get("since"), "2026-10-07T12:00:00Z");
  assert.equal(q.get("limit"), String(CHANGES_LIMIT));
  assert.equal(q.has("module"), false, "prázdný výběr = vše");
  assert.equal(new URLSearchParams(changesQuery("7d", ["school", "core"], NOW)).get("module"), "core,school");
  assert.equal(changesQuery("30d", [], NOW), changesQuery("30d", [], NOW + 20_000), "stejná minuta = stejná URL");
  assert.equal(new URLSearchParams(changesQuery("nesmysl", [], NOW)).get("since"), "2026-10-01T12:00:00Z");
});

test("kind labels and tones are Czech and stable", () => {
  assert.equal(changeKindLabel("completed"), "Splněno");
  assert.equal(changeKindLabel("done"), "Splněno");
  assert.equal(changeKindLabel("deleted"), "Smazáno");
  assert.equal(changeKindLabel("něco"), "Změna");
  assert.equal(changeKindTone("closed"), "success");
  assert.equal(changeKindTone("deleted"), "warning");
  assert.equal(changeKindTone("updated"), "neutral");
});

test("groupChangesByDay groups by Prague day and keeps the contract shape", () => {
  const item = (id, at) => ({ id, occurred_at: at, module_id: "school", entity_type: "assignment", entity_id: "1",
    kind: "completed", title: "t", summary: "", href: null, source: "event" });
  const groups = groupChangesByDay([item("event:3", "2026-10-08T21:30:00Z"), item("event:2", "2026-10-08T10:00:00Z"),
    item("activity:1", "2026-10-07T09:00:00Z")]);
  assert.deepEqual(groups.map(([d, l]) => [d, l.map((i) => i.id)]), [
    ["2026-10-08", ["event:3", "event:2"]], // 21:30Z = 23:30 v Praze, pořád 8. 10.
    ["2026-10-07", ["activity:1"]],
  ]);
  assert.equal("timestamp" in groups[0][1][0], false);
});

test("keepKnownFilters drops selections that no longer exist in the period", () => {
  assert.deepEqual(keepKnownFilters(["wot", "school"], [{ id: "school", label: "Škola", count: 2 }]), ["school"]);
});

test("refetch scheduler debounces bursts and cancels cleanly", () => {
  const timers = [];
  let runs = 0;
  const s = createRefetchScheduler(() => { runs += 1; }, 600, {
    set: (fn, ms) => { timers.push({ fn, ms, cleared: false }); return timers.length - 1; },
    clear: (h) => { timers[h].cleared = true; },
  });
  s.trigger();
  s.trigger();
  s.trigger();
  assert.deepEqual(timers.map((t) => t.cleared), [true, true, false], "jen poslední čeká");
  timers[2].fn();
  assert.equal(runs, 1);
  s.trigger();
  s.cancel();
  assert.equal(timers[3].cleared, true);
  assert.equal(runs, 1);
});

test("MRK-40: calendar source presence kinds have labels", () => {
  assert.equal(changeKindLabel("source_missing"), "Zmizelo ze zdroje");
  assert.equal(changeKindTone("source_missing"), "warning");
  assert.equal(changeKindLabel("restored"), "Obnoveno");
});
