// Roadmap 4B: oblasti mají české popisky a neznámá oblast nespadne.
import assert from "node:assert/strict";
import { test } from "node:test";

import { AREA_STYLES, areaMeta } from "./areas.ts";

test("known areas have Czech labels", () => {
  assert.equal(areaMeta("school").label, "Škola");
  assert.equal(areaMeta("WORK").label, "Práce");
  assert.equal(areaMeta("reminders").label, "Připomínky");
  for (const meta of Object.values(AREA_STYLES)) assert.ok(meta.bg && meta.border && meta.text && meta.label);
});

test("unknown area falls back to a neutral chip with its own name", () => {
  assert.deepEqual(areaMeta("garden").label, "garden");
  assert.equal(areaMeta(null).label, "Obecné");
  assert.equal(areaMeta(undefined).bg, "bg-zinc-500/10");
});
