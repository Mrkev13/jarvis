// MRK-126: mizení řádků – fokus na souseda, v omezeném pohybu bez čekání.
import assert from "node:assert/strict";
import { test } from "node:test";

import { exitDelay, neighborKey } from "./rowExit.ts";

test("neighbor is the next row, else the previous one", () => {
  assert.equal(neighborKey(["a", "b", "c"], "a"), "b");
  assert.equal(neighborKey(["a", "b", "c"], "b"), "c");
  assert.equal(neighborKey(["a", "b", "c"], "c"), "b");
});

test("no neighbor for a single or unknown row", () => {
  assert.equal(neighborKey(["a"], "a"), null);
  assert.equal(neighborKey([], "a"), null);
  assert.equal(neighborKey(["a", "b"], "x"), null);
});

test("reduced motion removes the row without waiting", () => {
  assert.equal(exitDelay(true, 220), 0);
  assert.equal(exitDelay(false, 220), 220);
});
