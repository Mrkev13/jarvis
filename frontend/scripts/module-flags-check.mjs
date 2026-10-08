// Prohlížečová kontrola feature flagů modulů (Roadmap 6C) – doplněk ui-check.mjs.
//
// Flagy frontendu se vkládají při buildu, proto se kontrola pouští proti dvěma buildům:
//   výchozí:     npm run build                                   → node scripts/module-flags-check.mjs
//   s vypnutými: NEXT_PUBLIC_MODULE_WOT_ENABLED=false NEXT_PUBLIC_MODULE_FINANCE_ENABLED=false npm run build
//                → UI_FLAGS_DISABLED=wot,finance node scripts/module-flags-check.mjs
// Předpoklady jako ui-check: node scripts/mock-api.mjs + npx next start -p 3000 -H 127.0.0.1 (žádný Groq).
// Mock API vrací data všech modulů – kontrola tak dokazuje i pojistku frontendu (filtr výsledků a rozboru).
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BASE = process.env.UI_BASE_URL || "http://127.0.0.1:3000";
const MOCK_API = process.env.MOCK_API_URL || "http://127.0.0.1:8000";
const OUT = fileURLToPath(new URL("./.ui-check/", import.meta.url));
mkdirSync(OUT, { recursive: true });
const DISABLED = new Set((process.env.UI_FLAGS_DISABLED || "").split(",").map((s) => s.trim()).filter(Boolean));
const MODE = DISABLED.size ? `off:${[...DISABLED].join("+")}` : "default";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "✓" : "✗"} [${MODE}] ${name}${detail ? ` – ${detail}` : ""}`);
}

const MODULE_PAGES = { school: "/school", work: "/work", finance: "/finance", goals: "/goals", wot: "/wot", mff: "/mff" };
const NAV_TOTAL = 14;

async function open(path, { width = 1366, height = 900, setup } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: "dark", hasTouch: width < 500 });
  const page = await ctx.newPage();
  const errors = [];
  const apiCalls = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("request", (r) => {
    if (r.url().startsWith(MOCK_API)) apiCalls.push(new URL(r.url()).pathname);
  });
  if (setup) await setup(page);
  await page.goto(BASE + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  return { ctx, page, errors, apiCalls };
}

const navHrefs = (page, scope) => page.locator(`${scope} nav[aria-label="Hlavní navigace"] a`).evaluateAll((as) => as.map((a) => a.getAttribute("href")));

// 1) Navigace: desktop + mobilní menu
{
  const { ctx, page, errors } = await open("/");
  const hrefs = await navHrefs(page, "aside");
  check("navigace desktop: počet odkazů", hrefs.length === NAV_TOTAL - DISABLED.size, String(hrefs.length));
  for (const [id, href] of Object.entries(MODULE_PAGES)) {
    check(`navigace desktop: ${href} ${DISABLED.has(id) ? "chybí" : "je vidět"}`, hrefs.includes(href) === !DISABLED.has(id));
  }
  const dead = await page.locator("a[href]").evaluateAll((as, off) => as.map((a) => a.getAttribute("href")).filter((h) => off.some((p) => h === p || h.startsWith(`${p}?`) || h.startsWith(`${p}/`))), [...DISABLED].map((id) => MODULE_PAGES[id]));
  check("dashboard: žádný odkaz na vypnutý modul", dead.length === 0, dead.join(", "));
  check("dashboard: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: `${OUT}flags-${MODE}-dashboard.png`, fullPage: true });
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/", { width: 390, height: 844 });
  await page.getByRole("button", { name: "Otevřít menu" }).click();
  await page.waitForTimeout(400);
  const hrefs = await navHrefs(page, "[data-drawer-nav]");
  check("mobilní menu: počet odkazů", hrefs.length === NAV_TOTAL - DISABLED.size, String(hrefs.length));
  for (const [id, href] of Object.entries(MODULE_PAGES)) {
    check(`mobilní menu: ${href} ${DISABLED.has(id) ? "chybí" : "je vidět"}`, hrefs.includes(href) === !DISABLED.has(id));
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check("mobil: bez horizontálního přetečení", overflow <= 0, `${overflow}px`);
  check("mobil: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: `${OUT}flags-${MODE}-mobile-menu.png` });
  await ctx.close();
}

// 2) Globální vyhledávání (mock /search vrací i záznamy vypnutých modulů → filtruje frontend)
{
  const { ctx, page, errors } = await open("/");
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  const input = dialog.getByRole("combobox", { name: "Hledat stránku nebo záznam" });
  const navCount = await dialog.getByRole("group", { name: "Navigace" }).getByRole("option").count();
  check("hledání: navigace bez stránek vypnutých modulů", navCount === NAV_TOTAL - DISABLED.size, String(navCount));
  for (const [q, group, module] of [["tvp", "World of Tanks", "wot"], ["obed", "Finance", "finance"], ["luna", "Marvel FF", "mff"]]) {
    await input.fill(q);
    await page.waitForTimeout(600);
    const hits = await dialog.getByRole("group", { name: group }).getByRole("option").count();
    check(`hledání: „${q}“ → ${group} ${DISABLED.has(module) ? "skryto" : "nalezeno"}`, DISABLED.has(module) ? hits === 0 : hits >= 1, String(hits));
  }
  await input.fill("tanky");
  await page.waitForTimeout(500);
  const wotPage = await dialog.getByRole("option", { name: /^World of Tanks/ }).count();
  check(`hledání: stránka WoT podle klíčového slova ${DISABLED.has("wot") ? "skryta" : "nalezena"}`, (wotPage >= 1) === !DISABLED.has("wot"), String(wotPage));
  await input.fill("prace");
  await page.waitForTimeout(500);
  const first = (await dialog.getByRole("option").first().innerText()).split("\n")[0];
  check("hledání: současné moduly beze změny („prace“ → Práce)", first === "Práce", first);
  check("hledání: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: `${OUT}flags-${MODE}-search.png` });
  await ctx.close();
}

// 3) Dashboard: widgety, části smíšených widgetů, uložené rozložení
const STORED = {
  version: 1,
  widgets: [
    "daily_briefing", "weekly_review", "today", "attention", "key_metrics", "goals", "upcoming", "work", "finance", "games", "quick_actions",
  ].map((id, i) => ({ id, visible: true, order: (i + 1) * 10, size: { daily_briefing: "large", weekly_review: "small", today: "large", attention: "small", key_metrics: "full", games: "full", quick_actions: "full", finance: "medium" }[id] ?? "small" })),
};
{
  const { ctx, page, errors } = await open("/", {
    setup: (p) => p.addInitScript((raw) => {
      if (!sessionStorage.getItem("seeded")) {
        localStorage.setItem("standa-hub:dashboard-layout:v1", raw);
        sessionStorage.setItem("seeded", "1");
      }
    }, JSON.stringify(STORED)),
  });
  const finance = DISABLED.has("finance");
  const wot = DISABLED.has("wot");
  check(`dashboard: widget Finance ${finance ? "se nevykreslí" : "je vidět"}`, ((await page.locator("#finance-title").count()) === 1) === !finance);
  check(`dashboard: metrika Bilance ${finance ? "chybí" : "je vidět"}`, ((await page.getByText("Bilance", { exact: true }).count()) >= 1) === !finance);
  check(`dashboard: rychlá akce „Přidat výdaj“ ${finance ? "chybí" : "je vidět"}`, ((await page.getByRole("link", { name: /Přidat výdaj/ }).count()) === 1) === !finance);
  const games = page.locator('[aria-labelledby="games-title"]');
  check("dashboard: widget Hry je vidět (MFF zapnuté)", (await page.locator("#games-title").count()) === 1);
  check(`dashboard: část World of Tanks ve Hrách ${wot ? "chybí" : "je vidět"}`, ((await games.getByText("World of Tanks", { exact: true }).count()) === 1) === !wot);
  check("dashboard: část Marvel Future Fight ve Hrách je vidět", (await games.getByText("Marvel Future Fight", { exact: true }).count()) === 1);
  // úprava rozložení s vypnutým modulem nesmaže jeho uložené nastavení
  await page.getByRole("button", { name: "Upravit dashboard" }).click();
  await page.waitForTimeout(300);
  const hiddenList = page.getByRole("list", { name: "Skryté widgety" });
  check("dashboard: vypnutý widget není ani mezi skrytými", finance ? (await hiddenList.getByRole("button", { name: /Finance/ }).count()) === 0 : true);
  await page.getByRole("button", { name: /Skrýt/ }).first().click();
  await page.waitForTimeout(300);
  const saved = JSON.parse(await page.evaluate(() => localStorage.getItem("standa-hub:dashboard-layout:v1")));
  const fin = saved.widgets.find((w) => w.id === "finance");
  check("dashboard: uložený záznam Finance přežije úpravu (velikost i viditelnost)", Boolean(fin && fin.size === "medium" && fin.visible === true), JSON.stringify(fin));
  check("dashboard: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: `${OUT}flags-${MODE}-dashboard-edit.png`, fullPage: true });
  await ctx.close();
}

// 4) Přímá adresa modulu: vypnutý = čistý stav „Modul není dostupný", žádná volání jeho API
for (const [id, path] of Object.entries(MODULE_PAGES).filter(([m]) => m === "wot" || m === "finance" || m === "mff")) {
  for (const width of [1366, 390]) {
    const { ctx, page, errors, apiCalls } = await open(`${path}${id === "wot" ? "?grind=4" : ""}`, { width });
    const off = DISABLED.has(id);
    const unavailable = await page.getByTestId("module-unavailable").count();
    const h1 = await page.locator("h1").allTextContents();
    const moduleCalls = apiCalls.filter((p) => p.startsWith(`${path}/`));
    if (off) {
      check(`${path} @${width}: stav „Modul není dostupný“`, unavailable === 1 && h1.length === 1 && h1[0] === "Modul není dostupný", h1.join("|"));
      check(`${path} @${width}: stránka se nepřipojí (žádné ${path}/* API)`, moduleCalls.length === 0, moduleCalls.join(", "));
      check(`${path} @${width}: odkaz zpět na Řídicí centrum`, (await page.getByRole("link", { name: /Zpět na Řídicí centrum/ }).count()) === 1);
    } else {
      check(`${path} @${width}: stránka modulu se otevře`, unavailable === 0 && h1.length === 1 && h1[0] !== "Modul není dostupný", h1.join("|"));
      check(`${path} @${width}: načte svá data`, moduleCalls.length >= 1, String(moduleCalls.length));
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`${path} @${width}: bez přetečení`, overflow <= 0, `${overflow}px`);
    check(`${path} @${width}: bez chyb JS`, errors.length === 0, errors.join(" | "));
    if (width === 390) await page.screenshot({ path: `${OUT}flags-${MODE}${path.replace("/", "-")}-mobile.png` });
    await ctx.close();
  }
}

// 5) Rychlé přidání: příklady a rozbor (mock vrací „finance" → frontend ho bere jako „nerozumím")
{
  const { ctx, page, errors } = await open("/");
  await page.keyboard.press("Control+Shift+K");
  const dialog = page.getByRole("dialog", { name: "Rychlé přidání" });
  const finance = DISABLED.has("finance");
  const exampleFinance = await dialog.getByRole("list", { name: "Příklady" }).getByRole("button", { name: "oběd 189,90 Kč" }).count();
  check(`quick add: příklad Financí ${finance ? "chybí" : "je vidět"}`, (exampleFinance === 1) === !finance);
  await dialog.getByLabel("Co chceš přidat?").fill("oběd 189,90 Kč");
  await page.waitForTimeout(500);
  const unknown = await dialog.getByTestId("quick-add-unknown").count();
  const preview = await dialog.getByTestId("quick-add-preview").count();
  check(`quick add: „oběd 189,90 Kč“ ${finance ? "nevytvoří Finance (nerozumím)" : "→ náhled Financí"}`, finance ? unknown === 1 && preview === 0 : preview === 1, `${unknown}/${preview}`);
  check(`quick add: tlačítko Uložit ${finance ? "není" : "je"} k dispozici`, finance ? (await dialog.getByTestId("quick-add-save").count()) === 0 || (await dialog.getByTestId("quick-add-save").isDisabled()) : true);
  await dialog.getByLabel("Co chceš přidat?").fill("zítra fyzio v 17:00");
  await page.waitForTimeout(500);
  check("quick add: připomínka (jádro) funguje vždy", (await dialog.getByTestId("quick-add-preview").getAttribute("data-kind")) === "reminder");
  check("quick add: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: `${OUT}flags-${MODE}-quick-add.png` });
  await ctx.close();
}

// 6) MRK-7: přírůstky mainu – Replay Library, vyhledávání replayů, Quick Add s časem, splnění ve Škole, Jarvis, Dnes
for (const path of ["/wot/replays", "/wot/replays?replay=1"]) {
  const { ctx, page, errors, apiCalls } = await open(path);
  const off = DISABLED.has("wot");
  const unavailable = await page.getByTestId("module-unavailable").count();
  const replayCalls = apiCalls.filter((p) => p.startsWith("/wot/"));
  if (off) {
    check(`${path}: stav „Modul není dostupný“, žádné /wot API`, unavailable === 1 && replayCalls.length === 0, replayCalls.join(", "));
  } else {
    check(`${path}: knihovna replayů se otevře`, unavailable === 0 && (await page.locator("h1").innerText()) === "Knihovna replayů" && replayCalls.length >= 1);
    if (path.includes("replay=1")) check(`${path}: detail replaye`, (await page.getByTestId("replay-detail").count()) === 1);
  }
  check(`${path}: bez chyb JS`, errors.length === 0, errors.join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/");
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  await dialog.getByRole("combobox", { name: "Hledat stránku nebo záznam" }).fill("progetto");
  await page.waitForTimeout(700);
  const hits = await dialog.getByRole("option", { name: /Progetto 65/ }).count();
  check(`hledání: replay „progetto“ ${DISABLED.has("wot") ? "skryt" : "nalezen"}`, DISABLED.has("wot") ? hits === 0 : hits >= 1, String(hits));
  check("hledání replayů: bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/");
  check("Jarvis companion je vidět (jádro, nezávisí na modulech)", (await page.getByTestId("jarvis-companion").count()) === 1);
  await page.keyboard.press("Control+Shift+K");
  const dialog = page.getByRole("dialog", { name: "Rychlé přidání" });
  await dialog.getByLabel("Co chceš přidat?").fill("21.10.2026 fyzio od 14 hodin");
  await page.waitForTimeout(600);
  check("quick add: „fyzio od 14 hodin“ = připomínka (MRK-11, jádro)", (await dialog.getByTestId("quick-add-preview").getAttribute("data-kind")) === "reminder");
  check("quick add s časem: bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/school");
  const school = DISABLED.has("school");
  check(`škola: akce Splnit ${school ? "nedostupná" : "je vidět"}`, ((await page.getByRole("button", { name: "Splnit úkol Sada" }).count()) === 1) === !school);
  check("škola: bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/today");
  const dead = await page.locator("main a[href]").evaluateAll((as, off) => as.map((a) => a.getAttribute("href")).filter((h) => off.some((p) => h === p || h.startsWith(`${p}?`) || h.startsWith(`${p}/`))), [...DISABLED].map((id) => MODULE_PAGES[id]));
  check("dnes: žádný odkaz na vypnutý modul", dead.length === 0, dead.join(", "));
  check("dnes: bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
}

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n[${MODE}] ${results.length - failed.length}/${results.length} kontrol prošlo.`);
process.exit(failed.length ? 1 : 0);
