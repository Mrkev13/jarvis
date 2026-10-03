// Roadmap 4C: middleware.ts → proxy.ts – stejné rozhodování auth brány (regrese).
import assert from "node:assert/strict";
import { test } from "node:test";

import { authDecision } from "./authGate.ts";

const invalid = { kind: "ok", valid: false, authDisabled: false };

test("public paths always pass (login never loops)", () => {
  for (const p of ["/login", "/login/x", "/_next/static/a.js", "/sw.js", "/manifest.webmanifest"]) {
    assert.deepEqual(authDecision(p, "", invalid), { action: "next" }, p);
  }
});

test("invalid session redirects to /login with the original path", () => {
  assert.deepEqual(authDecision("/ai", "", invalid), { action: "redirect", location: "/login?next=%2Fai" });
  assert.deepEqual(authDecision("/finance", "?x=1", invalid), { action: "redirect", location: "/login?next=%2Ffinance%3Fx%3D1" });
});

test("valid session, disabled auth and unavailable backend pass", () => {
  assert.deepEqual(authDecision("/ai", "", { kind: "ok", valid: true }), { action: "next" });
  assert.deepEqual(authDecision("/ai", "", { kind: "ok", authDisabled: true }), { action: "next" });
  assert.deepEqual(authDecision("/ai", "", { kind: "unavailable" }), { action: "next" });
  assert.deepEqual(authDecision("/ai", "", null), { action: "next" });
});
