import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import * as wot from "./wot.ts";

const records = [1, 2].map((id) => ({
  id, tank: "Progetto 65", milestone_type: "mastery", mastery: "ace",
  map_name: "Útesy", played_on: "2026-09-14", damage: 5205,
  assist: null, kills: null, base_xp: null, notes: `Battle ${id}`,
  favorite: false, created_at: null, updated_at: null, screenshots: [], replay_ids: [id + 10],
}));

test("MRK-12: validation and sorting retain identical-tank Ace records", () => {
  for (const record of records) {
    const result = wot.milestoneBody(wot.milestoneDraftFrom(record), "2026-10-07");
    assert.equal(result.ok, true);
    assert.equal(result.body.tank, "Progetto 65");
    assert.equal(result.body.mastery, "ace");
  }
  assert.deepEqual(wot.sortMilestones(records).map((m) => m.id), [2, 1]);
  assert.deepEqual(records.map((m) => m.id), [1, 2], "sorting does not mutate source data");
});

test("MRK-12: actual WoT page renders both records from the API list", () => {
  // Execute the real page with resource data and inert UI shells. No browser,
  // API, or Next server is needed; the page's list selection/map runs unchanged.
  const require = createRequire(import.meta.url);
  const shell = ({ children }) => React.createElement("div", null,
    typeof children === "function" ? null : children);
  const modules = {
    react: React,
    "@/lib/wot": wot,
    "@/hooks/useApiResource": { useApiResource: (path) => ({
      data: path === "/wot/milestones" ? records : path === "/wot/resources" ? {} : [],
      loading: false, refreshing: false, status: "ready", reload: async () => {},
    }) },
    "@/components/ui": new Proxy({}, { get: () => shell }),
    "@/components/wot/MilestoneCard": { MilestoneCard: ({ milestone }) =>
      React.createElement("li", { "data-milestone": milestone.id }, milestone.tank, milestone.notes) },
    "@/components/wot/MilestoneForm": { MilestoneForm: () => null },
    "@/components/wot/CompletedGrinds": { CompletedGrinds: () => null },
    "@/components/wot/GrindRow": { GrindRow: () => null },
    "@/components/games/GameImage": { GameImage: () => null },
    "@/lib/format": { formatNumber: String, plural: () => "", pragueDayKey: () => "2026-10-07" },
    "@/lib/jarvisSignals": { pulseJarvis: () => {} },
    "@/lib/motion": { prefersReducedMotion: () => true },
    "@/lib/api": { apiFetch: () => { throw Error("Unexpected API request"); }, jsonBody: () => {} },
  };
  const source = readFileSync(new URL("../app/wot/page.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const compiledModule = { exports: {} };
  new Function("require", "module", "exports", compiled)(
    (name) => Object.hasOwn(modules, name) ? modules[name] : require(name), compiledModule, compiledModule.exports);
  const html = renderToStaticMarkup(React.createElement(compiledModule.exports.default));
  assert.equal((html.match(/data-milestone=/g) ?? []).length, 2);
  assert.match(html, /data-milestone="1"/);
  assert.match(html, /data-milestone="2"/);
  assert.match(html, /Battle 1/);
  assert.match(html, /Battle 2/);
});
