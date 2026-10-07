import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  JARVIS_SIZES,
  JARVIS_STATES,
  aiJarvisState,
  briefingJarvisState,
  jarvisAssetMode,
  jarvisMotionClass,
  jarvisVisual,
} from "./jarvisAvatar.ts";

test("all supported states have a distinct non-color visual cue", () => {
  assert.deepEqual(JARVIS_STATES, ["idle", "listening", "thinking", "success", "warning", "error"]);
  assert.deepEqual(
    JARVIS_STATES.map((state) => jarvisVisual(state, "md").expression),
    ["calm", "open", "focus", "smile", "alert", "cross"],
  );
  assert.equal(new Set(JARVIS_STATES.map((state) => jarvisVisual(state, "md").label)).size, 6);
});

test("size variants keep fixed, practical dimensions", () => {
  assert.deepEqual(JARVIS_SIZES, ["sm", "md", "lg"]);
  assert.deepEqual(
    JARVIS_SIZES.map((size) => jarvisVisual("idle", size).pixels),
    [40, 64, 96],
  );
});

test("AI avatar state follows error, work, confirmation, success, idle priority", () => {
  assert.equal(aiJarvisState({ failure: true, failedAction: false, sending: true, confirming: false, listening: true, pending: 0, success: false }), "error");
  assert.equal(aiJarvisState({ failure: false, failedAction: true, sending: false, confirming: false, listening: true, pending: 1, success: false }), "error");
  assert.equal(aiJarvisState({ failure: false, failedAction: false, sending: true, confirming: false, listening: true, pending: 0, success: false }), "thinking");
  assert.equal(aiJarvisState({ failure: false, failedAction: false, sending: false, confirming: true, listening: true, pending: 1, success: false }), "thinking");
  assert.equal(aiJarvisState({ failure: false, failedAction: false, sending: false, confirming: false, listening: false, pending: 1, success: false }), "warning");
  assert.equal(aiJarvisState({ failure: false, failedAction: false, sending: false, confirming: false, listening: true, pending: 0, success: false }), "listening");
  assert.equal(aiJarvisState({ failure: false, failedAction: false, sending: false, confirming: false, listening: false, pending: 0, success: true }), "success");
  assert.equal(aiJarvisState({ failure: false, failedAction: false, sending: false, confirming: false, listening: false, pending: 0, success: false }), "idle");
});

test("missing or failed shell asset chooses the deterministic fallback", () => {
  assert.equal(jarvisAssetMode(false), "asset");
  assert.equal(jarvisAssetMode(true), "fallback");
});

test("animated states reuse Motion System semantic classes", () => {
  assert.deepEqual(
    JARVIS_STATES.map(jarvisMotionClass),
    ["", "", "motion-executing", "motion-completion", "motion-warning", "motion-error"],
  );
});

test("Daily Briefing keeps Jarvis calm except for meaningful work or problems", () => {
  assert.equal(briefingJarvisState({ loading: false, busy: false, error: false, generating: false, warning: false }), "idle");
  assert.equal(briefingJarvisState({ loading: true, busy: false, error: false, generating: false, warning: false }), "thinking");
  assert.equal(briefingJarvisState({ loading: false, busy: true, error: false, generating: false, warning: false }), "thinking");
  assert.equal(briefingJarvisState({ loading: false, busy: false, error: false, generating: true, warning: false }), "thinking");
  assert.equal(briefingJarvisState({ loading: false, busy: false, error: false, generating: false, warning: true }), "warning");
  assert.equal(briefingJarvisState({ loading: true, busy: true, error: true, generating: true, warning: true }), "error");
});

test("AI transient result state is cleared when its conversation context ends", () => {
  const hook = readFileSync(new URL("../hooks/useAiChat.ts", import.meta.url), "utf8");
  const reset = hook.match(/const reset = useCallback\(\(\) => \{([\s\S]*?)\n  \}, \[\]\);/)?.[1] ?? "";
  const sendStart = hook.match(/const send = useCallback\([\s\S]*?setHistory[\s\S]*?setSending\(true\);/)?.[0] ?? "";
  const reject = hook.match(/const reject = useCallback\([\s\S]*?\n  \);/)?.[0] ?? "";

  assert.match(reset, /setFailedAction\(null\)/);
  assert.match(reset, /setOutcomes\(\[\]\)/);
  assert.match(sendStart, /setFailedAction\(null\)/);
  assert.match(reject, /setFailedAction\(\(current\) => current\?\.id === action\.id \? null : current\)/);
});
