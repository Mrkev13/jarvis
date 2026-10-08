// Prohlížečová kontrola „Co se změnilo" (MRK-28) – doplněk ui-check.mjs.
// Předpoklady jako ui-check: node scripts/mock-api.mjs + npx next start -p 3000 -H 127.0.0.1 (žádný Groq).
//   node scripts/changes-check.mjs
// Ověřuje: obsah a skupiny po dnech, odkazy, období, odvozené filtry modulů, vypnutý modul, obnovení po
// doménové události „z jiného zařízení" (SSE, bez reloadu a bez pollingu), navigaci, mobil a chyby JS.
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BASE = process.env.UI_BASE_URL || "http://127.0.0.1:3000";
const MOCK_API = process.env.MOCK_API_URL || "http://127.0.0.1:8000";
const OUT = fileURLToPath(new URL("./.ui-check/", import.meta.url));
mkdirSync(OUT, { recursive: true });

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});
const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok });
  console.log(`${ok ? "✓" : "✗"} [changes] ${name}${detail ? ` – ${detail}` : ""}`);
}
const calls = async () => (await (await fetch(`${MOCK_API}/__mock/changes/calls`)).json()).length;

async function open(path, { width = 1366, height = 900 } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: "dark", hasTouch: width < 500 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  let navigations = 0;
  page.on("framenavigated", (f) => { if (f === page.mainFrame()) navigations += 1; });
  await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
  await page.getByTestId("change-item").first().waitFor({ timeout: 10000 }).catch(() => undefined);
  await page.waitForTimeout(400);
  return { ctx, page, errors, navigations: () => navigations };
}
const titles = (page) => page.getByTestId("change-item").locator("p.text-sm").allInnerTexts();

await fetch(`${MOCK_API}/__mock/modules/reset`);
await fetch(`${MOCK_API}/__mock/changes/reset`);
{
  const { ctx, page, errors, navigations } = await open("/changes");
  check("nadpis „Co se změnilo“", (await page.locator("h1").innerText()) === "Co se změnilo");
  const t7 = await titles(page);
  check("7 dní: 5 změn, nejnovější první", t7.length === 5 && t7[0].startsWith("Úkol splněn: Sada 4"), t7.join(" | "));
  const headings = await page.locator("section[aria-labelledby^='changes-day-'] h2").allInnerTexts();
  check("skupiny po dnech (Dnes / Včera / datum)", headings.length >= 2 && ["Dnes", "Včera"].includes(headings[0]), headings.join(", "));
  check("odkaz na záznam (deep link)", (await page.getByTestId("change-item").first().locator("a").getAttribute("href")) === "/school?assignment=12");
  check("popisky druhu změny česky", (await page.getByTestId("change-item").first().innerText()).includes("Splněno"));
  const chips = await page.getByRole("group", { name: "Modul" }).getByRole("button").allInnerTexts().catch(() => []);
  check("filtry odvozené z obsahu (jen moduly se změnami)", chips.length === 5 && chips[0].startsWith("Obecné") && !chips.some((c) => c.startsWith("Práce")), chips.join(", "));

  await page.getByRole("group", { name: "Modul" }).getByRole("button", { name: /^Finance/ }).click();
  await page.waitForTimeout(700);
  const onlyFinance = await titles(page);
  check("filtr modulu: jen Finance", onlyFinance.length === 1 && onlyFinance[0].startsWith("Výdaj"), onlyFinance.join(" | "));
  await page.getByRole("group", { name: "Modul" }).getByRole("button", { name: /^Finance/ }).click();
  await page.waitForTimeout(700);

  await page.getByLabel("Období").selectOption("24h");
  await page.waitForTimeout(700);
  check("období 24 h: 3 změny", (await titles(page)).length === 3, String((await titles(page)).length));
  await page.getByLabel("Období").selectOption("30d");
  await page.waitForTimeout(700);
  const t30 = await titles(page);
  check("období 30 dní: 6 změn včetně smazané směny", t30.length === 6 && t30.includes("Směna smazána"), String(t30.length));
  const deleted = page.getByTestId("change-item").filter({ hasText: "Směna smazána" });
  check("smazaný záznam bez odkazu", (await deleted.locator("a").count()) === 0);
  await page.getByLabel("Období").selectOption("7d");
  await page.waitForTimeout(700);

  // jiné zařízení splní úkol → doménová událost → stránka se obnoví sama
  const before = await calls();
  const navBefore = navigations();
  await page.evaluate(() => { window.__noReload = true; });
  await fetch(`${MOCK_API}/__mock/changes/complete`);
  await page.getByText(/Úkol z telefonu/).waitFor({ timeout: 4000 }).catch(() => undefined);
  const kept = await page.evaluate(() => window.__noReload === true);
  check("SSE: nová změna z jiného zařízení se objeví bez reloadu", (await page.getByText(/Úkol z telefonu/).count()) === 1 && kept && navigations() === navBefore, `reload=${!kept}, navigace +${navigations() - navBefore}`);
  const afterEvent = await calls();
  check("SSE: právě jedno nové načtení na událost", afterEvent - before === 1, String(afterEvent - before));
  await page.waitForTimeout(3500);
  check("bez pollingu: v klidu žádné další dotazy", (await calls()) === afterEvent, String((await calls()) - afterEvent));

  const nav = await page.locator('aside nav[aria-label="Hlavní navigace"] a').evaluateAll((as) => as.map((a) => [a.getAttribute("href"), a.textContent?.trim()]));
  const idx = nav.findIndex(([h]) => h === "/changes");
  check("navigace: „Co se změnilo“ před Aktivitou", idx >= 0 && nav[idx + 1]?.[0] === "/activity" && nav[idx][1]?.includes("Co se změnilo"), JSON.stringify(nav[idx]));
  check("aktivní položka navigace", (await page.locator('aside a[href="/changes"][aria-current="page"]').count()) === 1);
  await page.screenshot({ path: `${OUT}changes-desktop.png`, fullPage: true });
  check("bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
}
// vypnutý modul se v přehledu neukáže (ani ve filtrech)
{
  await fetch(`${MOCK_API}/__mock/modules?disabled=finance`);
  const { ctx, page, errors } = await open("/changes");
  const t = await titles(page);
  const chips = await page.getByRole("group", { name: "Modul" }).getByRole("button").allInnerTexts().catch(() => []);
  check("vypnutý modul: žádné změny Financí ani filtr", !t.some((x) => x.startsWith("Výdaj")) && !chips.some((c) => c.startsWith("Finance")), chips.join(", "));
  check("vypnutý modul: bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
  await fetch(`${MOCK_API}/__mock/modules/reset`);
}
// mobil 375 px: bez vodorovného posunu, položky čitelné
{
  const { ctx, page, errors } = await open("/changes", { width: 375, height: 812 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check("mobil: bez vodorovného posunu", overflow <= 0, String(overflow));
  check("mobil: položky viditelné", (await page.getByTestId("change-item").count()) >= 5);
  await page.screenshot({ path: `${OUT}changes-mobile.png`, fullPage: true });
  check("mobil: bez chyb JS", errors.length === 0, errors.join(" | "));
  await ctx.close();
}
// chyba API → chybový stav se „Zkusit znovu"
{
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage();
  await page.route(`${MOCK_API}/changes?*`, (route) => route.fulfill({ status: 500, body: JSON.stringify({ detail: "Simulovaná chyba." }) }));
  await page.goto(`${BASE}/changes`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /Zkusit znovu/ }).waitFor({ timeout: 6000 }).catch(() => undefined);
  check("chyba API: chybový stav s možností zkusit znovu", (await page.getByRole("button", { name: /Zkusit znovu/ }).count()) >= 1);
  await ctx.close();
}

await fetch(`${MOCK_API}/__mock/changes/reset`);
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n[changes] ${results.length - failed.length}/${results.length} kontrol prošlo.`);
process.exit(failed.length ? 1 : 0);
