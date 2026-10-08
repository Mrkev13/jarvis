// MRK-21: prohlížečová kontrola Návyků proti SKUTEČNÉMU backendu (ne mock) – založení, splnění, přeskočení,
// odvozené „vynecháno", akce z Dnes, vyhledávání, widget, vypnutí/zapnutí v Nastavení bez ztráty dat, mobil.
//
// Předpoklady (čerstvá scratch DB, žádný Groq):
//   cd backend && DATABASE_URL=sqlite+pysqlite:////tmp/hab.db AUTH_PIN_HASH= SCHEDULER_ENABLED=false \
//     REMINDERS_CHECK_ENABLED=false DAILY_BRIEFING_ENABLED=false WEEKLY_REVIEW_ENABLED=false \
//     GROQ_API_KEY=offline GROQ_BASE_URL=http://127.0.0.1:9/v1 uvicorn main:app --port 8000
//   seed: návyk „Čtení" (duration, cíl 20 min) založený před 3 dny, např.
//     sqlite3 /tmp/hab.db "insert into habits (name,kind,target_value,unit,active,created_at)
//       values ('Čtení','duration',20,'min',1,datetime('now','-3 days'))"
//   cd frontend && npm run build && npx next start -p 3000 -H 127.0.0.1
// Spuštění: node modules/habits/browser-check.mjs (PLAYWRIGHT_MODULE / PLAYWRIGHT_CHROMIUM jako ui-check).
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const BASE = process.env.UI_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const OUT = fileURLToPath(new URL("../../scripts/.ui-check/", import.meta.url));
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log(`${ok ? "✓" : "✗"} ${name}${detail ? " – " + detail : ""}`); };
async function open(path, width = 1366) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: "dark", hasTouch: width < 500 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  return { ctx, page, errors };
}
const api = async (p) => (await fetch(API + p)).json();

// 1) /habits: vytvořit Rehab, splnit; vytvořit Skincare, přeskočit; Čtení má vynechané dny
{
  const { ctx, page, errors } = await open("/habits");
  check("habits: stránka, jeden h1", (await page.locator("h1").allTextContents()).join() === "Návyky");
  const row = (name) => page.locator("li").filter({ has: page.getByTestId("habit-name").getByText(name, { exact: true }) });
  for (const name of ["Rehab", "Skincare"]) {
    await page.getByLabel("Název").fill(name);
    await page.getByRole("button", { name: "Přidat návyk" }).click();
    await page.waitForTimeout(600);
  }
  check("habits: Rehab a Skincare vytvořeny", (await row("Rehab").count()) === 1 && (await row("Skincare").count()) === 1);
  await page.getByRole("button", { name: "Splnit návyk: Rehab" }).click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "Přeskočit návyk: Skincare" }).click();
  await page.waitForTimeout(600);
  check("habits: Rehab dnes splněno", (await row("Rehab").getByTestId("habit-state").innerText()) === "splněno");
  check("habits: Skincare dnes přeskočeno", (await row("Skincare").getByTestId("habit-state").innerText()) === "přeskočeno");
  const missed = await row("Čtení").locator('[data-history-state="missed"]').count();
  check("habits: Čtení (založeno před 3 dny) má vynechané dny", missed === 3, String(missed));
  check("habits: Čtení dnes čeká", (await row("Čtení").getByTestId("habit-state").innerText()) === "čeká");
  check("habits: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: OUT + "habits-page.png", fullPage: true });
  await ctx.close();
}

// 2) Dnes: návyky v časové ose, akce Splněno z Dnes (obecná cesta modulu)
{
  const { ctx, page, errors } = await open("/today");
  const btn = page.getByRole("button", { name: "Splnit návyk: Čtení" });
  check("dnes: Čtení s akcí Splněno", (await btn.count()) === 1);
  check("dnes: Čtení s akcí Přeskočit", (await page.getByRole("button", { name: "Přeskočit návyk: Čtení" }).count()) === 1);
  check("dnes: Rehab bez akcí (hotovo)", (await page.getByRole("button", { name: "Splnit návyk: Rehab" }).count()) === 0 && (await page.locator('[data-item^="habit:"]').filter({ hasText: "Rehab" }).count()) === 1);
  await page.screenshot({ path: OUT + "today-before.png", fullPage: true });
  await btn.click();
  await page.waitForTimeout(900);
  const notice = await page.locator("[data-today-notice]").innerText().catch(() => "");
  check("dnes: hláška po splnění", /Čtení/.test(notice) && /splněný/.test(notice), notice);
  const h = (await api("/habits")).active.find((x) => x.name === "Čtení");
  check("dnes: zápis přes endpoint modulu", h.today.state === "done");
  check("dnes: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: OUT + "today-after.png", fullPage: true });
  await ctx.close();
}

// 3) Vyhledávání + dashboard widget (skrytý ve výchozím stavu, jde zobrazit)
{
  const { ctx, page, errors } = await open("/");
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  await dialog.getByRole("combobox").fill("rehab");
  await page.waitForTimeout(800);
  check("hledání: Rehab ve skupině Návyky", (await dialog.getByRole("group", { name: "Návyky" }).getByRole("option", { name: /^Rehab/ }).count()) === 1);
  await page.keyboard.press("Escape");
  check("dashboard: widget Návyky ve výchozím stavu skrytý", (await page.getByTestId("habits-widget").count()) === 0);
  await page.getByRole("button", { name: "Upravit dashboard" }).click();
  await page.getByRole("button", { name: "Zobrazit widget: Návyky" }).click();
  await page.getByRole("button", { name: "Hotovo" }).click();
  await page.waitForTimeout(800);
  const w = await page.getByTestId("habits-widget").innerText().catch(() => "");
  check("dashboard: widget Návyky ukazuje dnešek", /2\s*\/\s*3/.test(w), w.replace(/\n/g, " "));
  check("dashboard: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: OUT + "dashboard.png", fullPage: true });
  await ctx.close();
}

// 4) Vypnout v Nastavení → zmizí bez ztráty dat → zapnout → data zpět
const before = (await api("/habits")).active.length;
{
  const { ctx, page, errors } = await open("/settings");
  await page.getByTestId("module-toggle-habits").click();
  await page.waitForTimeout(800);
  check("nastavení: Návyky vypnuto", (await page.getByTestId("module-toggle-habits").getAttribute("aria-checked")) === "false");
  const nav = await page.locator('aside nav[aria-label="Hlavní navigace"] a').evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  check("vypnuto: Návyky zmizely z navigace", !nav.includes("/habits"), nav.join(","));
  await page.goto(BASE + "/habits", { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  check("vypnuto: /habits = Modul není dostupný", (await page.getByTestId("module-unavailable").count()) === 1);
  await page.goto(BASE + "/today", { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  check("vypnuto: Dnes bez návyků", (await page.locator('[data-item^="habit:"]').count()) === 0);
  check("vypnuto: API /habits 404", (await fetch(API + "/habits")).status === 404);
  check("vypnuto: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.screenshot({ path: OUT + "habits-disabled.png", fullPage: true });
  await page.goto(BASE + "/settings", { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page.getByTestId("module-toggle-habits").click();
  await page.waitForTimeout(800);
  await page.goto(BASE + "/habits", { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  const after = (await api("/habits")).active;
  check("zapnuto: data zpět beze ztráty", after.length === before && after.find((x) => x.name === "Rehab").today.state === "done");
  check("zapnuto: stránka Návyky zpět", (await page.getByTestId("habit-name").count()) === before);
  await ctx.close();
}

// 5) Mobil 390 px: bez přetečení, Návyky v mobilním menu
{
  const { ctx, page, errors } = await open("/habits", 390);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check("mobil: /habits bez horizontálního přetečení", overflow <= 0, `${overflow}px`);
  await page.getByRole("button", { name: "Otevřít menu" }).click();
  await page.waitForTimeout(400);
  const hrefs = await page.locator('[data-drawer-nav] nav[aria-label="Hlavní navigace"] a').evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  check("mobil: Návyky v menu", hrefs.includes("/habits"));
  check("mobil: bez chyb JS", errors.length === 0, errors.join(" | "));
  await page.keyboard.press("Escape");
  await page.screenshot({ path: OUT + "habits-mobile.png", fullPage: true });
  await ctx.close();
}
await browser.close();
const failed = results.filter((r) => !r).length;
console.log(`\n${results.length - failed}/${results.length} kontrol prošlo.`);
process.exit(failed ? 1 : 0);
