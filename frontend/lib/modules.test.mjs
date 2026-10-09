// Roadmap 6C: feature flagy modulů – parsování, registr, navigace, vyhledávání, dashboard, Rychlé přidání, Dnes, AI.
// Budoucí moduly zatím nemají kód → brány dokazují testovací moduly (FIXTURES) a vypnutí existujících modulů.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  availableWidgets,
  defaultLayout,
  needsDashboardData,
  parseStoredLayout,
  preserveUnavailable,
  serializeLayout,
  setWidgetVisible,
  WIDGETS,
} from "./dashboardLayout.ts";
import { allowsHref, CAPABILITIES, createModuleAccess, manifestFlags, MODULES } from "./modules.ts";
import { NAV_PAGES, navPagesFor } from "./navigation.ts";
import { availableKinds, examplesFor, gateParse, kindsHint, promptHint, QUICK_ADD_EXAMPLES, QUICK_ADD_KINDS } from "./quickAdd.ts";
import { filterAvailable, searchNavigation } from "./search.ts";

const ALL = [...CAPABILITIES];
const FIXTURES = [
  { id: "alpha", label: "Alfa", defaultEnabled: true, implemented: true, capabilities: ALL, entityTypes: ["alpha_item"], routes: ["/alpha"], quickAddKinds: ["alpha_meal"] },
  { id: "beta", label: "Beta", defaultEnabled: false, implemented: true, capabilities: ALL, entityTypes: ["beta_item"], routes: ["/beta"], quickAddKinds: ["beta_meal"] },
  { id: "gamma", label: "Gama", defaultEnabled: false, implemented: false, capabilities: [], entityTypes: [], routes: [], quickAddKinds: [] },
];
const EXISTING = ["school", "work", "finance", "goals", "wot", "mff", "habits"]; // habits = MRK-21 pilot
const FUTURE = ["food", "fitness", "projects", "knowledge", "car", "travel", "entertainment"];
const DEFAULTS = createModuleAccess(manifestFlags());
const off = (...ids) => createModuleAccess({ ...manifestFlags(), ...Object.fromEntries(ids.map((id) => [id, false])) });

test("manifest defaults: existing modules on, future modules off", () => {
  const flags = manifestFlags();
  for (const id of EXISTING) assert.equal(flags[id], true, id);
  for (const id of FUTURE) assert.equal(flags[id], false, id);
  assert.deepEqual(Object.keys(flags), MODULES.map((m) => m.id));
});

test("registry: unique ids and ownership, known capabilities", () => {
  const ids = MODULES.map((m) => m.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const key of ["entityTypes", "routes", "quickAddKinds"]) {
    const owned = MODULES.flatMap((m) => m[key]);
    assert.equal(new Set(owned).size, owned.length, key);
  }
  for (const m of MODULES) assert.ok(m.capabilities.every((c) => CAPABILITIES.includes(c)), m.id);
  // budoucí moduly nemají stránky ani schopnosti (žádné falešné produkční stránky)
  for (const id of FUTURE) {
    const m = MODULES.find((x) => x.id === id);
    assert.equal(m.implemented, false);
    assert.deepEqual([m.routes, m.capabilities], [[], []]);
  }
});

test("capabilities: enabled fixture allowed, disabled denied, flag alone never reveals an unimplemented module", () => {
  const access = createModuleAccess({ alpha: true, beta: false, gamma: true }, FIXTURES);
  for (const cap of CAPABILITIES) {
    assert.equal(access.allows("alpha", cap), true, cap);
    assert.equal(access.allows("beta", cap), false, cap);
    assert.equal(access.allows("gamma", cap), false, cap);
  }
  assert.equal(access.allows("unknown", "nav"), false);
  assert.equal(createModuleAccess({ beta: true }, FIXTURES).allows("beta", "today"), true);
  // budoucí moduly s flagem true zůstávají nedostupné
  const allOn = createModuleAccess(Object.fromEntries(FUTURE.map((id) => [id, true])));
  for (const id of FUTURE) assert.equal(allOn.isAvailable(id), false, id);
});

test("routes: disabled module path is not allowed, core paths always are", () => {
  const access = createModuleAccess({ alpha: true, beta: false }, FIXTURES);
  assert.equal(access.allowsPath("/beta"), false);
  assert.equal(access.allowsPath("/beta/123"), false);
  assert.equal(access.allowsPath("/betamax"), true, "celý segment");
  assert.equal(access.allowsPath("/alpha"), true);
  assert.equal(access.allowsPath("/today"), true);
  assert.equal(allowsHref(access, "/beta?item=3"), false);
  assert.equal(allowsHref(off("finance"), "/finance?transaction=3#x"), false);
  assert.equal(allowsHref(off("finance"), "/reminders?reminder=3"), true);
  assert.equal(DEFAULTS.moduleForPath("/goals")?.id, "goals");
});

test("navigation: default app unchanged, disabled module disappears", () => {
  assert.deepEqual(navPagesFor(DEFAULTS), NAV_PAGES);
  assert.deepEqual(navPagesFor(DEFAULTS), NAV_PAGES, "výchozí stav manifestu");
  const hrefs = navPagesFor(off("wot", "finance")).map((p) => p.href);
  assert.ok(!hrefs.includes("/wot") && !hrefs.includes("/finance"));
  assert.equal(hrefs.length, NAV_PAGES.length - 2);
  // fixture modul: stránka zapnutého modulu je vidět, vypnutého ne
  const pages = [...NAV_PAGES, { href: "/alpha", label: "Alfa", area: null, keywords: [], module: "alpha" }, { href: "/beta", label: "Beta", area: null, keywords: [], module: "beta" }];
  const fixtureHrefs = navPagesFor(createModuleAccess({ alpha: true, beta: false }, FIXTURES), pages).map((p) => p.href);
  assert.ok(fixtureHrefs.includes("/alpha"));
  assert.ok(!fixtureHrefs.includes("/beta"));
  // každá stránka modulu v navigaci patří existujícímu modulu a leží pod jeho cestou (žádné mrtvé odkazy)
  for (const p of NAV_PAGES.filter((x) => x.module)) {
    assert.equal(DEFAULTS.moduleForPath(p.href)?.id, p.module, p.href);
  }
});

test("search: availability is a filter, ranking unchanged", () => {
  const pages = navPagesFor(off("wot"));
  assert.deepEqual(searchNavigation("wot", pages).map((r) => r.href).includes("/wot"), false);
  assert.equal(searchNavigation("", pages).length, NAV_PAGES.length - 1);
  // současné moduly: výchozí stav beze změny
  assert.deepEqual(searchNavigation("marvel", navPagesFor(DEFAULTS)), searchNavigation("marvel"));
  const results = [
    { id: "wot_grind:1", type: "wot_grind", title: "IS-7", subtitle: "", area: "wot", href: "/wot?grind=1", score: 100 },
    { id: "transaction:2", type: "transaction", title: "Oběd", subtitle: "", area: "finance", href: "/finance?transaction=2", score: 85 },
    { id: "memory:3", type: "memory", title: "Fitness plán", subtitle: "", area: "memory", href: "/memory?memory=3", score: 70 },
    { id: "nav:/wot", type: "page", title: "World of Tanks", subtitle: "", area: "wot", href: "/wot", score: 105 },
  ];
  assert.deepEqual(filterAvailable(results, DEFAULTS), results);
  assert.deepEqual(filterAvailable(results, off("wot")).map((r) => r.id), ["transaction:2", "memory:3"]);
  // fixture: záznamy vypnutého modulu nejsou ve výsledcích ani v nedávných
  const fx = createModuleAccess({ alpha: true, beta: false }, FIXTURES);
  const fxResults = [
    { id: "alpha_item:1", type: "alpha_item", title: "A", subtitle: "", area: null, href: "/alpha?item=1", score: 50 },
    { id: "beta_item:1", type: "beta_item", title: "B", subtitle: "", area: null, href: "/beta?item=1", score: 60 },
  ];
  assert.deepEqual(filterAvailable(fxResults, fx).map((r) => r.id), ["alpha_item:1"]);
});

test("dashboard: disabled module widgets are absent, fetch skipped, storage preserved", () => {
  assert.deepEqual(availableWidgets(DEFAULTS), WIDGETS, "výchozí stav beze změny");
  assert.deepEqual(availableWidgets(DEFAULTS), WIDGETS);
  const wotMffOff = availableWidgets(off("wot", "mff")).map((d) => d.id);
  assert.ok(!wotMffOff.includes("games"));
  assert.ok(availableWidgets(off("wot")).some((d) => d.id === "games"), "Hry zůstanou s MFF");
  assert.ok(!availableWidgets(off("finance")).some((d) => d.id === "finance"));
  assert.ok(availableWidgets(off("finance")).some((d) => d.id === "key_metrics"), "Klíčová čísla zůstanou s Prací");

  // uložené vlastní rozložení: Finance skryté a malé, pak se modul vypne a uživatel upraví dashboard
  const stored = serializeLayout(setWidgetVisible(defaultLayout(), "finance", false));
  const available = availableWidgets(off("finance"));
  const layout = parseStoredLayout(stored, available);
  assert.ok(!layout.widgets.some((w) => w.id === "finance"), "nevykreslí se ani mezi skrytými");
  const edited = setWidgetVisible(layout, "games", false);
  const saved = preserveUnavailable(edited, stored, available);
  const finance = saved.widgets.find((w) => w.id === "finance");
  assert.deepEqual([finance.visible, finance.size], [false, "small"], "uložené nastavení přežije úpravu");
  assert.equal(saved.widgets.findIndex((w) => w.id === "finance"), saved.widgets.findIndex((w) => w.id === "work") + 1, "na původním místě");
  // opětovné zapnutí: widget se vrátí s uloženou viditelností (rozumné výchozí chování)
  const back = parseStoredLayout(serializeLayout(saved));
  assert.equal(back.widgets.find((w) => w.id === "finance").visible, false);
  assert.equal(back.widgets.find((w) => w.id === "games").visible, false);
  // bez uložených dat po zapnutí = výchozí rozložení
  assert.deepEqual(parseStoredLayout(null), defaultLayout());

  // fetch: widgety vypnutých modulů v rozložení nejsou → nic nenačítají (GET /dashboard jen kvůli jiným widgetům)
  const moduleWidgets = WIDGETS.filter((d) => d.modules);
  const allModulesOff = parseStoredLayout(serializeLayout(defaultLayout(moduleWidgets)), availableWidgets(off(...EXISTING), moduleWidgets));
  assert.deepEqual(allModulesOff.widgets, []);
  assert.equal(needsDashboardData(allModulesOff), false);
});

test("dashboard fixture module: enabled widget appears, disabled widget is ignored", () => {
  const defs = [
    ...WIDGETS,
    { id: "alpha_widget", title: "Alfa", area: null, defaultVisible: true, defaultOrder: 115, defaultSize: "small", allowedSizes: ["small"], usesDashboardData: false, modules: ["alpha"] },
    { id: "beta_widget", title: "Beta", area: null, defaultVisible: true, defaultOrder: 116, defaultSize: "small", allowedSizes: ["small"], usesDashboardData: true, modules: ["beta"] },
  ];
  const ids = availableWidgets(createModuleAccess({ alpha: true, beta: false }, FIXTURES), defs).map((d) => d.id);
  assert.ok(ids.includes("alpha_widget"));
  assert.ok(!ids.includes("beta_widget"));
});

test("Quick Add: disabled module kinds are not offered and a parse of them becomes unknown", () => {
  assert.deepEqual(availableKinds(DEFAULTS), QUICK_ADD_KINDS);
  assert.deepEqual(examplesFor(DEFAULTS), QUICK_ADD_EXAMPLES);
  assert.equal(kindsHint(DEFAULTS), "Umím připomínku, výdaj nebo příjem, odpracované hodiny a školní test nebo úkol.");
  assert.equal(promptHint(DEFAULTS), "Napiš, co chceš přidat – připomínku, výdaj, práci nebo školní termín.");
  const noFinance = off("finance");
  assert.deepEqual(availableKinds(noFinance), ["reminder", "work", "exam", "assignment"]);
  assert.ok(examplesFor(noFinance).every((ex) => ex.kind !== "finance"));
  assert.ok(!kindsHint(noFinance).includes("finance"));
  const parsed = { kind: "finance", confidence: "high", fields: { amount: 189.9 }, display: { title: "Oběd", subtitle: "", area: "finance" }, warnings: [], needs_input: [], errors: [], ready: true };
  assert.equal(gateParse(parsed, DEFAULTS), parsed);
  const gated = gateParse(parsed, noFinance);
  assert.deepEqual([gated.kind, gated.ready, gated.fields], ["unknown", false, {}]);
  // připomínka je jádro
  assert.ok(availableKinds(off(...EXISTING)).includes("reminder"));
  // budoucí modul (Food) zatím parser nemá – brána ale funguje pro jeho druhy
  assert.equal(createModuleAccess({ alpha: true }, FIXTURES).allowsQuickAddKind("alpha_meal"), true);
  assert.equal(createModuleAccess({ beta: false }, FIXTURES).allowsQuickAddKind("beta_meal"), false);
});

test("Today and AI context: canonical capability answers", () => {
  const fx = createModuleAccess({ alpha: true, beta: false }, FIXTURES);
  assert.equal(fx.allows("alpha", "today"), true);
  assert.equal(fx.allows("beta", "today"), false);
  assert.equal(fx.allowsEntity("beta_item", "today"), false);
  assert.equal(fx.allowsEntity("notification", "today"), true, "jádro");
  assert.equal(fx.allows("alpha", "ai_context"), true);
  assert.equal(fx.allows("beta", "ai_context"), false);
  assert.equal(fx.allows("gamma", "ai_context"), false);
  // WoT a MFF do Dnes nepřispívají (nemají datované záznamy) – schopnost se neodvozuje z flagu
  assert.equal(DEFAULTS.allows("wot", "today"), false);
  assert.equal(DEFAULTS.allows("school", "today"), true);
  assert.equal(off("school").allows("school", "today"), false);
});

test("MRK-7 main-era: Replay Library and milestones belong to WoT", () => {
  const off = createModuleAccess({ wot: false });
  const on = createModuleAccess({});
  // stránky knihovny replayů a deep linky z vyhledávání
  for (const path of ["/wot", "/wot/replays", "/wot/replays?replay=1"]) {
    assert.equal(allowsHref(on, path), true, path);
    assert.equal(allowsHref(off, path), false, path);
  }
  assert.equal(off.moduleForPath("/wot/replays")?.id, "wot");
  // výsledky Ctrl+K: replay i grind zmizí, jádro a jiné moduly zůstanou
  const results = [
    { id: "wot_replay:1", type: "wot_replay", title: "Progetto 65", subtitle: "Replay · Útesy", area: "wot", href: "/wot/replays?replay=1", score: 85 },
    { id: "wot_grind:2", type: "wot_grind", title: "Kranvagn", subtitle: "Grind", area: "wot", href: "/wot?grind=2", score: 80 },
    { id: "exam:3", type: "exam", title: "test", subtitle: "Test", area: "school", href: "/school?exam=3", score: 70 },
  ];
  assert.deepEqual(filterAvailable(results, on).map((r) => r.id), ["wot_replay:1", "wot_grind:2", "exam:3"]);
  assert.deepEqual(filterAvailable(results, off).map((r) => r.id), ["exam:3"]);
  assert.equal(off.allowsEntity("wot_replay", "search"), false, "typ je ve vlastnictví WoT, ne jádra");
  // core trasy hlavního menu (Dnes, AI s Jarvisem) zůstávají
  for (const path of ["/", "/today", "/ai", "/reminders"]) assert.equal(allowsHref(off, path), true, path);
});
