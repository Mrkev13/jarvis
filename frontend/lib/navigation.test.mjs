// MRK-79 / MRK-122: zúžená navigace – hlavní menu, skupina „Další“, dole Nastavení.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createModuleAccess, manifestFlags, MODULES } from "./modules.ts";
import { menuGroupsFor, menuPagesFor, navPagesFor, NAV_PAGES } from "./navigation.ts";

const ALL_ON = createModuleAccess(Object.fromEntries(MODULES.map((m) => [m.id, true])));
const off = (...ids) => createModuleAccess({ ...manifestFlags(), ...Object.fromEntries(ids.map((id) => [id, false])) });
const hrefs = (group) => group.pages.map((p) => p.href);
const byId = (groups) => Object.fromEntries(groups.map((g) => [g.id, g]));

test("hlavní menu má nanejvýš 8 položek i se všemi moduly zapnutými", () => {
  const { main } = byId(menuGroupsFor(ALL_ON));
  assert.ok(main.pages.length <= 8, hrefs(main).join(", "));
  for (const href of ["/", "/school", "/goals", "/reminders", "/ai"]) assert.ok(hrefs(main).includes(href), href);
});

test("skupiny: Další a dole Nastavení; Co se změnilo, Aktivita a Paměť nejsou v menu (MRK-122)", () => {
  const groups = menuGroupsFor(ALL_ON);
  assert.deepEqual(groups.map((g) => [g.id, g.label]), [["main", null], ["more", "Další"], ["system", "Systém"]]);
  const { more, system } = byId(groups);
  for (const href of ["/planner", "/finance", "/work", "/mff"]) assert.ok(hrefs(more).includes(href), href);
  assert.deepEqual(hrefs(system), ["/settings"]);
  const menu = menuPagesFor(ALL_ON).map((p) => p.href);
  for (const href of ["/changes", "/activity", "/memory"]) assert.ok(!menu.includes(href), href);
});

test("skupiny dohromady = celé menu, každá stránka právě jednou", () => {
  for (const access of [ALL_ON, createModuleAccess(manifestFlags()), off("finance", "work", "mff", "wot")]) {
    const grouped = menuGroupsFor(access).flatMap((g) => g.pages.map((p) => p.href));
    assert.deepEqual([...grouped].sort(), menuPagesFor(access).map((p) => p.href).sort());
    assert.equal(new Set(grouped).size, grouped.length);
  }
});

test("vypnutý modul zmizí ze všech skupin, prázdná skupina se nevykreslí", () => {
  const all = (access) => menuGroupsFor(access).flatMap((g) => g.pages.map((p) => p.href));
  assert.ok(!all(off("finance")).includes("/finance"));
  assert.ok(!all(off("wot")).includes("/wot"));
  const pagesOnlyMain = NAV_PAGES.filter((p) => !p.group);
  assert.deepEqual(menuGroupsFor(ALL_ON, pagesOnlyMain).map((g) => g.id), ["main"]);
});

test("Ctrl+K dál najde všechny dostupné stránky bez ohledu na skupinu", () => {
  const found = navPagesFor(ALL_ON).map((p) => p.href);
  for (const href of ["/planner", "/settings", "/changes", "/activity", "/memory", "/today", "/review", "/finance"]) assert.ok(found.includes(href), href);
});
