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
