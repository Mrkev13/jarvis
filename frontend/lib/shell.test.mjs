// Roadmap 4B: login běží bez aplikačního rámu (žádný zvonek, žádná navigace).
import assert from "node:assert/strict";
import { test } from "node:test";

import { isBareRoute } from "./shell.ts";

test("login (and sub-paths) are bare routes", () => {
  assert.equal(isBareRoute("/login"), true);
  assert.equal(isBareRoute("/login/whatever"), true);
});

test("app pages keep the shell", () => {
  for (const p of ["/", "/reminders", "/review", "/loginx", "/planner"]) assert.equal(isBareRoute(p), false, p);
  assert.equal(isBareRoute(null), false);
});
