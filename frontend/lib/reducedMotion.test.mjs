// Roadmap 4A: omezený pohyb – všechny animace (motion-*, Tailwind animate-*, HUD puls) se vypnou.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = (name) => readFileSync(new URL(`../app/${name}`, import.meta.url), "utf8");

function reducedBlock(source) {
  const start = source.indexOf("@media (prefers-reduced-motion: reduce)");
  assert.ok(start >= 0, "chybí blok prefers-reduced-motion");
  return source.slice(start);
}

test("Tailwind pulse/bounce/ping/spin are disabled for reduced motion", () => {
  const block = reducedBlock(css("motion.css"));
  for (const cls of [".animate-pulse", ".animate-bounce", ".animate-ping", ".animate-spin"]) {
    assert.ok(block.includes(cls), `${cls} není v reduced-motion bloku`);
  }
});

test("HUD live pulse becomes a static ring under reduced motion", () => {
  const block = reducedBlock(css("hud.css"));
  assert.match(block, /\.status-pulse-live::after\s*\{[^}]*animation:\s*none/);
});

test("design tokens are imported and the app stays dark", () => {
  const globals = css("globals.css");
  assert.ok(globals.indexOf('@import "./tokens.css"') > globals.indexOf('@import "tailwindcss"'));
  assert.ok(globals.includes('@import "./hud.css"'));
  assert.match(css("tokens.css"), /--color-app:\s*#07090d/);
});

// Roadmap 6A: sémantická primitiva (motion-semantic.css) – každá animace má reduced-motion protějšek.
function rulesOutsideReduced(source) {
  const body = source.slice(0, source.indexOf("@media (prefers-reduced-motion: reduce)")).replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];
  for (const m of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = m[1].trim();
    if (selectors.startsWith("@") || /^(from|to|\d+%)/.test(selectors)) continue;
    rules.push({ selectors: selectors.split(",").map((s) => s.trim()), decl: m[2] });
  }
  return rules;
}

test("every animated semantic primitive is stopped under reduced motion", () => {
  const source = css("motion-semantic.css");
  const block = reducedBlock(source);
  const animated = rulesOutsideReduced(source).filter((r) => /\banimation\s*:/.test(r.decl)).flatMap((r) => r.selectors);
  assert.ok(animated.length >= 7, animated.join(", "));
  for (const sel of animated) assert.ok(block.includes(sel), `${sel} chybí v reduced-motion bloku`);
  assert.match(block, /animation:\s*none !important/);
});

test("progress updates immediately and decorative glows stay static under reduced motion", () => {
  const block = reducedBlock(css("motion-semantic.css"));
  assert.match(block, /\.motion-progress-fill\s*\{[^}]*transition:\s*none/);
  // Trvalý obrys milníku (::before) není animovaný → zůstává i bez pohybu.
  assert.doesNotMatch(block, /\.motion-milestone::before/);
});

test("semantic motion animates only opacity/transform (glows) and a short ring for warning/error", () => {
  const source = css("motion-semantic.css");
  for (const m of source.matchAll(/@keyframes ([a-z-]+)\s*\{([\s\S]*?)\n\}/g)) {
    const props = [...m[2].matchAll(/([a-z-]+)\s*:/g)].map((p) => p[1]);
    const allowed = m[1].startsWith("motion-ring-") ? ["box-shadow"] : ["opacity", "transform"];
    for (const p of props) assert.ok(allowed.includes(p), `${m[1]} animuje ${p}`);
  }
  // Žádné třesení: chyba/varování se nehýbou.
  assert.doesNotMatch(source, /translateX\([^)]*px\)/);
  assert.doesNotMatch(css("motion.css"), /motion-shake/);
});

test("no infinite loops in semantic primitives except the opt-in streak idle", () => {
  const rules = rulesOutsideReduced(css("motion-semantic.css"));
  for (const r of rules.filter((x) => /\binfinite\b/.test(x.decl))) {
    assert.deepEqual(r.selectors, [".motion-streak-bump-idle"]);
  }
});

test("semantic CSS is imported after the base motion layer", () => {
  const globals = css("globals.css");
  assert.ok(globals.indexOf('@import "./motion-semantic.css"') > globals.indexOf('@import "./motion.css"'));
});

test("completion celebrations share the semantic motion primitive instead of module-specific keyframes", () => {
  const baseMotion = css("motion.css");
  const semanticMotion = css("motion-semantic.css");
  const keyframes = (source) => [...source.matchAll(/@keyframes\s+([a-z0-9-]+)/g)].map((match) => match[1]);

  assert.deepEqual(
    keyframes(baseMotion).filter((name) => name.includes("grind-complete")),
    [],
    "WoT nesmí udržovat vlastní completion keyframes vedle sdíleného CompletionState",
  );
  assert.ok(keyframes(semanticMotion).includes("motion-glow-once"));
});
