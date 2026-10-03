// Roadmap 4A: ConfirmDialog – Escape během odesílání nezavře, past na fokus, sdílený zámek scrollu.
import assert from "node:assert/strict";
import { test } from "node:test";

import { dialogKeyAction, isPromiseLike, lockScroll, nextFocusIndex } from "./dialog.ts";

test("Escape closes only when not busy; Tab is trapped", () => {
  assert.equal(dialogKeyAction("Escape", false), "close");
  assert.equal(dialogKeyAction("Escape", true), "none");
  assert.equal(dialogKeyAction("Tab", true), "trap");
  assert.equal(dialogKeyAction("Enter", false), "none");
});

test("focus wraps both ways", () => {
  assert.equal(nextFocusIndex(1, 2, false), 0);
  assert.equal(nextFocusIndex(0, 2, true), 1);
  assert.equal(nextFocusIndex(-1, 3, false), 0);
  assert.equal(nextFocusIndex(-1, 3, true), 2);
  assert.equal(nextFocusIndex(0, 0, false), -1);
});

test("promise detection drives the busy state", () => {
  assert.equal(isPromiseLike(Promise.resolve()), true);
  assert.equal(isPromiseLike(undefined), false);
  assert.equal(isPromiseLike({ then: 1 }), false);
});

test("nested scroll locks restore the original overflow only at the end", () => {
  const doc = { body: { style: { overflow: "auto" } } };
  const releaseMenu = lockScroll(doc);
  const releaseDialog = lockScroll(doc);
  assert.equal(doc.body.style.overflow, "hidden");
  releaseDialog();
  releaseDialog(); // idempotentní
  assert.equal(doc.body.style.overflow, "hidden", "menu je pořád otevřené");
  releaseMenu();
  assert.equal(doc.body.style.overflow, "auto");
});
