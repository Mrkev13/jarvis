// Vizuální a přístupnostní kontrola migrovaných stránek (Roadmap 4A + 4B).
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

async function open(path, { width = 1440, height = 1000, scheme = "dark", reducedMotion = "no-preference", delayPath, setup } = {}) {
  // Mobilní šířka = dotykové zařízení (pointer: coarse → větší tlačítka, viz Button).
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: scheme, reducedMotion, hasTouch: width < 500 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  if (setup) await setup(page);
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
  // Roadmap 4B
  ["/planner", "planner"],
  ["/school", "school"],
  ["/work", "work"],
  ["/finance", "finance"],
  ["/goals", "goals"],
  ["/activity", "activity"],
  ["/memory", "memory"],
  ["/wot", "wot"],
  ["/mff", "mff"],
];
const ONLY = process.env.UI_CHECK_PAGES ? process.env.UI_CHECK_PAGES.split(",") : null;
const WIDTHS = [
  [1920, "wide"],
  [1366, "laptop"],
  [820, "tablet"],
  [390, "mobile"],
];

// 1) Rozložení: šířky, jeden <h1>, žádné horizontální přetečení, žádné chyby JS, jeden zvonek.
for (const [path, name] of PAGES.filter(([, n]) => !ONLY || ONLY.includes(n))) {
  for (const [width, label] of WIDTHS) {
    const { ctx, page, errors } = await open(path, { width });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`${name} @${label}: bez horizontálního přetečení`, overflow <= 0, `${overflow}px`);
    const h1 = await page.locator("h1").count();
    check(`${name} @${label}: právě jeden h1`, h1 === 1, String(h1));
    const bells = await page.locator('button[aria-label^="Notifikace"]').count();
    check(`${name} @${label}: jeden zvonek notifikací`, bells === 1, String(bells));
    check(`${name} @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
    // Dotykové cíle: myš ≥ 36 px, dotyk ≥ 40 px na výšku (vč. rozšířené plochy ::after).
    const minTarget = width < 500 ? 40 : 36;
    const small = await page.evaluate((min) => {
      const out = [];
      for (const el of document.querySelectorAll("main a[href], main button")) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height || getComputedStyle(el).visibility === "hidden") continue;
        if (el.closest("p, li p") && el.tagName === "A" && !el.className.includes("after:")) continue; // odkaz ve větě
        const after = getComputedStyle(el, "::after");
        const extra = after.content !== "none" && after.position === "absolute" ? -2 * parseFloat(after.top || "0") : 0;
        if (r.height + Math.max(0, extra) < min) out.push(`${el.tagName.toLowerCase()}:${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 24)}(${Math.round(r.height)})`);
      }
      return out;
    }, minTarget);
    check(`${name} @${label}: dotykové cíle ≥ ${minTarget} px`, small.length === 0, small.slice(0, 6).join(", "));
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

// 7) Login: samostatný rám – bez navigace, bez zvonku, bez dotazů na notifikace, PIN s popiskem.
{
  const requests = [];
  const { ctx, page, errors } = await open("/login", {
    setup: async (p) => {
      p.on("request", (r) => requests.push(new URL(r.url()).pathname));
      await p.route("**/auth/session/validate", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ valid: false, auth_disabled: false }) }),
      );
    },
  });
  check("login: bez zvonku notifikací", (await page.locator('button[aria-label^="Notifikace"]').count()) === 0);
  check("login: bez navigace aplikace", (await page.locator("nav").count()) === 0);
  check("login: žádné dotazy na /notifications", !requests.some((r) => r.startsWith("/notifications")), requests.join(","));
  const pin = page.getByLabel("PIN", { exact: true });
  check("login: pole PIN má přístupný popisek", (await pin.count()) === 1);
  check("login: fokus v poli PIN", await pin.evaluate((el) => el === document.activeElement));
  check("login: právě jeden h1", (await page.locator("h1").count()) === 1);
  check("login: bez chyb JS", errors.length === 0, errors.join("; "));
  await page.screenshot({ path: `${OUT}login-wide.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${OUT}login-mobile.png` });
  await ctx.close();
}

// 8) Mobilní menu: dialog, fokus dovnitř, Escape zavře a vrátí fokus, po navigaci fokus na obsah.
{
  const { ctx, page } = await open("/planner", { width: 390, height: 844 });
  const opener = page.getByRole("button", { name: "Otevřít menu" });
  await opener.click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  check("menu: role=dialog s popiskem", (await menu.count()) === 1);
  check("menu: aria-expanded na tlačítku", (await opener.getAttribute("aria-expanded")) === "true");
  await page.waitForTimeout(80);
  const inMenu = await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')));
  check("menu: fokus uvnitř menu", inMenu);
  const current = await page.evaluate(() => document.activeElement?.getAttribute("aria-current"));
  check("menu: fokus na aktuální stránce", current === "page", String(current));
  for (let i = 0; i < 25; i += 1) await page.keyboard.press("Tab");
  check("menu: Tab zůstává v menu", await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))));
  await page.screenshot({ path: `${OUT}menu-mobile.png` });
  await page.keyboard.press("Escape");
  check("menu: Escape zavře", (await menu.count()) === 0);
  await page.waitForTimeout(50);
  check("menu: fokus zpět na tlačítko", await opener.evaluate((el) => el === document.activeElement));
  await opener.click();
  await menu.getByRole("link", { name: "Finance" }).click();
  await page.waitForURL("**/finance");
  await page.waitForTimeout(300);
  check("menu: po navigaci zavřené", (await page.getByRole("dialog").count()) === 0);
  const focusId = await page.evaluate(() => document.activeElement?.id);
  check("menu: po navigaci fokus na hlavní obsah", focusId === "main-content", String(focusId));
  await ctx.close();
}

// 9) Panel notifikací: Drawer s popiskem, Escape, návrat fokusu, české texty.
for (const [width, label] of [[1366, "laptop"], [390, "mobile"]]) {
  const { ctx, page, errors } = await open("/", { width, height: width < 500 ? 844 : 900 });
  const bell = page.locator('button[aria-label^="Notifikace"]');
  await bell.click();
  const panel = page.getByRole("dialog", { name: "Notifikace" });
  await page.waitForTimeout(1500); // generate (POST) + seznam
  check(`notifikace @${label}: panel je dialog s popiskem`, (await panel.count()) === 1);
  // Panel přes celou výšku okna (dřív ho sticky hlavička s backdrop-filter ořízla na svou výšku).
  const box = await panel.boundingBox();
  const vh = page.viewportSize().height;
  check(`notifikace @${label}: panel přes celou výšku`, Boolean(box && box.height >= vh - 2), `${box?.height}/${vh}`);
  check(`notifikace @${label}: fokus v panelu`, await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))));
  const items = await panel.locator("li").count();
  check(`notifikace @${label}: seznam položek`, items > 0, String(items));
  const raw = await panel.evaluate((el) => /\b\d{4}-\d{2}-\d{2}\b|overdue|deadline/i.test(el.textContent || ""));
  check(`notifikace @${label}: bez surových ISO dat / angličtiny`, !raw);
  await page.screenshot({ path: `${OUT}notifications-${label}.png` });
  await page.keyboard.press("Escape");
  check(`notifikace @${label}: Escape zavře`, (await panel.count()) === 0);
  await page.waitForTimeout(50);
  check(`notifikace @${label}: fokus zpět na zvonek`, await bell.evaluate((el) => el === document.activeElement));
  check(`notifikace @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
  await ctx.close();
}

// 10) Omezený pohyb pro Drawer: bez vjezdové animace.
{
  const { ctx, page } = await open("/", { reducedMotion: "reduce" });
  await page.locator('button[aria-label^="Notifikace"]').click();
  await page.waitForTimeout(100);
  const anim = await page.evaluate(() => {
    const el = document.querySelector(".motion-drawer");
    return el ? getComputedStyle(el).animationName : "missing";
  });
  check("reduced motion: Drawer bez animace", anim === "none", anim);
  await ctx.close();
}

// 11) Filtry (FilterBar): Aktivita posílá správné parametry, Paměť hledá s debounce.
{
  const urls = [];
  const { ctx, page, errors } = await open("/activity", {
    setup: async (p) => p.on("request", (r) => r.url().includes("/activity?") && urls.push(r.url())),
  });
  await page.getByRole("button", { name: "Finance", exact: true }).click();
  await page.getByRole("button", { name: "Práce", exact: true }).click();
  await page.getByLabel("Od").fill("2026-10-01");
  await page.waitForTimeout(800);
  const last = new URL(urls.at(-1) || "http://x/");
  check("aktivita: více oblastí v jednom dotazu", last.searchParams.get("area") === "finance,work", last.search);
  check("aktivita: datum jako from_date (začátek pražského dne)", last.searchParams.get("from_date") === "2026-09-30T22:00:00.000Z", last.search);
  check("aktivita: čip má aria-pressed", (await page.getByRole("button", { name: "Finance", exact: true }).getAttribute("aria-pressed")) === "true");
  check("aktivita: Zrušit filtry", (await page.getByRole("button", { name: /Zrušit filtry/ }).count()) >= 1);
  await page.getByRole("button", { name: "Detail" }).first().click();
  await page.waitForTimeout(300);
  check("aktivita: detail se rozbalí", (await page.locator('[id^="activity-detail-"]').count()) === 1);
  check("aktivita: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const urls = [];
  const { ctx, page } = await open("/memory", {
    setup: async (p) => p.on("request", (r) => r.url().includes("/memories?q=") && urls.push(r.url())),
  });
  await page.getByLabel("Hledat v paměti").pressSequentially("ráno", { delay: 60 });
  await page.waitForTimeout(800);
  check("paměť: hledání s debounce (1 dotaz na slovo)", urls.length === 1, String(urls.length));
  await ctx.close();
}

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} kontrol prošlo. Screenshoty: ${OUT}`);
process.exit(failed.length ? 1 : 0);
