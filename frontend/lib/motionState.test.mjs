// Roadmap 6A: kdy se motion primitiva přehrají (completion, milník, streak) a progress bez layoutu.
import assert from "node:assert/strict";
import { test } from "node:test";

import { becameTrue, increased, progressFillOffset, stepSignal, STREAK_MILESTONES, streakVisual } from "./motionState.ts";

function run(values, trigger, { ready = true } = {}) {
  let state = { prev: values[0], ready: Array.isArray(ready) ? ready[0] : ready, signal: 0 };
  const signals = [];
  values.forEach((v, i) => {
    state = stepSignal(state, v, Array.isArray(ready) ? ready[i] : ready, trigger);
    signals.push(state.signal);
  });
  return signals;
}

test("completion fires only on incomplete → complete, never for already-complete data", () => {
  assert.deepEqual(run([true, true, true], becameTrue), [0, 0, 0], "načtení hotového neoslavuje");
  assert.deepEqual(run([false, true, true], becameTrue), [0, 1, 1]);
  assert.deepEqual(run([false, true, false, true], becameTrue), [0, 1, 1, 2], "znovu dokončeno → znovu");
});

test("completion waits for data: loading → loaded complete is not an event", () => {
  assert.deepEqual(run([false, true], becameTrue, { ready: [false, true] }), [0, 0]);
  assert.deepEqual(run([false, true, false, true], becameTrue, { ready: [false, true, true, true] }), [0, 0, 0, 1]);
});

test("unchanged input returns the same state object (no extra render)", () => {
  const state = { prev: 3, ready: true, signal: 2 };
  assert.equal(stepSignal(state, 3, true, increased), state);
});

test("streak bump: only increases count, not decreases or the first value", () => {
  assert.deepEqual(run([5, 6, 6, 7, 0, 1], increased), [0, 1, 1, 2, 2, 3]);
  assert.deepEqual(run([12], increased), [0]);
});

test("streak visual states and accessible labels", () => {
  assert.deepEqual(streakVisual(0), { state: "inactive", label: "Streak 0 dní" });
  assert.deepEqual(streakVisual(4, { broken: true }), { state: "inactive", label: "Streak přerušen" });
  assert.deepEqual(streakVisual(1), { state: "active", label: "Streak 1 den" });
  assert.deepEqual(streakVisual(3), { state: "active", label: "Streak 3 dny" });
  assert.deepEqual(streakVisual(5), { state: "active", label: "Streak 5 dní" });
  assert.deepEqual(streakVisual(7), { state: "milestone", label: "Streak 7 dní – milník" });
  assert.equal(streakVisual(10, { milestones: [10] }).state, "milestone");
  assert.equal(streakVisual(Number.NaN).state, "inactive");
  assert.equal(streakVisual(-3).state, "inactive");
  assert.ok(STREAK_MILESTONES.includes(30));
});

test("progress fill moves by transform offset, clamped 0–100", () => {
  assert.equal(progressFillOffset(42), "-58%");
  assert.equal(progressFillOffset(100), "0%");
  assert.equal(progressFillOffset(140), "0%");
  assert.equal(progressFillOffset(0), "-100%");
  assert.equal(progressFillOffset(-5), "-100%");
  assert.equal(progressFillOffset("abc"), "-100%");
});
