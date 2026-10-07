// Roadmap 6A: sémantické motion tokeny – malá sada, CSS a JS se shodují, každá kategorie má třídu.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { MOTION_CATEGORIES, MOTION_DURATION, MOTION_EASING, MOTION_SPEC, motionClass, motionDurationMs } from "./motionTokens.ts";

const css = (name) => readFileSync(new URL(`../app/${name}`, import.meta.url), "utf8");
const motionCss = css("motion.css");
const semanticCss = css("motion-semantic.css");

function cssVar(source, name) {
  const m = source.match(new RegExp(`${name}:\\s*([^;]+);`));
  return m ? m[1].trim() : null;
}

test("token set stays small: 5 durations, 4 easings", () => {
  assert.deepEqual(Object.keys(MOTION_DURATION), ["instant", "fast", "normal", "deliberate", "celebration"]);
  assert.deepEqual(Object.keys(MOTION_EASING), ["standard", "enter", "exit", "emphasized"]);
  const values = Object.values(MOTION_DURATION);
  assert.deepEqual([...values].sort((a, b) => a - b), values, "délky jsou seřazené od nejkratší");
  assert.equal(MOTION_DURATION.instant, 0);
  assert.ok(MOTION_DURATION.celebration <= 1500, "oslava nejvýš 1,5 s");
});

test("CSS custom properties mirror the JS tokens", () => {
  for (const [name, ms] of Object.entries(MOTION_DURATION)) {
    assert.equal(cssVar(motionCss, `--motion-duration-${name}`), `${ms}ms`, `--motion-duration-${name}`);
  }
  for (const [name, curve] of Object.entries(MOTION_EASING)) {
    assert.equal(cssVar(motionCss, `--motion-ease-${name}`), curve, `--motion-ease-${name}`);
  }
  // Původní názvy jsou aliasy, ne další hodnoty.
  assert.equal(cssVar(motionCss, "--motion-fast"), "var(--motion-duration-fast)");
  assert.equal(cssVar(motionCss, "--motion-normal"), "var(--motion-duration-normal)");
  assert.equal(cssVar(motionCss, "--motion-slow"), "var(--motion-duration-deliberate)");
  assert.equal(cssVar(motionCss, "--motion-ease"), "var(--motion-ease-enter)");
});

test("semantic CSS uses only semantic duration/easing tokens", () => {
  const rules = semanticCss.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.doesNotMatch(rules, /\b\d+(ms|s)\b/, "žádné natvrdo zapsané délky");
  for (const m of rules.matchAll(/var\(--motion-(duration|ease)-([a-z]+)\)/g)) {
    const known = m[1] === "duration" ? MOTION_DURATION : MOTION_EASING;
    assert.ok(m[2] in known, `neznámý token ${m[0]}`);
  }
});

test("every semantic category maps to an existing CSS class and a token duration", () => {
  assert.deepEqual([...MOTION_CATEGORIES].sort(), Object.keys(MOTION_SPEC).sort());
  for (const category of MOTION_CATEGORIES) {
    const cls = motionClass(category);
    assert.match(cls, /^motion-[a-z-]+$/);
    assert.ok(
      new RegExp(`\\.${cls}[\\s,{:.]`).test(motionCss) || new RegExp(`\\.${cls}[\\s,{:.]`).test(semanticCss),
      `${category}: třída .${cls} neexistuje`,
    );
    assert.ok(MOTION_SPEC[category].duration in MOTION_DURATION);
    assert.ok(MOTION_SPEC[category].easing in MOTION_EASING);
    assert.equal(motionDurationMs(category), MOTION_DURATION[MOTION_SPEC[category].duration]);
  }
  assert.ok(MOTION_CATEGORIES.length <= 10);
});

test("nothing loops: one-shot categories, attention at most 3 pulses", () => {
  for (const category of MOTION_CATEGORIES) {
    const { iterations } = MOTION_SPEC[category];
    assert.ok(iterations === "once" || (typeof iterations === "number" && iterations <= 3), category);
  }
  assert.equal(MOTION_SPEC.attention.iterations, 3);
  assert.match(motionCss, /\.motion-attention\s*\{[^}]*\b3;/, "CSS motion-attention má 3 iterace");
});
