import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  COMPANION_BOX,
  COMPANION_PRIORITY,
  COMPANION_STATES,
  COMPANION_TIMING,
  RELOCATION_PAUSE_OFFSETS,
  WALK_EASING_POINTS,
  WALK_STEP_CYCLE_MS,
  anchorSamplePoints,
  chooseCompanionAnchor,
  companionAnchors,
  companionBubbleSide,
  companionLayout,
  companionVisible,
  createCompanion,
  measureOccupied,
  nextCompanionDeadline,
  parseCompanionPref,
  pickSafeAnchor,
  serializeCompanionPref,
  stepCompanion,
  walkEasingCss,
  walkPhase,
  walkPosition,
} from "./jarvisCompanion.ts";

const VIEWPORT = { width: 1366, height: 768, sidebar: 240 };
const anchorsFor = (vp = VIEWPORT, route = "default") => companionAnchors(vp, route);

/** Nový companion po prvním měření (nic pod kotvami). */
function fresh({ now = 0, roaming = true, enabled = true, route = "default", vp = VIEWPORT, occupied = [] } = {}) {
  const m = createCompanion({ now, anchors: anchorsFor(vp, route), enabled, roaming });
  return stepCompanion(m, { type: "occupancy", occupied, now });
}
const regularAnchors = (vp, route) => anchorsFor(vp, route).filter((a) => !a.peek);

/**
 * Tiká stroj po jeho vlastních termínech (tak to dělá komponenta – jeden časovač),
 * dokud se nezmění zobrazený stav.
 */
function advance(machine) {
  let m = machine;
  for (let i = 0; i < 10; i += 1) {
    const at = nextCompanionDeadline(m);
    assert.ok(Number.isFinite(at), "machine should have a deadline");
    m = stepCompanion(m, { type: "tick", now: at });
    if (m.state !== machine.state) return m;
  }
  assert.fail("state never changed");
}

test("states and priorities follow the brief: error/warning > success > listening/thinking > walking > idle", () => {
  assert.deepEqual(COMPANION_STATES, ["hidden", "idle", "walking", "listening", "thinking", "success", "warning", "error"]);
  const p = COMPANION_PRIORITY;
  assert.ok(p.error > p.success && p.warning > p.success);
  assert.ok(p.success > p.listening && p.success > p.thinking);
  assert.equal(p.listening, p.thinking);
  assert.ok(p.thinking > p.walking && p.walking > p.idle && p.idle > p.hidden);
});

test("anchors stay inside the viewport and right of the sidebar", () => {
  for (const vp of [VIEWPORT, { width: 1024, height: 700, sidebar: 240 }, { width: 2560, height: 1440, sidebar: 240 }]) {
    const anchors = regularAnchors(vp);
    assert.deepEqual(anchorsFor(vp).map((a) => a.id), ["left", "left-mid", "center", "right-mid", "right", "edge"]);
    const edge = anchorsFor(vp).find((a) => a.peek);
    assert.equal(edge.x + edge.width, vp.width, "edge peek stays flush with the right edge");
    for (const a of anchors) {
      assert.ok(a.x >= vp.sidebar, `${a.id} must not cover the sidebar`);
      assert.ok(a.x + COMPANION_BOX.width <= vp.width, `${a.id} must fit horizontally`);
      assert.ok(a.y >= 0 && a.y + COMPANION_BOX.height <= vp.height, `${a.id} must fit vertically`);
    }
    for (let i = 1; i < anchors.length; i += 1) assert.ok(anchors[i - 1].x < anchors[i].x);
  }
});

test("AI route has a single docked anchor in the conversation column; tiny viewports have none", () => {
  const ai = anchorsFor(VIEWPORT, "ai");
  assert.deepEqual(ai.map((a) => a.id), ["ai"]);
  assert.ok(ai[0].x >= VIEWPORT.sidebar && ai[0].x + COMPANION_BOX.width <= VIEWPORT.sidebar + 288);
  assert.deepEqual(anchorsFor({ width: 390, height: 844, sidebar: 0 }), []);
  assert.deepEqual(anchorsFor({ width: 1023, height: 700, sidebar: 240 }), []);
});

test("companion is visible only on wide desktop and when the preference is on", () => {
  assert.equal(companionVisible({ width: 1366, enabled: true }), true);
  assert.equal(companionVisible({ width: 1024, enabled: true }), true);
  assert.equal(companionVisible({ width: 1023, enabled: true }), false);
  assert.equal(companionVisible({ width: 390, enabled: true }), false);
  assert.equal(companionVisible({ width: 1366, enabled: false }), false);
});

test("preference parsing: default on, explicit off, garbage → on", () => {
  assert.equal(parseCompanionPref(null), true);
  assert.equal(parseCompanionPref("off"), false);
  assert.equal(parseCompanionPref("on"), true);
  assert.equal(parseCompanionPref("{broken"), true);
  assert.equal(serializeCompanionPref(false), "off");
  assert.equal(serializeCompanionPref(true), "on");
});

test("starts idle at the right anchor; disabled companion is hidden", () => {
  const m = fresh();
  assert.equal(m.state, "idle");
  assert.equal(m.anchor, "right");
  assert.equal(m.x, anchorsFor().find((a) => a.id === "right").x);
  assert.equal(fresh({ enabled: false }).state, "hidden");
  const off = stepCompanion(m, { type: "enabled", value: false, now: 10 });
  assert.equal(off.state, "hidden");
  assert.equal(nextCompanionDeadline(off), Infinity, "hidden companion schedules nothing");
});

test("idle relocation: short hops to the neighbouring anchor, ping-pong across the lane", () => {
  let m = fresh();
  assert.equal(nextCompanionDeadline(m), COMPANION_TIMING.relocateEveryMs + RELOCATION_PAUSE_OFFSETS[0]);
  const lane = regularAnchors();
  const visited = [];
  for (let i = 0; i < 8; i += 1) {
    m = advance(m); // čas na přesun
    assert.equal(m.state, "walking");
    const from = lane.findIndex((a) => a.x === m.walk.from);
    const to = lane.findIndex((a) => a.id === m.walk.target);
    assert.equal(Math.abs(to - from), 1, "always the neighbouring anchor – no long glide across the screen");
    assert.equal(m.facing, m.walk.to > m.walk.from ? "right" : "left");
    assert.ok(m.walk.travelMs >= COMPANION_TIMING.minTravelMs && m.walk.travelMs <= COMPANION_TIMING.maxTravelMs);
    m = advance(m); // dojde
    assert.equal(m.state, "idle");
    assert.equal(m.walk, null);
    assert.equal(m.x, lane.find((a) => a.id === m.anchor).x);
    visited.push(m.anchor);
  }
  assert.deepEqual(visited, ["right-mid", "center", "left-mid", "left", "left-mid", "center", "right-mid", "right"]);
});

test("relocation pauses alternate deterministically between ~39 and ~53 s (alive, never constant)", () => {
  const pauses = RELOCATION_PAUSE_OFFSETS.map((o) => COMPANION_TIMING.relocateEveryMs + o);
  assert.ok(Math.min(...pauses) >= 35_000 && Math.max(...pauses) <= 60_000);
  assert.ok(new Set(pauses).size > 1);
});

test("walk timing: depart (turn) → eased travel → arrival settle; speed matches the step cycle", () => {
  const m = advance(fresh());
  const w = m.walk;
  assert.equal(w.departMs, COMPANION_TIMING.departMs);
  assert.equal(w.settleMs, COMPANION_TIMING.settleMs);
  assert.equal(w.duration, w.departMs + w.travelMs + w.settleMs);
  assert.equal(m.walkPhase, "depart");
  assert.equal(walkPhase(w, w.start + w.departMs - 1), "depart");
  assert.equal(walkPhase(w, w.start + w.departMs), "travel");
  assert.equal(walkPhase(w, w.start + w.departMs + w.travelMs), "arrive");
  // během otočení stojí na místě, při doběhnutí už stojí na kotvě
  assert.equal(walkPosition(w, w.start + w.departMs - 1), w.from);
  assert.equal(walkPosition(w, w.start + w.departMs + w.travelMs), w.to);
  // rozjezd a dojezd: první a poslední desetina cesty urazí méně než prostřední desetina
  const at = (t) => walkPosition(w, w.start + w.departMs + w.travelMs * t);
  const d = (a, b) => Math.abs(at(b) - at(a));
  assert.ok(d(0, 0.1) < d(0.45, 0.55) && d(0.9, 1) < d(0.45, 0.55), "accelerates and decelerates – no constant glide");
  // ustálená rychlost = délka kroku × 2 / krokový cyklus (nohy neklouzají)
  const cruise = d(0.4, 0.6) / (0.2 * w.travelMs / 1000);
  const stepSpeed = (2 * COMPANION_TIMING.stridePx) / (WALK_STEP_CYCLE_MS / 1000);
  assert.ok(Math.abs(cruise - stepSpeed) / stepSpeed < 0.06, `${cruise} vs ${stepSpeed}`);
});

test("CSS easing and JS position use the very same curve", () => {
  assert.equal(WALK_EASING_POINTS[0], 0);
  assert.equal(WALK_EASING_POINTS.at(-1), 1);
  for (let i = 1; i < WALK_EASING_POINTS.length; i += 1) assert.ok(WALK_EASING_POINTS[i] > WALK_EASING_POINTS[i - 1]);
  assert.equal(walkEasingCss(), `linear(${WALK_EASING_POINTS.join(", ")})`);
  const w = { from: 0, to: 1000, target: "center", start: 0, departMs: 0, travelMs: 2400, settleMs: 0, duration: 2400 };
  WALK_EASING_POINTS.forEach((p, i) => assert.equal(walkPosition(w, (2400 * i) / (WALK_EASING_POINTS.length - 1)), Math.round(p * 1000)));
});

test("machine ticks on every walk phase boundary (one timer, no extra timers)", () => {
  let m = advance(fresh());
  const w = m.walk;
  assert.equal(nextCompanionDeadline(m), w.start + w.departMs);
  m = stepCompanion(m, { type: "tick", now: w.start + w.departMs });
  assert.equal(m.walkPhase, "travel");
  assert.equal(nextCompanionDeadline(m), w.start + w.departMs + w.travelMs);
  m = stepCompanion(m, { type: "tick", now: w.start + w.departMs + w.travelMs });
  assert.equal(m.walkPhase, "arrive");
  assert.equal(m.state, "walking");
  m = stepCompanion(m, { type: "tick", now: w.start + w.duration });
  assert.equal(m.state, "idle");
  assert.equal(m.walkPhase, null);
});

test("interruption during the turn keeps him in place; resuming starts with a fresh turn", () => {
  let m = advance(fresh());
  const w = m.walk;
  m = stepCompanion(m, { type: "mood", mood: "listening", now: w.start + 100 });
  assert.equal(m.state, "listening");
  assert.equal(m.x, w.from, "no slide while he was still turning");
  m = stepCompanion(m, { type: "mood", mood: "idle", now: w.start + 5000 });
  assert.equal(m.state, "walking");
  assert.equal(m.walkPhase, "depart");
  assert.equal(m.walk.target, w.target);
});

test("stroll starts the next neighbour hop right away", () => {
  const m = stepCompanion(fresh(), { type: "stroll", now: 50 });
  assert.equal(m.state, "walking");
  assert.equal(m.walk.target, "right-mid");
});

test("a high-priority event interrupts walking, then the walk resumes to its anchor", () => {
  let m = advance(fresh()); // walking right → right-mid
  const { walk } = m;
  const mid = walk.start + walk.duration / 2;
  m = stepCompanion(m, { type: "pulse", kind: "error", now: mid });
  assert.equal(m.state, "error");
  assert.equal(m.walk, null);
  assert.equal(m.x, walkPosition(walk, mid), "stops where it is, no teleport");
  assert.equal(m.pendingTarget, "right-mid");
  m = advance(m); // chyba odezní
  assert.equal(m.state, "walking");
  assert.equal(m.walkPhase, "depart", "resumes with a turn, not a jump-start");
  assert.equal(m.walk.target, "right-mid");
  assert.equal(m.walk.from, walkPosition(walk, mid));
  m = advance(m);
  assert.equal(m.state, "idle");
  assert.equal(m.anchor, "right-mid");
});

test("sustained moods: thinking/listening/warning hold until the source clears", () => {
  let m = fresh();
  m = stepCompanion(m, { type: "mood", mood: "thinking", now: 5 });
  assert.equal(m.state, "thinking");
  m = stepCompanion(m, { type: "tick", now: COMPANION_TIMING.relocateEveryMs * 3 });
  assert.equal(m.state, "thinking", "never relocates while busy");
  m = stepCompanion(m, { type: "mood", mood: "listening", now: COMPANION_TIMING.relocateEveryMs * 3 + 1 });
  assert.equal(m.state, "listening");
  m = stepCompanion(m, { type: "mood", mood: "warning", now: COMPANION_TIMING.relocateEveryMs * 3 + 2 });
  assert.equal(m.state, "warning");
  m = stepCompanion(m, { type: "mood", mood: "idle", now: COMPANION_TIMING.relocateEveryMs * 3 + 3 });
  assert.equal(m.state, "idle");
});

test("success is a short celebration, then idle; error settles too", () => {
  let m = stepCompanion(fresh(), { type: "pulse", kind: "success", now: 100 });
  assert.equal(m.state, "success");
  m = stepCompanion(m, { type: "tick", now: 100 + COMPANION_TIMING.successMs - 1 });
  assert.equal(m.state, "success");
  m = stepCompanion(m, { type: "tick", now: 100 + COMPANION_TIMING.successMs });
  assert.equal(m.state, "idle");

  m = stepCompanion(m, { type: "pulse", kind: "error", now: 10_000 });
  assert.equal(m.state, "error");
  m = stepCompanion(m, { type: "tick", now: 10_000 + COMPANION_TIMING.errorMs });
  assert.equal(m.state, "idle");
});

test("priority: error beats thinking; success does not override a pending warning", () => {
  let m = stepCompanion(fresh(), { type: "mood", mood: "thinking", now: 1 });
  m = stepCompanion(m, { type: "pulse", kind: "error", now: 2 });
  assert.equal(m.state, "error");
  m = stepCompanion(m, { type: "tick", now: 2 + COMPANION_TIMING.errorMs });
  assert.equal(m.state, "thinking", "falls back to the still-active mood");

  let w = stepCompanion(fresh(), { type: "mood", mood: "warning", now: 1 });
  w = stepCompanion(w, { type: "pulse", kind: "success", now: 2 });
  assert.equal(w.state, "warning");
  w = stepCompanion(w, { type: "mood", mood: "idle", now: 3 });
  assert.equal(w.state, "success", "confirmed action: the celebration plays once the warning clears");
});

test("reduced motion: no roaming, fixed right anchor, expressions still change", () => {
  let m = fresh({ roaming: false });
  assert.equal(m.anchor, "right");
  assert.equal(nextCompanionDeadline(m), Infinity, "no relocation timer");
  m = stepCompanion(m, { type: "tick", now: COMPANION_TIMING.relocateEveryMs * 10 });
  assert.equal(m.state, "idle");
  assert.equal(m.anchor, "right");
  m = stepCompanion(m, { type: "mood", mood: "thinking", now: 1 });
  assert.equal(m.state, "thinking");

  // přepnutí na reduced motion uprostřed chůze → okamžitě na pevnou kotvu, žádná chůze
  let walking = advance(fresh());
  walking = stepCompanion(walking, { type: "roaming", value: false, now: walking.walk.start + 10 });
  assert.equal(walking.state, "idle");
  assert.equal(walking.walk, null);
  assert.equal(walking.anchor, "right");
  assert.equal(walking.pendingTarget, null);
});

test("goto (avoiding a focused control) walks, or snaps under reduced motion", () => {
  let m = stepCompanion(fresh(), { type: "goto", target: "left", now: 50 });
  assert.equal(m.state, "walking");
  assert.equal(m.walk.target, "left");
  let r = stepCompanion(fresh({ roaming: false }), { type: "goto", target: "left", now: 50 });
  assert.equal(r.state, "idle");
  assert.equal(r.anchor, "left");
  assert.equal(r.x, anchorsFor().find((a) => a.id === "left").x);
});

test("avoidance during a reaction steps aside immediately; reduced-motion resize keeps the avoided anchor", () => {
  let m = stepCompanion(fresh(), { type: "mood", mood: "warning", now: 1 });
  m = stepCompanion(m, { type: "goto", target: "center", now: 2 });
  assert.equal(m.state, "warning");
  assert.equal(m.anchor, "center");
  assert.equal(m.x, anchorsFor().find((a) => a.id === "center").x);
  assert.equal(m.pendingTarget, null);

  let r = stepCompanion(fresh({ roaming: false }), { type: "goto", target: "left", now: 5 });
  r = stepCompanion(r, { type: "layout", anchors: anchorsFor({ width: 1300, height: 760, sidebar: 240 }), now: 6 });
  assert.equal(r.anchor, "left");
});

test("layout change re-clamps to the new anchors (viewport bounds)", () => {
  let m = advance(fresh());
  const small = { width: 1100, height: 700, sidebar: 240 };
  m = stepCompanion(m, { type: "layout", anchors: anchorsFor(small), now: m.walk.start + 1 });
  assert.equal(m.walk, null);
  const target = anchorsFor(small).find((a) => a.id === m.anchor);
  assert.ok(target, "anchor exists in the new layout");
  assert.equal(m.x, target.x);
  assert.ok(m.x + COMPANION_BOX.width <= small.width);

  let ai = stepCompanion(fresh(), { type: "layout", anchors: anchorsFor(VIEWPORT, "ai"), now: 5 });
  assert.equal(ai.anchor, "ai");
  assert.equal(nextCompanionDeadline(ai), 5 + COMPANION_TIMING.recheckAfterLayoutMs, "only the one-off recheck");
  ai = stepCompanion(ai, { type: "occupancy", occupied: [], now: 6 });
  ai = stepCompanion(ai, { type: "tick", now: 5 + COMPANION_TIMING.recheckAfterLayoutMs });
  assert.equal(nextCompanionDeadline(ai), Infinity, "single anchor → no relocation");

  const gone = stepCompanion(fresh(), { type: "layout", anchors: [], now: 5 });
  assert.equal(gone.state, "hidden");
});

test("bubbles are short, deterministic, auto-hide and are rate-limited", () => {
  let m = stepCompanion(fresh(), { type: "pulse", kind: "success", now: 0 });
  assert.equal(m.bubble.text, "Hotovo!");
  assert.equal(m.bubble.until, COMPANION_TIMING.bubbleMs);
  m = stepCompanion(m, { type: "tick", now: COMPANION_TIMING.bubbleMs });
  assert.equal(m.bubble, null);
  m = stepCompanion(m, { type: "tick", now: COMPANION_TIMING.successMs });
  m = stepCompanion(m, { type: "pulse", kind: "success", now: COMPANION_TIMING.successMs + 10 });
  assert.equal(m.state, "success");
  assert.equal(m.bubble, null, "same bubble within the cooldown is not repeated");
  m = stepCompanion(m, { type: "tick", now: COMPANION_TIMING.bubbleCooldownMs + 5000 });
  m = stepCompanion(m, { type: "pulse", kind: "success", now: COMPANION_TIMING.bubbleCooldownMs + 6000 });
  assert.equal(m.bubble.text, "Hotovo!");
  for (const text of ["Poslouchám…", "Moment, přemýšlím…", "Čekám na tvoje potvrzení.", "Tohle se nepovedlo."]) {
    assert.ok(text.length <= 32);
  }
  assert.equal(stepCompanion(fresh(), { type: "mood", mood: "warning", now: 1 }).bubble.text, "Čekám na tvoje potvrzení.");
  const walking = advance(fresh());
  assert.equal(walking.bubble, null, "walking and idle stay quiet");
});

test("bubble opens toward the inside of the screen", () => {
  assert.equal(companionBubbleSide(1200, 1366), "left");
  assert.equal(companionBubbleSide(300, 1366), "right");
});

test("pickSafeAnchor moves away from a focused control that overlaps the companion", () => {
  const anchors = regularAnchors();
  const right = anchors.find((a) => a.id === "right");
  const control = { left: right.x - 10, right: right.x + 40, top: right.y + 5, bottom: right.y + 30 };
  assert.equal(pickSafeAnchor(anchors, "right", control), "right-mid");
  const far = { left: 0, right: 100, top: 0, bottom: 40 };
  assert.equal(pickSafeAnchor(anchors, "right", far), null, "no overlap → stay");
  const everywhere = { left: 0, right: 5000, top: 0, bottom: 5000 };
  assert.equal(pickSafeAnchor(anchors, "right", everywhere), null, "nowhere safe → stay put");
});

// ---------- obsazené kotvy (MRK-16 UX) ----------

test("occupied bottom-right anchor → walks to the nearest free anchor", () => {
  let m = fresh();
  assert.equal(m.anchor, "right");
  m = stepCompanion(m, { type: "occupancy", occupied: ["right"], now: 10 });
  assert.equal(m.state, "walking", "visible and calm → walks away, no teleport");
  assert.equal(m.walk.target, "right-mid");
  assert.equal(m.parked, false);
});

test("occupied anchor while not yet visible (first measure) → placed directly on a free one", () => {
  const created = createCompanion({ now: 0, anchors: anchorsFor(), enabled: true, roaming: true });
  assert.equal(created.measured, false, "starts unmeasured (rendered transparent)");
  const m = stepCompanion(created, { type: "occupancy", occupied: ["right", "right-mid"], now: 1 });
  assert.equal(m.state, "idle");
  assert.equal(m.anchor, "center");
  assert.equal(m.measured, true);
});

test("all regular anchors occupied → peeks from the right edge; everything occupied → hides", () => {
  let m = stepCompanion(fresh(), { type: "scroll", now: 5 });
  m = stepCompanion(m, { type: "tick", now: 5 + COMPANION_TIMING.scrollSettleMs });
  m = stepCompanion(m, { type: "occupancy", occupied: ["left", "left-mid", "center", "right-mid", "right"], now: 300 });
  assert.equal(m.anchor, "edge");
  assert.equal(m.state, "idle");
  assert.equal(m.x, anchorsFor().find((a) => a.id === "edge").x);
  assert.equal(nextCompanionDeadline(m), m.checkAt ?? Infinity, "never relocates out of the peek on its own");

  m = stepCompanion(m, { type: "occupancy", occupied: [...["left", "left-mid", "center", "right-mid", "right"], "edge"], now: 400 });
  assert.equal(m.state, "hidden");
  assert.equal(m.parked, true);
  m = stepCompanion(m, { type: "pulse", kind: "success", now: 410 });
  assert.equal(m.state, "hidden", "parked companion does not pop out over content");

  m = stepCompanion(m, { type: "occupancy", occupied: ["left"], now: 500 });
  assert.equal(m.parked, false);
  assert.ok(m.anchor !== "left" && m.anchor !== "edge", "comes back to a free regular anchor");
});

test("scrolling hides him (transparent), stops the walk, then re-measures once settled", () => {
  let m = advance(fresh()); // walking right → right-mid
  const t = m.walk.start + 1000;
  const before = m.measureRequest;
  m = stepCompanion(m, { type: "scroll", now: t });
  assert.equal(m.measured, false);
  assert.equal(m.walk, null);
  assert.equal(m.scrollUntil, t + COMPANION_TIMING.scrollSettleMs);
  m = stepCompanion(m, { type: "scroll", now: t + 100 });
  assert.equal(m.measureRequest, before, "no measuring while still scrolling");
  assert.equal(nextCompanionDeadline(m), t + 100 + COMPANION_TIMING.scrollSettleMs);
  m = stepCompanion(m, { type: "tick", now: t + 100 + COMPANION_TIMING.scrollSettleMs });
  assert.equal(m.measureRequest, before + 1, "settled → one measurement");
  m = stepCompanion(m, { type: "occupancy", occupied: ["right-mid"], now: t + 400 });
  assert.equal(m.measured, true);
  assert.equal(m.walk, null, "repositioned while invisible – no walk across content");
  assert.notEqual(m.anchor, "right-mid");
  assert.equal(m.x, anchorsFor().find((a) => a.id === m.anchor).x, "stands exactly on an anchor, not mid-way");
});

test("relocation never targets an occupied anchor (turns back instead)", () => {
  let m = fresh({ occupied: ["right-mid"] });
  m = stepCompanion(m, { type: "tick", now: nextCompanionDeadline(m) });
  assert.equal(m.state, "idle", "the only neighbour is occupied → stays");
  let c = stepCompanion(fresh(), { type: "goto", target: "center", now: 1 });
  c = stepCompanion(c, { type: "tick", now: c.walk.start + c.walk.duration });
  c = stepCompanion(c, { type: "occupancy", occupied: ["left-mid"], now: c.walk?.start ?? 2 });
  c = stepCompanion(c, { type: "stroll", now: 100_000 });
  assert.equal(c.walk.target, "right-mid", "left neighbour occupied → turns around");
});

test("reduced motion: occupied fixed anchor → nearest free one, never walking", () => {
  let m = fresh({ roaming: false, occupied: ["right"] });
  assert.equal(m.state, "idle");
  assert.equal(m.walk, null);
  assert.equal(m.anchor, "right-mid");
  m = stepCompanion(m, { type: "occupancy", occupied: ["right-mid", "right"], now: 50 });
  assert.equal(m.walk, null);
  assert.equal(m.anchor, "center");
  m = stepCompanion(m, { type: "stroll", now: 55 });
  assert.equal(m.walk, null, "no strolling under reduced motion");
  m = stepCompanion(m, { type: "mood", mood: "thinking", now: 60 });
  assert.equal(m.state, "thinking", "expressions still change");
});

test("/ai dock is reserved: it is never measured as occupied", () => {
  const ai = anchorsFor(VIEWPORT, "ai");
  assert.deepEqual(measureOccupied(ai, () => true), []);
  const all = measureOccupied(anchorsFor(), (x) => x > 1200);
  assert.deepEqual(all, ["right", "edge"]);
});

test("sample points stay inside the visible part of the anchor", () => {
  for (const a of anchorsFor()) {
    for (const p of anchorSamplePoints(a)) {
      assert.ok(p.x > a.x && p.x < a.x + a.width && p.y > a.y && p.y < a.y + COMPANION_BOX.height);
    }
  }
});

test("chooseCompanionAnchor keeps a free current anchor and prefers regular anchors over the edge", () => {
  const anchors = anchorsFor();
  assert.equal(chooseCompanionAnchor(anchors, [], "right", 1278), "right");
  assert.equal(chooseCompanionAnchor(anchors, ["right"], "right", 1278), "right-mid");
  assert.equal(chooseCompanionAnchor(anchors, ["left", "left-mid", "center", "right-mid", "right"], "right", 1278), "edge");
  assert.equal(chooseCompanionAnchor(anchors, [...["left", "left-mid", "center", "right-mid", "right"], "edge"], "right", 1278), null);
});

test("companionLayout derives the dock mode from the route", () => {
  assert.equal(companionLayout("/"), "default");
  assert.equal(companionLayout("/wot"), "default");
  assert.equal(companionLayout("/ai"), "ai");
  assert.equal(companionLayout(null), "default");
});

test("character motion is isolated under jarvis-* and never reuses semantic motion classes", () => {
  const css = readFileSync(new URL("../app/jarvis-companion.css", import.meta.url), "utf8");
  const keyframes = [...css.matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => m[1]);
  assert.ok(keyframes.length >= 5);
  for (const name of keyframes) assert.match(name, /^jarvis-/);
  const classes = [...css.matchAll(/\.([a-z][\w-]*)/g)].map((m) => m[1]);
  for (const name of classes) assert.ok(!name.startsWith("motion-"), `${name} must not touch MRK-6 motion classes`);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  const component = readFileSync(new URL("../components/jarvis/JarvisCompanion.tsx", import.meta.url), "utf8");
  const figure = readFileSync(new URL("../components/jarvis/JarvisFigure.tsx", import.meta.url), "utf8");
  for (const source of [component, figure]) {
    assert.doesNotMatch(source, /jarvisMotionClass|["'\s]motion-(executing|completion|warning|error)/);
    assert.doesNotMatch(source, /setInterval/);
  }
  const timers = component.match(/setTimeout\(/g) ?? [];
  assert.equal(timers.length, 1, "one centralized timer drives the machine");
});
