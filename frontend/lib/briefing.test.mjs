// Phase F: Denní přehled – výběr stavu karty, odkazy a popisky.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  briefingView,
  fallbackGroups,
  generateAction,
  generatedCaption,
  generateErrorText,
  pragueHHMM,
  safeHref,
} from "./briefing.ts";

const base = {
  date: "2026-10-05",
  enabled: true,
  scheduled_time: "07:00",
  status: "missing",
  briefing: null,
  generated_at: null,
  generated_label: null,
  trigger: null,
  regenerated_count: 0,
  error_category: null,
  error_text: null,
  fallback: { today: [], overdue: [], soon: [] },
};
const content = { summary: "Dnes 2 věci.", priorities: [], watch: [], upcoming: [], note: null };

test("pragueHHMM uses Prague time in summer and winter", () => {
  assert.equal(pragueHHMM(new Date("2026-10-05T04:30:00Z")), "06:30");
  assert.equal(pragueHHMM(new Date("2026-12-05T06:05:00Z")), "07:05");
});

test("missing before the scheduled time says it will be generated", () => {
  const v = briefingView(base, new Date("2026-10-05T04:30:00Z")); // 06:30 Praha
  assert.equal(v.kind, "scheduled");
  assert.match(v.message, /07:00/);
});

test("missing after the scheduled time is 'not generated yet'", () => {
  assert.equal(briefingView(base, new Date("2026-10-05T06:30:00Z")).kind, "missing");
});

test("disabled scheduler is explained", () => {
  assert.equal(briefingView({ ...base, enabled: false }, new Date("2026-10-05T04:00:00Z")).kind, "disabled");
});

test("ready, generating and failed states", () => {
  const ready = briefingView({ ...base, status: "ready", briefing: content });
  assert.equal(ready.kind, "ready");
  assert.equal(ready.warning, null);
  assert.equal(briefingView({ ...base, status: "generating" }).kind, "generating");
  const failed = briefingView({ ...base, status: "failed", error_text: "AI má vyčerpaný denní limit." });
  assert.equal(failed.kind, "failed");
  assert.match(failed.message, /denní limit/);
});

test("failed regeneration keeps the previous briefing with a warning", () => {
  const v = briefingView({
    ...base, status: "ready", briefing: content, error_category: "regenerate_failed:provider", error_text: "AI neodpověděla.",
  });
  assert.equal(v.kind, "ready");
  assert.match(v.warning, /předchozí verze/);
});

test("generate action: create, regenerate, none while generating", () => {
  assert.deepEqual(generateAction(base), { label: "Vytvořit přehled", regenerate: false });
  assert.deepEqual(generateAction({ ...base, status: "ready", briefing: content }), { label: "Přegenerovat", regenerate: true });
  assert.equal(generateAction({ ...base, status: "generating" }), null);
  assert.equal(generateAction(null), null);
});

test("safeHref allows only internal paths", () => {
  assert.equal(safeHref("/school"), "/school");
  assert.equal(safeHref("https://evil.example"), null);
  assert.equal(safeHref("//evil.example"), null);
  assert.equal(safeHref(""), null);
  assert.equal(safeHref(null), null);
});

test("generated caption mentions trigger and regenerations", () => {
  assert.equal(generatedCaption(base), null);
  assert.equal(generatedCaption({ ...base, generated_label: "07:00", trigger: "scheduler" }), "Vytvořeno v 07:00");
  assert.equal(
    generatedCaption({ ...base, generated_label: "09:12", trigger: "manual", regenerated_count: 2 }),
    "Vytvořeno v 09:12 (ručně) · přegenerováno 2×",
  );
  assert.match(generatedCaption({ ...base, generated_label: "08:40", trigger: "catchup" }), /dodatečně/);
});

test("fallback groups keep order overdue → today → soon and drop empty", () => {
  const item = { ref: "assignment:1", kind: "assignment", label: "Úkol", when: "dnes", url: "/school", detail: "" };
  const groups = fallbackGroups({ ...base, fallback: { today: [item], overdue: [], soon: [item] } });
  assert.deepEqual(groups.map((g) => g.title), ["Dnes", "Brzy"]);
  assert.deepEqual(fallbackGroups({ ...base, fallback: null }), []);
});

test("generate error texts", () => {
  assert.match(generateErrorText(409), /právě vytváří/);
  assert.match(generateErrorText(401), /Přihlášení/);
  assert.match(generateErrorText(500, "boom"), /boom/);
});
