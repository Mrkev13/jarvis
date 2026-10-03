// Vizuální a přístupnostní kontrola migrovaných stránek (Roadmap 4A).
//
// Předpoklady: `npm run build`, pak v jiných terminálech
//   node scripts/mock-api.mjs            (fixtures, žádný Groq)
//   npx next start -p 3000 -H 127.0.0.1
// Spuštění: node scripts/ui-check.mjs   (Playwright: PLAYWRIGHT_MODULE=/cesta/k/playwright/index.mjs,
//           jinak `import("playwright")`; prohlížeč: PLAYWRIGHT_CHROMIUM=/cesta/k/chromium volitelně)
// Výstup: screenshoty do scripts/.ui-check/ (gitignore) a seznam kontrol; exit 1 při selhání.
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BASE = process.env.UI_BASE_URL || "http://127.0.0.1:3000";
const OUT = fileURLToPath(new URL("./.ui-check/", import.meta.url));  // .pathname dává na Windows /C:/…
mkdirSync(OUT, { recursive: true });

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "✓" : "✗"} ${name}${detail ? ` – ${detail}` : ""}`);
}

async function open(path, { width = 1440, height = 1000, scheme = "dark", reducedMotion = "no-preference", delayPath } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: scheme, reducedMotion });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  if (delayPath) {
    await page.route(`**${delayPath}`, async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
  }
  await page.goto(BASE + path, { waitUntil: delayPath ? "domcontentloaded" : "networkidle" });
  if (!delayPath) await page.waitForTimeout(700);
  return { ctx, page, errors };
}

const PAGES = [
  ["/", "dashboard"],
  ["/reminders", "reminders"],
  ["/review", "weekly-review"],
];
const WIDTHS = [
  [1920, "wide"],
  [1366, "laptop"],
  [820, "tablet"],
  [390, "mobile"],
];

// 1) Rozložení: šířky, jeden <h1>, žádné horizontální přetečení, žádné chyby JS, jeden zvonek.
for (const [path, name] of PAGES) {
  for (const [width, label] of WIDTHS) {
    const { ctx, page, errors } = await open(path, { width });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`${name} @${label}: bez horizontálního přetečení`, overflow <= 0, `${overflow}px`);
    const h1 = await page.locator("h1").count();
    check(`${name} @${label}: právě jeden h1`, h1 === 1, String(h1));
    const bells = await page.locator('button[aria-label^="Notifikace"]').count();
    check(`${name} @${label}: jeden zvonek notifikací`, bells === 1, String(bells));
    check(`${name} @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
    if (["wide", "mobile"].includes(label) || name !== "dashboard") {
      await page.screenshot({ path: `${OUT}${name}-${label}.png`, fullPage: true });
    }
    await ctx.close();
  }
}

// 2) Motiv systému: aplikace zůstává tmavá i při světlém motivu OS.
for (const scheme of ["light", "dark"]) {
  const { ctx, page } = await open("/", { scheme });
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  check(`dashboard (${scheme} OS): tmavé pozadí`, /rgb\(7, 9, 13\)|lab\(/.test(bg) && !bg.includes("255, 255, 255"), bg);
  await page.screenshot({ path: `${OUT}dashboard-${scheme}-os.png` });
  await ctx.close();
}

// 3) Načítání: skeleton/role=status, žádný prázdný stav před daty.
{
  const { ctx, page } = await open("/", { delayPath: "/dashboard" });
  await page.waitForTimeout(400);
  const statuses = await page.locator('[role="status"]').count();
  const prematureEmpty = await page.getByText("Žádné blížící se termíny.").count();
  check("dashboard: při načítání skeleton (role=status)", statuses > 0, String(statuses));
  check("dashboard: žádný prázdný stav před načtením", prematureEmpty === 0);
  await ctx.close();
}

// 4) ConfirmDialog: role/aria, výchozí fokus, past na fokus, Escape, busy stav bez dvojího odeslání.
{
  const { ctx, page } = await open("/reminders");
  await page.getByRole("button", { name: "Zrušit", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  check("dialog: role=dialog + aria-modal", (await dialog.count()) === 1 && (await dialog.getAttribute("aria-modal")) === "true");
  check("dialog: má popisek (aria-labelledby)", Boolean(await dialog.getAttribute("aria-labelledby")));
  await page.waitForTimeout(50);
  const focused = await page.evaluate(() => document.activeElement?.textContent?.trim());
  check("dialog: destruktivní akce → fokus na „Ponechat“", focused === "Ponechat", String(focused));
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const inside = await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')));
  check("dialog: Tab zůstává v dialogu", inside);
  await page.keyboard.press("Escape");
  check("dialog: Escape zavře", (await dialog.count()) === 0);
  await page.getByRole("button", { name: "Zrušit", exact: true }).first().click();
  const confirm = page.getByRole("button", { name: "Zrušit připomínku" });
  await confirm.click();
  await page.waitForTimeout(100);
  const busyBtn = page.locator('[role="dialog"] button[aria-busy="true"]');
  check("dialog: busy stav po potvrzení", (await busyBtn.count()) === 1);
  check("dialog: potvrzení je během busy zakázané", await busyBtn.isDisabled());
  await page.keyboard.press("Escape");
  check("dialog: Escape během busy nezavře", (await dialog.count()) === 1);
  await page.screenshot({ path: `${OUT}reminders-dialog-busy.png` });
  await page.waitForTimeout(1500);
  check("dialog: po dokončení se zavře", (await dialog.count()) === 0);
  await ctx.close();
}

// 5) Omezený pohyb: žádné vstupní animace, skeleton bez pulzu, HUD puls statický.
{
  const { ctx, page } = await open("/reminders", { reducedMotion: "reduce" });
  const anims = await page.evaluate(() => {
    const card = document.querySelector(".motion-card");
    const live = document.querySelector(".status-pulse-live");
    return {
      card: card ? getComputedStyle(card).animationName : "none",
      pulse: live ? getComputedStyle(live, "::after").animationName : "none",
    };
  });
  check("reduced motion: karty bez animace", anims.card === "none", anims.card);
  check("reduced motion: HUD puls bez animace", anims.pulse === "none", anims.pulse);
  await ctx.close();
}

// 6) Klávesnice: viditelný fokus na první položce navigace.
{
  const { ctx, page } = await open("/review");
  for (let i = 0; i < 3; i += 1) await page.keyboard.press("Tab");
  const ring = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return "";
    const cs = getComputedStyle(el);
    return `${cs.boxShadow} | ${cs.outlineStyle}`;
  });
  check("klávesnice: viditelný fokus", ring !== "" && (!ring.startsWith("none") || !ring.endsWith("none")), ring);
  await ctx.close();
}

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} kontrol prošlo. Screenshoty: ${OUT}`);
process.exit(failed.length ? 1 : 0);
