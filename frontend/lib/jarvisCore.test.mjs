import test from "node:test";
import assert from "node:assert/strict";
import { coreLine, coreMood, coreSegments, things } from "./jarvisCore.ts";

// MRK-132: Jarvis jádro dne – segmenty a věta jen z /today summary (žádné AI).
const S = (o = {}) => ({ remaining: 0, done: 0, attention: 0, next: null, ...o });
const NEXT = { id: "reminder:1", type: "reminder", title: "Fyzioterapie", subtitle: "", area: null, date: null, time: "18:30",
  status: "upcoming", priority: null, severity: null, href: null, actions: [], minutes_until: 240 };

test("segments: done lights up, long days are scaled to 12", () => {
  assert.deepEqual(coreSegments(2, 4), { total: 6, lit: 2 });
  assert.deepEqual(coreSegments(0, 0), { total: 0, lit: 0 });
  assert.deepEqual(coreSegments(30, 0), { total: 12, lit: 12 });
  assert.deepEqual(coreSegments(1, 29), { total: 12, lit: 0 });
  assert.deepEqual(coreSegments(29, 1), { total: 12, lit: 11 }, "nikdy plné, dokud něco zbývá");
});

test("czech plural of věc", () => {
  assert.deepEqual([1, 2, 4, 5, 0].map(things), ["věc", "věci", "věci", "věcí", "věcí"]);
});

test("one sentence about today", () => {
  assert.equal(coreLine(S({ attention: 3, remaining: 4, done: 2, next: NEXT })), "3 věci hoří. Další je Fyzioterapie v 18:30.");
  assert.equal(coreLine(S({ remaining: 1, next: { ...NEXT, minutes_until: 25 } })), "Další je Fyzioterapie v 18:30 (za 25 min).");
  assert.equal(coreLine(S({ remaining: 5 })), "Zbývá 5 věcí.");
  assert.equal(coreLine(S({ attention: 1 })), "1 věc hoří.");
  assert.equal(coreLine(S({ done: 4 })), "Na dnešek je všechno hotovo. Dobrá práce.");
  assert.equal(coreLine(S()), "Dnes nic naplánovaného – volno.");
  assert.deepEqual([coreMood(S({ attention: 1 })), coreMood(S({ done: 1 })), coreMood(S({ remaining: 1 }))], ["alert", "done", "calm"]);
});
