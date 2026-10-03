// Roadmap 4A: sémantika tónů a popisků (čeština, barvy jen s významem).
import assert from "node:assert/strict";
import { test } from "node:test";

import { BADGE_TONE, BAR_TONE, CARD_TONE, clampPercent, cx, priorityTone, progressTone, severityTone, TEXT_TONE, trendTone } from "./ui.ts";

test("every tone has badge, text, bar and card classes", () => {
  const tones = ["neutral", "accent", "ai", "success", "warning", "danger", "info"];
  for (const map of [BADGE_TONE, TEXT_TONE, BAR_TONE, CARD_TONE]) {
    assert.deepEqual(Object.keys(map).sort(), [...tones].sort());
  }
});

test("severity and priority map to Czech labels; only high priority is highlighted", () => {
  assert.deepEqual(severityTone("important"), { tone: "danger", label: "Důležité" });
  assert.deepEqual(severityTone("WARNING"), { tone: "warning", label: "Varování" });
  assert.deepEqual(severityTone(undefined), { tone: "info", label: "Info" });
  assert.deepEqual(priorityTone("high"), { tone: "warning", label: "Vysoká" });
  assert.equal(priorityTone("medium").tone, "neutral");
  assert.equal(priorityTone("low").label, "Nízká");
});

test("trend polarity comes from the backend", () => {
  assert.equal(trendTone("better"), "success");
  assert.equal(trendTone("worse"), "danger");
  assert.equal(trendTone("up"), "neutral");
});

test("progress clamps and only marks completion green", () => {
  assert.equal(clampPercent(142), 100);
  assert.equal(clampPercent("abc"), 0);
  assert.equal(progressTone(40), "accent");
  assert.equal(progressTone(100), "success");
  assert.equal(progressTone(40, "warning"), "warning");
});

test("cx joins only truthy classes", () => {
  assert.equal(cx("a", false, null, "b", undefined, ""), "a b");
});
