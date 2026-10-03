// Phase G: Týdenní přehled – stavy stránky, odhady oddělené od faktů, popisky.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  confidenceLabel,
  displayContent,
  generateAction,
  metaCaption,
  reviewView,
} from "./weeklyReview.ts";

const content = {
  headline: "Dokončený úkol",
  summary: "Shrnutí.",
  wins: [{ ref: "metric:a", text: "Dokončen 1 úkol", kind: "metric", url: "/school" }],
  concerns: [],
  comparisons: [],
  next_week: [{ ref: "assignment:3", text: "Projekt", kind: "assignment", url: "/school" }],
  forecasts: [{ ref: "forecast:x", statement: "Příští týden může být náročnější.", confidence: "high",
    confidence_text: "vysoká", rule: "známé termíny", basis_labels: ["Projekt"] }],
  focus: [],
  partial: true,
};
const base = {
  week_start: "2026-10-05", week_label: "5.–11. 10. 2026", is_current: true, can_generate: true, enabled: true,
  schedule_label: "neděle 19:00", status: "missing", review: null, generated_label: null, period_end_label: null,
  trigger: null, regenerated_count: 0, error_category: null, error_text: null, fallback: null,
};

test("no review yet / scheduled message", () => {
  const v = reviewView(base);
  assert.equal(v.kind, "missing");
  assert.match(v.message, /neděle 19:00/);
  assert.equal(reviewView({ ...base, is_current: false }).message, "Pro tento týden přehled není.");
  assert.equal(reviewView({ ...base, enabled: false }).kind, "disabled");
});

test("generating, ready, failed and failed regeneration", () => {
  assert.equal(reviewView({ ...base, status: "generating" }).kind, "generating");
  const failed = reviewView({ ...base, status: "failed", error_text: "AI má vyčerpaný denní limit." });
  assert.equal(failed.kind, "failed");
  assert.match(failed.message, /denní limit/);
  const ready = reviewView({ ...base, status: "ready", review: content });
  assert.equal(ready.kind, "ready");
  assert.equal(ready.warning, null);
  const kept = reviewView({ ...base, status: "ready", review: content, error_category: "regenerate_failed:output_limit" });
  assert.match(kept.warning, /předchozí verze/);
});

test("deterministic quiet review renders as a normal review", () => {
  const quiet = { ...content, quiet: true, forecasts: [], wins: [], headline: "Klidný týden – málo dat" };
  const v = reviewView({ ...base, status: "ready", review: quiet });
  assert.equal(v.kind, "ready");
  assert.equal(v.content.forecasts.length, 0);
});

test("generate only for the current week; history is read-only", () => {
  assert.deepEqual(generateAction(base), { label: "Vytvořit přehled", regenerate: false });
  assert.deepEqual(generateAction({ ...base, review: content }), { label: "Přegenerovat", regenerate: true });
  assert.equal(generateAction({ ...base, can_generate: false, is_current: false, review: content }), null);
  assert.equal(generateAction({ ...base, status: "generating" }), null);
  assert.equal(generateAction(null), null);
});

test("fallback content is flagged", () => {
  assert.deepEqual(displayContent(base), { content: null, isFallback: false });
  assert.equal(displayContent({ ...base, fallback: content }).isFallback, true);
  assert.equal(displayContent({ ...base, review: content, fallback: content }).isFallback, false);
});

test("forecast confidence labels", () => {
  assert.equal(confidenceLabel("high"), "vysoká jistota");
  assert.equal(confidenceLabel("low"), "nízká jistota");
  assert.equal(confidenceLabel("??"), "jistota neuvedena");
});

test("meta caption and counts", () => {
  assert.equal(metaCaption(base), null);
  assert.equal(
    metaCaption({ ...base, review: content, generated_label: "neděle 11. 10. 19:00", trigger: "manual",
      period_end_label: "neděle 11. 10. 19:00", regenerated_count: 2 }),
    "Vytvořeno neděle 11. 10. 19:00 (ručně) · data do neděle 11. 10. 19:00 · přegenerováno 2×",
  );
});
