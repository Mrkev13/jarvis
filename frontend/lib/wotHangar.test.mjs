import test from "node:test";
import assert from "node:assert/strict";
import { armorPlates, medalRank, nationStyle, romanTier } from "./wotHangar.ts";

// MRK-138: WoT hangár – národ, tier, medaile, pancéřové pláty.
test("nation, tier and medals", () => {
  assert.equal(nationStyle("sweden").label, "Švédsko");
  assert.equal(nationStyle("GERMANY").label, "Německo");
  assert.equal(nationStyle("mars"), null);
  assert.equal(nationStyle(undefined), null);
  assert.deepEqual([1, 8, 10, 11, 0, 12, 7.5, undefined].map(romanTier), ["I", "VIII", "X", "XI", null, null, null, null]);
  assert.deepEqual([1, 2, 4, 5, 9].map(medalRank), ["bronze", "silver", "silver", "gold", "gold"]);
});

test("armor plates follow the grind progress", () => {
  assert.deepEqual(armorPlates(54), { total: 20, lit: 11 });
  assert.deepEqual(armorPlates(100), { total: 20, lit: 20 });
  assert.deepEqual(armorPlates(null), { total: 20, lit: 0 });
  assert.deepEqual(armorPlates(-5), { total: 20, lit: 0 });
});
