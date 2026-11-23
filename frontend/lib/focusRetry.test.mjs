// MRK-129: fokus po akci na Dnes – znovu zaměřit jen když se ztratil, nikdy nepřebít uživatele.
import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldRefocus } from "./focusRetry.ts";

const node = (connected = true) => ({ isConnected: connected });

test("first attempt always focuses", () => {
  assert.equal(shouldRefocus({ active: null, focused: null, activeIsBody: true }), true);
});

test("focus kept on our element = done", () => {
  const el = node();
  assert.equal(shouldRefocus({ active: el, focused: el, activeIsBody: false }), false);
});

test("focus fell to body or our node was replaced = retry", () => {
  const el = node();
  assert.equal(shouldRefocus({ active: null, focused: el, activeIsBody: true }), true);
  const gone = node(false);
  assert.equal(shouldRefocus({ active: gone, focused: gone, activeIsBody: false }), true);
});

test("never steal focus the user moved elsewhere", () => {
  assert.equal(shouldRefocus({ active: node(), focused: node(), activeIsBody: false }), false);
});
