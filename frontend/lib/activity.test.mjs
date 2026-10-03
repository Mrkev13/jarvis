// Roadmap 4B: Aktivita – dotaz filtrů, seskupení po pražských dnech, české popisky.
import assert from "node:assert/strict";
import { test } from "node:test";

import { activityActionLabel, activityQuery, dayHeading, EMPTY_ACTIVITY_FILTERS, groupByDay } from "./activity.ts";

test("query uses backend parameter names and Prague day bounds", () => {
  assert.equal(activityQuery(EMPTY_ACTIVITY_FILTERS, 20, 0), "limit=20&offset=0");
  const qs = new URLSearchParams(
    activityQuery({ areas: ["finance", "work"], actionType: "create", q: " kava ", fromDate: "2026-10-01", toDate: "2026-10-02" }, 20, 40),
  );
  assert.equal(qs.get("area"), "finance,work");
  assert.equal(qs.get("action_type"), "create");
  assert.equal(qs.get("q"), "kava");
  assert.equal(qs.get("from_date"), "2026-09-30T22:00:00.000Z");
  assert.equal(qs.get("to_date"), "2026-10-02T21:59:59.999Z");
  assert.equal(qs.get("offset"), "40");
});

test("groups naive UTC timestamps by Prague day", () => {
  const groups = groupByDay([
    { id: 1, timestamp: "2026-10-10T22:30:00" }, // 11. 10. 0:30 v Praze
    { id: 2, timestamp: "2026-10-10T21:30:00" }, // 10. 10. 23:30
    { id: 3, timestamp: "2026-10-10T08:00:00" },
  ]);
  assert.deepEqual(groups.map(([k, v]) => [k, v.map((x) => x.id)]), [["2026-10-11", [1]], ["2026-10-10", [2, 3]]]);
});

test("day headings and action labels are Czech", () => {
  assert.equal(dayHeading("2026-10-11", "2026-10-11"), "Dnes");
  assert.equal(dayHeading("2026-10-10", "2026-10-11"), "Včera");
  assert.equal(dayHeading("2026-09-30", "2026-10-11"), "30. 9. 2026");
  assert.equal(activityActionLabel("snooze"), "Odloženo");
  assert.equal(activityActionLabel("custom_x"), "custom_x");
});
