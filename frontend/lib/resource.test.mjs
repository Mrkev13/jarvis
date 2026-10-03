// Roadmap 4A: useApiResource – loading od začátku, refresh bez blikání, zastaralé odpovědi se zahodí.
import assert from "node:assert/strict";
import { test } from "node:test";

import { initialResource, resourceReducer } from "./resource.ts";

test("starts in loading, idle when disabled", () => {
  assert.equal(initialResource().status, "loading");
  assert.equal(initialResource(false).status, "idle");
});

test("first load → success; refresh keeps data and sets refreshing", () => {
  let s = resourceReducer(initialResource(), { type: "start", id: 1 });
  assert.equal(s.status, "loading");
  s = resourceReducer(s, { type: "success", id: 1, data: [1] });
  assert.deepEqual([s.status, s.data, s.refreshing], ["success", [1], false]);
  s = resourceReducer(s, { type: "start", id: 2 });
  assert.deepEqual([s.status, s.data, s.refreshing], ["success", [1], true]);
});

test("stale responses are ignored (out-of-order search results)", () => {
  let s = resourceReducer(initialResource(), { type: "start", id: 1 });
  s = resourceReducer(s, { type: "start", id: 2 });
  s = resourceReducer(s, { type: "success", id: 2, data: "new" });
  s = resourceReducer(s, { type: "success", id: 1, data: "old" });
  assert.equal(s.data, "new");
  s = resourceReducer(s, { type: "error", id: 1, error: "late failure" });
  assert.equal(s.error, null);
});

test("errors: first load shows error state; failed refresh keeps the last data", () => {
  let s = resourceReducer(initialResource(), { type: "start", id: 1 });
  s = resourceReducer(s, { type: "error", id: 1, error: "HTTP 500" });
  assert.deepEqual([s.status, s.error], ["error", "HTTP 500"]);
  s = resourceReducer(s, { type: "start", id: 2 });
  s = resourceReducer(s, { type: "success", id: 2, data: { a: 1 } });
  s = resourceReducer(s, { type: "start", id: 3 });
  s = resourceReducer(s, { type: "error", id: 3, error: "síť" });
  assert.deepEqual([s.status, s.data, s.error, s.refreshing], ["success", { a: 1 }, "síť", false]);
});

test("local set replaces data (optimistic update after an action)", () => {
  const s = resourceReducer(initialResource(), { type: "set", data: 5 });
  assert.deepEqual([s.status, s.data], ["success", 5]);
});
