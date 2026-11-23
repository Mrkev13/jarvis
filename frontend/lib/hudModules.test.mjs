import test from "node:test";
import assert from "node:assert/strict";
import { financeCore, habitsCore, mffCore, remindersCore, untilLabel, workCore, wotCore, wowCore } from "./hudModules.ts";

// MRK-134: HUD jádra modulů – deterministicky z dat stránky.
test("habits", () => {
  assert.deepEqual(habitsCore({ total: 4, done: 1, skipped: 1, open: 2, week_done: 9, week_expected: 20 }),
    { total: 4, lit: 1, mood: "calm", line: "Dnes zbývá 2 návyky. Týden: 9/20." });
  assert.equal(habitsCore({ total: 2, done: 2, skipped: 0, open: 0, week_done: 0, week_expected: 0 }).mood, "done");
  assert.equal(habitsCore({ total: 0, done: 0, skipped: 0, open: 0, week_done: 0, week_expected: 0 }).line, "Na dnešek žádný návyk.");
});

test("work, finance, mff, wow", () => {
  assert.deepEqual(workCore(31.5, 9150, 15, 30), { total: 10, lit: 5, mood: "calm", line: "Tento měsíc 31,5 h · 9 150 Kč." });
  assert.equal(workCore(0, 0, 1, 30).line, "Tento měsíc zatím žádná práce.");
  assert.deepEqual(financeCore(21275, 4640), { total: 10, lit: 8, mood: "done", line: "Zůstává 78 % příjmů." });
  assert.equal(financeCore(100, 200).mood, "alert");
  assert.equal(financeCore(0, 0).line, "Zatím žádné pohyby.");
  assert.deepEqual(mffCore(3, 1), { total: 3, lit: 1, mood: "calm", line: "Plně postaveno 1 z 3 T4." });
  assert.equal(wowCore({ characters: 3, max_level: 60, with_target: 2, at_target: 1 }).line, "1 z 2 na cíli · nejvyšší level 60.");
  assert.equal(wowCore({ characters: 0, max_level: 0, with_target: 0, at_target: 0 }).total, 0);
});

test("wot target", () => {
  assert.deepEqual(wotCore({ tank: "Kranvagn", progress: 54, remaining: 44000 }),
    { total: 10, lit: 5, mood: "calm", line: "Zaměřeno: Kranvagn – 54 %. Zbývá 44 000 XP." });
  assert.equal(wotCore(null).lit, 0);
});

test("reminders countdown", () => {
  const now = Date.parse("2026-11-23T12:00:00Z");
  const items = [
    { title: "Fyzio", status: "scheduled", state: "scheduled", due_at: "2026-11-23T14:14:00Z" },
    { title: "Pozdější", status: "scheduled", state: "scheduled", due_at: "2026-11-24T14:14:00Z" },
  ];
  assert.deepEqual(remindersCore(items, now), { total: 12, lit: 9, mood: "calm", line: "Další za 2 h 14 min: Fyzio." });
  assert.equal(remindersCore([{ title: "x", status: "fired", state: "due", due_at: "2026-11-23T11:00:00Z" }], now).line,
    "1 věc čeká na vyřízení. Žádná další naplánovaná připomínka.");
  assert.deepEqual([0, 5, 60, 125, 60 * 72].map(untilLabel), ["teď", "za 5 min", "za 1 h", "za 2 h 5 min", "za 3 dny"]);
});

test("calendar now line", async () => {
  const { nowLineIndex, pragueNow } = await import("./hudModules.ts");
  assert.equal(nowLineIndex([10, 20, 30], 15), 1);
  assert.equal(nowLineIndex([10, 20, 30], 5), 0);
  assert.equal(nowLineIndex([10, 20, 30], 35), 3);
  assert.deepEqual(pragueNow(new Date("2026-11-23T17:42:00Z")), { date: "2026-11-23", time: "18:42" });
});
