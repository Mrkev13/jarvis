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
  assert.equal(memoryCategoryLabel("vlastní"), "Vlastní"); // 4B.1: neznámá kategorie s velkým písmenem (lib/labels)
  assert.deepEqual(distinctSorted(["work", "finance", "work", "", null, "škola"]), ["finance", "škola", "work"]);
});

// MRK-117: druh a platnost vzpomínky.
test("kind and validity", async () => {
  const m = await import("./memory.ts");
  const now = new Date("2026-11-23T10:00:00Z");
  assert.equal(m.memoryKindLabel("temporary"), "Dočasná");
  assert.equal(m.memoryKindLabel(null), "Fakt");
  const fmt = (d) => d.toISOString().slice(0, 16);
  assert.deepEqual(m.memoryValidity("2026-11-29T22:59:00", now, fmt), { expired: false, label: "Platí do 2026-11-29T22:59" });
  assert.deepEqual(m.memoryValidity("2026-11-20T10:00:00", now, fmt), { expired: true, label: "Vypršela 2026-11-20T10:00" });
  assert.deepEqual(m.memoryValidity(null, now), { expired: false, label: null });
  assert.equal(m.matchesValidity("2026-11-20T10:00:00", "expired", now), true);
  assert.equal(m.matchesValidity(null, "expired", now), false);
  assert.equal(m.matchesValidity(null, "valid", now), true);
});

test("draft validation and payload", async () => {
  const m = await import("./memory.ts");
  const now = new Date("2026-11-23T10:00:00Z");
  const base = { area: "", category: "", content: "Nemocný", importance: 5, active: true };
  assert.match(m.validateMemoryDraft({ ...base, kind: "temporary" }, now), /platnosti/);
  assert.match(m.validateMemoryDraft({ ...base, kind: "temporary", expiresLocal: "2026-11-20T10:00" }, now), /budoucnosti/);
  assert.equal(m.validateMemoryDraft({ ...base, kind: "temporary", expiresLocal: "2026-11-29T23:59" }, now), null);
  const body = m.memoryPayload({ ...base, kind: "temporary", expiresLocal: "2026-11-29T23:59" });
  assert.equal(body.kind, "temporary");
  assert.match(body.expires_at, /^2026-11-29T\d\d:59:00\.000Z$/);
  assert.equal("kind" in m.memoryPayload(base), false, "úprava neposílá druh");
});
