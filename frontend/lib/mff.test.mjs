// Marvel Future Fight: popisky, build, filtry/řazení a tělo POST beze změny oproti původní stránce.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildBucketMatches,
  characterPayload,
  computeBuildCompleteness,
  emptyCharacterForm,
  filterAndSortCharacters,
  normalizeCharacters,
  statusMeta,
  validateCharacterForm,
} from "./mff.ts";

test("status labels are Czech with semantic tones", () => {
  assert.deepEqual(statusMeta("built"), { tone: "success", label: "Postaveno" });
  assert.deepEqual(statusMeta("building"), { tone: "info", label: "Rozpracováno" });
  assert.equal(statusMeta("in_progress").label, "Rozpracováno");
  assert.equal(statusMeta("planned").label, "Plánováno");
  assert.equal(statusMeta("inactive").label, "Neaktivní");
  assert.equal(statusMeta("").label, "Bez stavu");
});

test("build completeness counts 8 components", () => {
  const base = { tier: "T3", level: 1, uniform: "", ctp: "", artifact: "", uru_slots_total: 20, uru_slots_filled: 0, iso8_set: "", team_supports: "" };
  assert.equal(computeBuildCompleteness(base), 0);
  assert.equal(computeBuildCompleteness({ ...base, tier: "T4", level: 80 }), 25);
  assert.equal(
    computeBuildCompleteness({ tier: "Transcendent", level: 80, uniform: "u", ctp: "c", artifact: "a", uru_slots_total: 20, uru_slots_filled: 20, iso8_set: "i", team_supports: "t" }),
    100,
  );
  assert.equal(computeBuildCompleteness({ ...base, uru_slots_total: 0, uru_slots_filled: 0 }), 0);
});

test("build buckets", () => {
  assert.ok(buildBucketMatches(100, "100"));
  assert.ok(buildBucketMatches(80, "80-99"));
  assert.ok(!buildBucketMatches(100, "80-99"));
  assert.ok(buildBucketMatches(49, "under-50"));
  assert.ok(buildBucketMatches(0, "all"));
});

const chars = normalizeCharacters([
  { id: 1, name: "Thor", tier: "T3", priority: "medium", status: "building", build_completeness: 50, roles: ["ABX"], team: "Asgard" },
  { id: 2, name: "Hulk", tier: "T4", priority: "high", status: "built", build_completeness: 90, roles: ["ABX", "PvP"] },
  { id: 3, name: "Ant-Man", tier: "T4", priority: "high", status: "built", build_completeness: 40, roles: null },
]);

test("normalize fills defaults", () => {
  assert.equal(chars[0].team_supports, "Asgard");
  assert.equal(chars[0].uru_slots_total, 20);
  assert.deepEqual(chars[2].roles, []);
});

const all = { tier: "all", priority: "all", status: "all", roles: [], build: "all", sort: "default" };

test("default sort: priority, lowest build, name", () => {
  assert.deepEqual(filterAndSortCharacters(chars, all).map((c) => c.id), [3, 2, 1]);
  assert.deepEqual(filterAndSortCharacters(chars, { ...all, sort: "build_desc" }).map((c) => c.id), [2, 1, 3]);
  assert.deepEqual(filterAndSortCharacters(chars, { ...all, sort: "build_asc" }).map((c) => c.id), [3, 1, 2]);
  assert.deepEqual(filterAndSortCharacters(chars, { ...all, sort: "tier" }).map((c) => c.id), [3, 2, 1]);
});

test("filters: all selected roles required", () => {
  assert.deepEqual(filterAndSortCharacters(chars, { ...all, roles: ["ABX", "PvP"] }).map((c) => c.id), [2]);
  assert.deepEqual(filterAndSortCharacters(chars, { ...all, tier: "T3" }).map((c) => c.id), [1]);
  assert.deepEqual(filterAndSortCharacters(chars, { ...all, build: "under-50" }).map((c) => c.id), [3]);
});

test("validation keeps original rules", () => {
  assert.deepEqual(Object.keys(validateCharacterForm(emptyCharacterForm())), ["name"]);
  const errs = validateCharacterForm({ ...emptyCharacterForm(), name: "X", level: "0", uruSlotsFilled: "21" });
  assert.ok(errs.level);
  assert.ok(errs.uruSlotsFilled);
});

test("payload shape is unchanged", () => {
  const p = characterPayload({
    ...emptyCharacterForm(),
    name: " Black Bolt ",
    tier: "T4",
    roles: ["ABX", "PvP"],
    teamSupports: " White Fox ",
    uruSlotsFilled: "5",
  });
  assert.deepEqual(p, {
    name: "Black Bolt",
    tier: "T4",
    level: 80,
    uniform: "",
    ctp: "",
    artifact: "",
    priority: "medium",
    status: "planned",
    notes: "",
    role: "ABX · PvP",
    team: "White Fox",
    uru_state: "5/20",
    iso8_set: "",
    build_completeness: 38,
    roles: ["ABX", "PvP"],
    team_supports: "White Fox",
    uru_slots_total: 20,
    uru_slots_filled: 5,
    odin_blessings_count: 0,
  });
});
