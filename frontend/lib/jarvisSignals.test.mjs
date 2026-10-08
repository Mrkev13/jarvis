import assert from "node:assert/strict";
import test from "node:test";

import {
  clearJarvisSource,
  combineJarvisMood,
  jarvisSourceEdge,
  publishJarvisSource,
  pulseJarvis,
  subscribeJarvisSignals,
} from "./jarvisSignals.ts";

test("combined mood takes the highest sustained state; success/error are not sustained", () => {
  assert.equal(combineJarvisMood([]), "idle");
  assert.equal(combineJarvisMood(["idle", "thinking"]), "thinking");
  assert.equal(combineJarvisMood(["listening", "warning", "thinking"]), "warning");
  assert.equal(combineJarvisMood(["success", "error"]), "idle");
});

test("edges: entering success/error emits one pulse, staying there does not", () => {
  assert.equal(jarvisSourceEdge(undefined, "success"), "success");
  assert.equal(jarvisSourceEdge("thinking", "success"), "success");
  assert.equal(jarvisSourceEdge("success", "success"), null);
  assert.equal(jarvisSourceEdge("thinking", "error"), "error");
  assert.equal(jarvisSourceEdge("error", "idle"), null);
});

test("store publishes mood changes and pulses to subscribers", () => {
  const events = [];
  const stop = subscribeJarvisSignals((e) => events.push(e));
  publishJarvisSource("ai", "thinking");
  publishJarvisSource("ai", "thinking"); // beze změny → nic
  publishJarvisSource("briefing", "idle");
  publishJarvisSource("ai", "success");
  pulseJarvis("success");
  clearJarvisSource("ai");
  stop();
  pulseJarvis("error"); // po odhlášení se nic nedoručí
  assert.deepEqual(events, [
    { type: "mood", mood: "thinking" },
    { type: "mood", mood: "idle" },
    { type: "pulse", kind: "success" },
    { type: "pulse", kind: "success" },
  ]);
  clearJarvisSource("briefing");
});
