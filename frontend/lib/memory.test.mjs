// Roadmap 4B: Paměť – dotaz filtrů, payload a popisky kategorií.
import assert from "node:assert/strict";
import { test } from "node:test";

import { distinctSorted, EMPTY_MEMORY_FILTERS, memoryCategoryLabel, memoryPayload, memoryQuery } from "./memory.ts";

test("query keeps the backend parameters and skips empty filters", () => {
  assert.equal(memoryQuery(EMPTY_MEMORY_FILTERS), "");
  assert.equal(
    memoryQuery({ q: " ráno ", area: "school", category: "all", includeInactive: true }),
    "q=r%C3%A1no&area=school&include_inactive=true",
  );
});

test("payload trims and falls back like before", () => {
  assert.deepEqual(memoryPayload({ area: " ", category: "", content: "  x ", importance: 7, active: false }), {
    area: "general",
    category: "context",
    content: "x",
    importance: 7,
    active: false,
  });
});

test("category labels and distinct options", () => {
  assert.equal(memoryCategoryLabel("preference"), "Preference");
  assert.equal(memoryCategoryLabel("Context"), "Kontext");
  assert.equal(memoryCategoryLabel("vlastní"), "vlastní");
  assert.deepEqual(distinctSorted(["work", "finance", "work", "", null, "škola"]), ["finance", "škola", "work"]);
});
