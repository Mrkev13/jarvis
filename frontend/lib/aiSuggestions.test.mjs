// MRK-81: návrhy otázek – podle zapnutých modulů, nikdy Finance, odkaz s předvyplněným dotazem.
import assert from "node:assert/strict";
import { test } from "node:test";

import { AI_SUGGESTIONS, askFromSearch, askHref, suggestionsFor } from "./aiSuggestions.ts";
import { createModuleAccess, manifestFlags } from "./modules.ts";

const all = createModuleAccess(manifestFlags());

test("each surface has suggestions and the chat at most six", () => {
  for (const surface of ["ai", "school", "goals", "wot", "habits"]) assert.ok(suggestionsFor(surface, all).length > 0, surface);
  assert.ok(suggestionsFor("ai", all).length <= 6);
});

test("a disabled module gives no suggestion", () => {
  const noWot = createModuleAccess({ ...manifestFlags(), wot: false, school: false });
  assert.equal(suggestionsFor("wot", noWot).length, 0);
  assert.ok(suggestionsFor("ai", noWot).every((s) => s.module !== "wot" && s.module !== "school"));
  assert.ok(suggestionsFor("ai", noWot).some((s) => s.module === null), "core suggestions stay");
});

test("never a finance suggestion", () => {
  assert.ok(AI_SUGGESTIONS.every((s) => s.module !== "finance" && !/financ|peníz|bilanc|výdaj/i.test(s.prompt)));
});

test("ask link round-trip", () => {
  const href = askHref("Jak jsem na tom s cíli?");
  assert.equal(askFromSearch(href.split("?")[1]), "Jak jsem na tom s cíli?");
  assert.equal(askFromSearch(""), null);
  assert.equal(askFromSearch("ask=%20%20"), null);
  assert.equal(askFromSearch(`ask=${"x".repeat(400)}`).length, 300);
});
