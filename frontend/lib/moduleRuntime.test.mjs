// MRK-18 A2: runtime stav modulů z GET /modules – odpověď řídí gating, nic z build-time prostředí.
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { availableWidgets, WIDGETS } from "./dashboardLayout.ts";
import {
  accessFor,
  flagsFromRuntime,
  parseCachedModules,
  parseModules,
  routeDecision,
  serializeModules,
  settingsModules,
  UNKNOWN_SNAPSHOT,
} from "./moduleRuntime.ts";
import { MODULES } from "./modules.ts";
import { NAV_PAGES, navPagesFor } from "./navigation.ts";
import { availableKinds } from "./quickAdd.ts";
import { filterAvailable } from "./search.ts";

/** Odpověď ve tvaru backendu (public_config) – výchozí stav, volitelně s přepsanými moduly. */
function response(overrides = {}) {
  return {
    modules: MODULES.map((m) => {
      const o = overrides[m.id] ?? {};
      const enabled = o.enabled ?? m.defaultEnabled;
      return {
        id: m.id, label: m.label, enabled, available: enabled && m.implemented,
        source: o.source ?? "default", locked: o.locked ?? false, implemented: m.implemented,
        default_enabled: m.defaultEnabled, depends_on: [], capabilities: enabled && m.implemented ? m.capabilities : [],
      };
    }),
  };
}
const ready = (body) => ({ status: "ready", modules: parseModules(body) });
const CORE_PAGES = NAV_PAGES.filter((p) => !p.module);

test("parseModules accepts the backend shape and rejects anything else", () => {
  assert.equal(parseModules(response()).length, MODULES.length);
  for (const bad of [null, {}, { modules: "x" }, { modules: [{ id: "wot" }] }, { modules: [{ ...response().modules[0], source: "file" }] }]) {
    assert.equal(parseModules(bad), null, JSON.stringify(bad));
  }
  const roundTrip = parseCachedModules(serializeModules(parseModules(response())));
  assert.deepEqual(roundTrip, parseModules(response()));
  assert.equal(parseCachedModules("{nope"), null);
  assert.equal(parseCachedModules(null), null);
});

test("runtime response drives gating – WoT disabled at runtime disappears everywhere", () => {
  const access = accessFor(ready(response({ wot: { enabled: false, source: "db" } })));
  assert.equal(access.isAvailable("wot"), false);
  assert.ok(!navPagesFor(access).some((p) => p.href === "/wot"), "navigace");
  assert.deepEqual(filterAvailable([{ type: "wot_grind", id: 1, title: "Kranvagn", href: "/wot" }, { type: "goal", id: 2, title: "Cíl", href: "/goals" }], access).map((r) => r.type), ["goal"], "vyhledávání");
  assert.ok(!availableWidgets(access).some((w) => w.id === "games") || availableWidgets(access).find((w) => w.id === "games").modules.some((id) => id !== "wot"), "dashboard");
  assert.equal(access.allowsPath("/wot/replays"), false, "stránky");
  assert.equal(access.allows("wot", "ai_context"), false, "AI");
  // ostatní moduly beze změny
  assert.equal(access.isAvailable("mff"), true);
});

test("runtime enabled=true for a module whose frontend default is off still respects implemented=false", () => {
  const access = accessFor(ready(response({ food: { enabled: true, source: "env", locked: true } })));
  assert.equal(access.isAvailable("food"), false);
});

test("Quick Add kinds follow runtime state", () => {
  const off = accessFor(ready(response({ finance: { enabled: false, source: "db" } })));
  assert.ok(!availableKinds(off).includes("finance"));
  assert.ok(availableKinds(accessFor(ready(response()))).includes("finance"));
});

test("unknown or failed state is conservative: only core pages, module routes never render", () => {
  for (const snapshot of [UNKNOWN_SNAPSHOT, { status: "error", modules: null }]) {
    const access = accessFor(snapshot);
    assert.deepEqual(navPagesFor(access), CORE_PAGES, snapshot.status);
    assert.equal(availableWidgets(access).filter((w) => w.modules?.length).length, 0, "žádné modulové widgety");
    assert.equal(routeDecision(snapshot, access, "/wot"), snapshot.status === "error" ? "error" : "loading");
    assert.equal(routeDecision(snapshot, access, "/today"), "allow", "jádro se vykreslí vždy");
    assert.equal(routeDecision(snapshot, access, "/settings"), "allow");
  }
  // modul, o kterém server neřekl nic, je vypnutý (žádný fallback na výchozí hodnotu frontendu)
  assert.equal(flagsFromRuntime([]).wot, false);
});

test("routeDecision with known state", () => {
  const off = ready(response({ wot: { enabled: false, source: "db" } }));
  assert.equal(routeDecision(off, accessFor(off), "/wot/replays"), "unavailable");
  const on = ready(response());
  assert.equal(routeDecision(on, accessFor(on), "/wot"), "allow");
  assert.deepEqual(availableWidgets(accessFor(on)), WIDGETS, "výchozí stav = jako dřív");
  assert.deepEqual(navPagesFor(accessFor(on)), NAV_PAGES);
});

test("Settings list: implemented modules only, locked state preserved", () => {
  const mods = settingsModules(parseModules(response({ wot: { enabled: true, source: "env", locked: true } })));
  assert.deepEqual(mods.map((m) => m.id), MODULES.filter((m) => m.implemented).map((m) => m.id));
  const wot = mods.find((m) => m.id === "wot");
  assert.equal(wot.locked, true);
  const src = readFileSync(new URL("../components/modules/ModuleSettings.tsx", import.meta.url), "utf8");
  assert.match(src, /disabled=\{m\.locked/, "zamčený přepínač nejde použít");
  assert.match(src, /if \(m\.locked \|\| busy\) return;/, "ani programové kliknutí nic nepošle");
  assert.match(src, /Vynuceno konfigurací serveru/);
});

test("no NEXT_PUBLIC_MODULE_* dependency remains for module state", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  assert.equal(existsSync(join(root, "lib", "moduleConfig.ts")), false);
  const offenders = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      if (name === "node_modules" || name.startsWith(".")) continue;
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(ts|tsx|mjs)$/.test(name) && !name.endsWith(".test.mjs") && readFileSync(path, "utf8").includes("NEXT_PUBLIC_MODULE")) offenders.push(path);
    }
  };
  for (const dir of ["app", "components", "hooks", "lib", "scripts"]) walk(join(root, dir));
  assert.deepEqual(offenders, []);
});
