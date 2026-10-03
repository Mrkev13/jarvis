import assert from "node:assert/strict";
import { test } from "node:test";

import {
  activeXpRemaining,
  emptyGrindDraft,
  grindBody,
  grindStatusMeta,
  resourceEntries,
} from "./wot.ts";

test("resourceEntries posílá jen vyplněné měny v pevném pořadí", () => {
  assert.deepEqual(resourceEntries({ gold: 12500, credits: 8450000, free_xp: undefined }), [
    { resource: "credits", amount: 8450000 },
    { resource: "gold", amount: 12500 },
  ]);
  assert.deepEqual(resourceEntries({}), []);
});

test("grindBody validuje a skládá stejné tělo jako dřív", () => {
  const empty = grindBody(emptyGrindDraft());
  assert.equal(empty.ok, false);
  assert.ok(!empty.ok && empty.errors.tank && empty.errors.xp_remaining);

  const res = grindBody({ tank: "  Kranvagn ", xp_remaining: "64000", priority: "high", status: "paused" });
  assert.deepEqual(res, {
    ok: true,
    body: { tank: "Kranvagn", xp_remaining: 64000, priority: "high", status: "paused" },
  });
  assert.equal(grindBody({ ...emptyGrindDraft(), tank: "T-100 LT", xp_remaining: "0" }).ok, true);
});

test("grindStatusMeta dává české popisky", () => {
  assert.deepEqual(grindStatusMeta("completed"), { tone: "success", label: "Dokončeno" });
  assert.deepEqual(grindStatusMeta("paused"), { tone: "neutral", label: "Pozastaveno" });
  assert.deepEqual(grindStatusMeta("active"), { tone: "accent", label: "Aktivní" });
  assert.equal(grindStatusMeta("weird").label, "weird");
});


test("activeXpRemaining sčítá jen aktivní grindy", () => {
  assert.equal(
    activeXpRemaining([
      { tank: "A", xp_remaining: 128000, priority: "high", status: "active" },
      { tank: "B", xp_remaining: 64000, priority: "medium", status: "active" },
      { tank: "C", xp_remaining: 5000, priority: "low", status: "paused" },
    ]),
    192000,
  );
});
