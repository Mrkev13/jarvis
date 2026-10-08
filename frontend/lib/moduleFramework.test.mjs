// MRK-20: frontendové registry (navigace, parametry a skupiny vyhledávání, oblast a stránka Rychlého přidání)
// se odvozují z manifestu modulů (lib/modules.ts MODULE_UI) – nový modul nepřidává nic do navigation.ts ani search.ts.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { MODULE_UI, MODULES, quickAddOwner } from "./modules.ts";
import { modulePages, NAV_PAGES } from "./navigation.ts";
import { KIND_AREAS, KIND_HREFS, QUICK_ADD_KINDS } from "./quickAdd.ts";
import { GROUP_ORDER, SEARCH_TARGET_PARAMS } from "./search.ts";

test("manifest: only implemented modules, nav for every module with the nav capability, href is a module route", () => {
  const byId = new Map(MODULES.map((m) => [m.id, m]));
  for (const [id, ui] of Object.entries(MODULE_UI)) {
    const m = byId.get(id);
    assert.ok(m && m.implemented, `MODULE_UI.${id} bez implementovaného modulu`);
    if (ui.nav) assert.ok(m.routes.includes(ui.nav.href), `${id}: ${ui.nav.href} není v routes`);
  }
  for (const m of MODULES.filter((x) => x.implemented && x.capabilities.includes("nav"))) {
    assert.ok(MODULE_UI[m.id]?.nav, `${m.id} má schopnost nav, ale žádnou položku navigace`);
  }
});

test("derived registries equal the previous hand-written lists (zero-surprise)", () => {
  assert.deepEqual(NAV_PAGES.map((p) => p.href), [
    "/", "/today", "/review", "/planner", "/reminders", "/goals", "/school", "/work", "/finance", "/habits", "/wot", "/mff",
    "/activity", "/memory", "/ai", "/settings",
  ]);
  for (const p of NAV_PAGES.filter((x) => x.module)) assert.equal(p.area, p.module);
  assert.deepEqual(GROUP_ORDER, ["page", "school", "reminders", "work", "finance", "goals", "memory", "wot", "habits", "mff"]);
  assert.deepEqual(KIND_AREAS, { reminder: "reminders", finance: "finance", work: "work", exam: "school", assignment: "school" });
  assert.deepEqual(KIND_HREFS, { reminder: "/reminders", finance: "/finance", work: "/work", exam: "/school", assignment: "/school" });
});

test("search params and groups: unique, every module param is an href the backend provider builds", () => {
  assert.equal(new Set(SEARCH_TARGET_PARAMS).size, SEARCH_TARGET_PARAMS.length);
  assert.equal(new Set(GROUP_ORDER).size, GROUP_ORDER.length);
  for (const [id, ui] of Object.entries(MODULE_UI)) {
    const provider = [new URL(`../../backend/${id}_integrations.py`, import.meta.url),
      new URL(`../../backend/modules/${id}/integrations.py`, import.meta.url)].find((u) => existsSync(u));
    if (!provider) continue; // frontend bez backendu
    const src = readFileSync(provider, "utf8");
    for (const param of ui.searchParams ?? []) assert.ok(src.includes(`?${param}=`), `${id}: backend nevytváří ?${param}=`);
  }
});

test("Quick Add kinds of modules take area and page from the owning module", () => {
  for (const kind of QUICK_ADD_KINDS) {
    const owner = quickAddOwner(kind);
    if (!owner) continue; // jádro (připomínka)
    assert.equal(KIND_AREAS[kind], owner.id);
    assert.ok(owner.routes.includes(KIND_HREFS[kind]), kind);
  }
});

test("a new module appears in navigation from its manifest alone", () => {
  const alpha = { id: "alpha", label: "Alfa", defaultEnabled: true, implemented: true, capabilities: ["nav"], entityTypes: [], routes: ["/alpha"], quickAddKinds: [] };
  const pages = modulePages([...MODULES, alpha], { ...MODULE_UI, alpha: { nav: { href: "/alpha", label: "Alfa", keywords: ["alfa"], order: 35 } } });
  const i = pages.findIndex((p) => p.href === "/alpha");
  assert.ok(i > 0);
  assert.equal(pages[i - 1].href, "/work", "pořadí podle `order`");
  assert.deepEqual(pages[i], { href: "/alpha", label: "Alfa", area: "alpha", keywords: ["alfa"], module: "alpha" });
  // neimplementovaný modul se neukáže ani s manifestem
  const planned = { ...alpha, implemented: false };
  assert.ok(!modulePages([...MODULES, planned], { ...MODULE_UI, alpha: { nav: { href: "/alpha", label: "Alfa", keywords: [], order: 35 } } })
    .some((p) => p.href === "/alpha"));
});
