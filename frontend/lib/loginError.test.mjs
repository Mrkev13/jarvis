// Regrese 4B: špatný PIN ukazoval surový kód „invalid_pin" místo české hlášky.
import assert from "node:assert/strict";
import { test } from "node:test";

import { loginErrorMessage } from "./loginError.ts";

test("invalid PIN codes map to a Czech message", () => {
  assert.equal(loginErrorMessage("invalid_pin"), "Neplatný PIN.");
  assert.equal(loginErrorMessage("invalid_credentials"), "Neplatný PIN.");
  assert.equal(loginErrorMessage(""), "Neplatný PIN.");
  assert.equal(loginErrorMessage(undefined), "Neplatný PIN.");
});

test("lockout message is Czech with minutes rounded up", () => {
  assert.equal(
    loginErrorMessage("Too many failed attempts. Locked for 290s."),
    "Příliš mnoho neúspěšných pokusů. Zkus to znovu za 5 min.",
  );
  assert.equal(
    loginErrorMessage("Too many failed attempts. Locked for 20s."),
    "Příliš mnoho neúspěšných pokusů. Zkus to znovu za 1 min.",
  );
});

test("unknown text passes through unchanged", () => {
  assert.equal(loginErrorMessage("Server je nedostupný"), "Server je nedostupný");
});
