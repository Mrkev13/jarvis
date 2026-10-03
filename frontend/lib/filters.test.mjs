// Roadmap 4B: FilterBar – sestavení dotazu a počítání aktivních filtrů.
import assert from "node:assert/strict";
import { test } from "node:test";

import { countActiveFilters, filterQuery, isEmptyFilter, toggleInList } from "./filters.ts";

test("empty filters are skipped", () => {
  assert.equal(isEmptyFilter("all"), true);
  assert.equal(isEmptyFilter("  "), true);
  assert.equal(isEmptyFilter([]), true);
  assert.equal(isEmptyFilter(false), true);
  assert.equal(isEmptyFilter(0), false);
  assert.equal(isEmptyFilter("work"), false);
});

test("query keeps order, joins lists and trims text", () => {
  assert.equal(
    filterQuery({ q: "  faktura ", area: ["work", "finance"], category: "all", include_inactive: true, limit: 20 }),
    "q=faktura&area=work%2Cfinance&include_inactive=true&limit=20",
  );
  assert.equal(filterQuery({ q: "", area: [] }), "");
});

test("active filter count and chip toggling", () => {
  assert.equal(countActiveFilters({ q: "x", area: [], type: "all", from: "2026-10-01" }), 2);
  assert.deepEqual(toggleInList(["work"], "finance", ["finance", "work"]), ["finance", "work"]);
  assert.deepEqual(toggleInList(["work", "finance"], "work"), ["finance"]);
});
