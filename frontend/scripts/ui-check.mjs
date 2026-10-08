// Vizuální a přístupnostní kontrola migrovaných stránek (Roadmap 4A–4H, Game Enrichment A–C).
//
// Předpoklady: `npm run build`, pak v jiných terminálech
//   node scripts/mock-api.mjs            (fixtures, žádný Groq)
//   npx next start -p 3000 -H 127.0.0.1
// Spuštění: node scripts/ui-check.mjs   (Playwright: PLAYWRIGHT_MODULE=/cesta/k/playwright/index.mjs,
//           jinak `import("playwright")`; prohlížeč: PLAYWRIGHT_CHROMIUM=/cesta/k/chromium volitelně)
// Výstup: screenshoty do scripts/.ui-check/ (gitignore) a seznam kontrol; exit 1 při selhání.
import { mkdirSync, readFileSync } from "node:fs";
import { stubPng } from "./stub-png.mjs";
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
  // Game Enrichment C
  ["/wot/replays", "wot-replays"],
  // Roadmap 4C
  ["/ai", "ai"],
  // Roadmap 4G
  ["/today", "today"],
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

// MRK-10 – Jarvis v denním briefingu: lokální asset, deterministický stav a dekorativní a11y režim.
{
  const { ctx, page, errors } = await open("/", { width: 1366, height: 900 });
  const avatar = page.locator('[aria-labelledby="briefing-title"] [data-testid="jarvis-avatar"]');
  check("jarvis briefing: avatar je viditelný", (await avatar.count()) === 1 && await avatar.isVisible());
  check("jarvis briefing: výchozí stav idle", (await avatar.getAttribute("data-jarvis-state")) === "idle");
  check("jarvis briefing: lokální asset a velikost sm", (await avatar.getAttribute("data-jarvis-asset")) === "asset" && (await avatar.getAttribute("data-jarvis-size")) === "sm");
  check("jarvis briefing: dekorativní instance je skrytá čtečkám", (await avatar.getAttribute("aria-hidden")) === "true");
  check("jarvis briefing: bez chyb JS", errors.length === 0, errors.join("; "));
  await page.screenshot({ path: `${OUT}jarvis-briefing.png` });
  await ctx.close();
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

// 5b) Roadmap 6A – sémantický pohyb: progress přes transform (bez layoutu), reduced motion = okamžitá změna.
for (const motion of ["no-preference", "reduce"]) {
  const { ctx, page, errors } = await open("/goals", { reducedMotion: motion });
  await page.waitForTimeout(900);
  const bars = await page.evaluate(() =>
    [...document.querySelectorAll('[role="progressbar"]')].map((bar) => {
      const fill = bar.querySelector(".motion-progress-fill");
      if (!fill) return { ok: false };
      const cs = getComputedStyle(fill);
      const m = new DOMMatrix(cs.transform);
      const track = bar.getBoundingClientRect().width;
      const shown = track ? (100 * (track + m.m41)) / track : 0;
      return {
        ok: true,
        fullWidth: Math.abs(fill.getBoundingClientRect().width - track) <= 1 || Math.abs(fill.offsetWidth - bar.clientWidth) <= 1,
        delta: Math.abs(shown - Number(bar.getAttribute("aria-valuenow"))),
        transition: `${cs.transitionProperty} ${cs.transitionDuration}`,
      };
    }),
  );
  const label = motion === "reduce" ? "goals reduced motion" : "goals";
  check(`${label}: progress bary používají motion-progress-fill`, bars.length > 0 && bars.every((b) => b.ok), String(bars.length));
  check(`${label}: výplň odpovídá aria-valuenow (±1 %)`, bars.every((b) => b.delta <= 1), bars.map((b) => b.delta?.toFixed(1)).join(","));
  check(
    `${label}: ${motion === "reduce" ? "bez přechodu" : "přechod jen transformací"}`,
    bars.every((b) => (motion === "reduce" ? /\b0s\b/.test(b.transition) : /^transform \d/.test(b.transition))),
    bars[0]?.transition,
  );
  check(`${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
  await ctx.close();
}

// 5c) Roadmap 6A – motion primitiva na vývojové ukázce /dev/motion (jen s MOTION_PREVIEW=1 na serveru).
{
  const probe = await fetch(`${BASE}/dev/motion`, { redirect: "manual" }).catch(() => null);
  if (!probe || probe.status === 404) {
    console.log("· /dev/motion není zapnutá (MOTION_PREVIEW=1) – kontroly primitiv přeskočeny");
  } else {
    for (const motion of ["no-preference", "reduce"]) {
      const tag = motion === "reduce" ? "motion primitiva (reduced)" : "motion primitiva";
      const { ctx, page, errors } = await open("/dev/motion", { reducedMotion: motion });
      const btn = (name) => page.getByRole("button", { name, exact: true });
      const pseudoAnim = (sel, pseudo) =>
        page.evaluate(([s, p]) => {
          const el = document.querySelector(s);
          return el ? getComputedStyle(el, p).animationName : "missing";
        }, [sel, pseudo]);

      // Completion: 40 → 100 %
      await btn("+30 %").click();
      await btn("+30 %").click();
      await page.waitForTimeout(80);
      const done = page.locator('[data-complete="true"]').first();
      check(`${tag}: dokončení – štítek viditelný`, await done.getByText("Splněno").isVisible());
      check(`${tag}: dokončení – role=status zpráva`, (await done.locator('[role="status"]').innerText()).includes("Ukázkový cíl splněn"));
      const glow = await pseudoAnim('[data-complete="true"]', "::after");
      check(`${tag}: dokončení – záře ${motion === "reduce" ? "vypnutá" : "běží"}`, motion === "reduce" ? glow === "none" : glow === "motion-glow-once", glow);
      await page.waitForTimeout(1400);
      const running = await page.evaluate(() => document.querySelector('[data-complete="true"]').getAnimations({ subtree: true }).filter((a) => a.playState === "running").length);
      check(`${tag}: oslava doběhne do 1,5 s`, running === 0, String(running));

      // Streak: +1 den → krátké rozhoření; popisek nese počet
      await btn("+1 den").click();
      await page.waitForTimeout(60);
      const flame = await page.evaluate(() => {
        const el = document.querySelector('[data-testid="preview-streak"] [role="img"]:last-child');
        const icon = el?.querySelector(".motion-flame");
        return { label: el?.getAttribute("aria-label"), anim: icon ? getComputedStyle(icon).animationName : "missing", hidden: icon?.getAttribute("aria-hidden") };
      });
      check(`${tag}: streak – popisek „Streak 6 dní"`, flame.label === "Streak 6 dní", flame.label);
      check(`${tag}: streak – ikona aria-hidden`, flame.hidden === "true");
      check(
        `${tag}: streak – ${motion === "reduce" ? "statický plamen" : "rozhoření při nárůstu"}`,
        motion === "reduce" ? flame.anim === "none" : flame.anim.startsWith("motion-flame-burst"),
        flame.anim,
      );

      // Milník: trvalý obrys i bez pohybu, záře jen s pohybem
      await btn("Přepnout milník").click();
      await page.waitForTimeout(60);
      const ring = await page.evaluate(() => {
        const el = document.querySelector('[data-milestone="true"]');
        return el ? getComputedStyle(el, "::before").boxShadow : "missing";
      });
      check(`${tag}: milník – trvalý obrys`, ring !== "none" && ring !== "missing", ring);
      const mGlow = await pseudoAnim('[data-milestone="true"]', "::after");
      check(`${tag}: milník – záře ${motion === "reduce" ? "vypnutá" : "jednou"}`, motion === "reduce" ? mGlow === "none" : mGlow === "motion-glow-once", mGlow);

      // Chyba: krátký obrys, žádné třesení (transform zůstává none)
      await btn("Chyba").click();
      const err = await page.evaluate(async () => {
        const el = document.querySelector('[role="alert"].motion-error');
        const samples = [];
        for (let i = 0; i < 5; i += 1) {
          samples.push(el ? getComputedStyle(el).transform : "missing");
          await new Promise((r) => setTimeout(r, 60));
        }
        return { samples, anim: el ? getComputedStyle(el).animationName : "missing" };
      });
      check(`${tag}: chyba – bez posunu textu`, err.samples.every((t) => t === "none"), err.samples.join(","));
      check(`${tag}: chyba – ${motion === "reduce" ? "bez animace" : "krátký obrys"}`, motion === "reduce" ? err.anim === "none" : err.anim === "motion-ring-error", err.anim);

      // Animace neblokují: tlačítka jsou klikací hned, fokus se nikam nepřesouvá
      check(`${tag}: fokus zůstává na ovládání`, await page.evaluate(() => document.activeElement?.tagName === "BUTTON"));
      check(`${tag}: bez chyb JS`, errors.length === 0, errors.join("; "));
      await page.screenshot({ path: `${OUT}motion-preview-${motion}.png`, fullPage: true });
      await ctx.close();
    }
  }
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

// 12) Roadmap 4B.1 – vyvážení dashboardu na širokých displejích (nezávislé na konkrétních datech).
for (const width of [1920, 1366]) {
  const { ctx, page } = await open("/", { width, height: 1000 });
  const m = await page.evaluate(() => {
    const card = (id) => document.getElementById(id)?.closest("section, article, div[aria-labelledby]")?.getBoundingClientRect();
    const [today, attention, goals, upcoming, work, finance, games] =
      ["today-title", "attention-title", "goals-title", "upcoming-title", "work-title", "finance-title", "games-title"].map(card);
    return {
      topGap: Math.abs(today.bottom - attention.bottom),
      // sloupec Práce/Finance nesmí trčet nad sousední karty (dřív o ~400 px)
      stackOverhang: finance.bottom - Math.max(goals.bottom, upcoming.bottom),
      gamesBelow: games.top >= Math.max(goals.bottom, upcoming.bottom, finance.bottom),
      workAbove: work.bottom <= finance.top,
    };
  });
  check(`dashboard @${width}: horní sloupce vyrovnané (< 200 px)`, m.topGap < 200, `${Math.round(m.topGap)} px`);
  check(`dashboard @${width}: Práce/Finance nepřečnívá sousedy`, m.stackOverhang <= 40, `${Math.round(m.stackOverhang)} px`);
  check(`dashboard @${width}: Hry jako pruh pod sloupci`, m.gamesBelow && m.workAbove);
  await ctx.close();
}

// 13) Roadmap 4B.1 – žádné interní hodnoty v UI (popisky z lib/labels.ts).
{
  const RAW_ENTITY = /\b(WotGrind|WotResource|FinanceTransaction|WorkSession|MffCharacter|PendingAction|Assignment|Exam|Memory|Reminder|Goal)\s*#/;
  const { ctx, page, errors } = await open("/activity");
  const text = await page.locator("main").innerText();
  check("aktivita: žádné interní typy entit", !RAW_ENTITY.test(text), (text.match(RAW_ENTITY) || [""])[0]);
  check("aktivita: žádný surový zdroj (manual / ai_confirm)", !/zdroj: (manual|ai_confirm)\b/.test(text));
  check("aktivita: česká entita (např. Grind #)", /(Grind|Transakce|Pracovní záznam|Paměť|Úkol) #\d+/.test(text));
  check("aktivita: bez „Pamatka“ a „(hard)“", !/Pamatka|\(hard\)|\(soft\)/.test(text));
  check("aktivita: finance bez „work (sync)“ a anglických znamének", !/work \(sync\)|^-\d/m.test(text));
  check("aktivita: plánovač/práce bez desetinné tečky v hodinách", !/\d\.\d h\b/.test(text));
  const rows = page.getByRole("button", { name: "Detail" });
  const fieldNames = [];
  for (let i = 0; i < Math.min(await rows.count(), 6); i += 1) {
    await rows.nth(i).click();
    await page.waitForTimeout(250);
  }
  for (const dt of await page.locator('[id^="activity-detail-"] dt').allInnerTexts()) fieldNames.push(dt);
  check("aktivita: detail má české názvy polí", fieldNames.length > 0 && fieldNames.every((f) => !/_|^[a-z]+$/.test(f)), fieldNames.slice(0, 8).join(", "));
  check("aktivita (labels): bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const { ctx, page } = await open("/finance");
  const meta = await page.locator("main li").allInnerTexts();
  const raw = meta.filter((t) => /(^|\s|·)\s*(work|food|salary|rent)\s*(·|$)/im.test(t));
  check("finance: kategorie česky (žádné work/food)", raw.length === 0, raw.slice(0, 2).join(" | "));
  check("finance: work → Práce", meta.some((t) => /Práce/.test(t)));
  await ctx.close();
}
{
  const { ctx, page } = await open("/memory");
  const text = await page.locator("main").innerText();
  check("paměť: kategorie česky (žádné plan/context/decision)", !/\b(plan|context|decision|routine|constraint)\b/.test(text)); // „preference" je i české slovo
  check("paměť: plan → Plán", /\bPlán\b/.test(text));
  await ctx.close();
}
{
  const { ctx, page } = await open("/work");
  const days = await page.evaluate(() => {
    const num = (s) => Number(s.replace(/[^\d,−-]/g, "").replace(",", ".").replace("−", "-"));
    return [...document.querySelectorAll("[data-day-total]")].map((el) => {
      const li = el.closest("li");
      const rows = [...li.querySelectorAll("[data-session-earnings]")].map((r) => num(r.textContent));
      return { total: num(el.textContent), sum: Math.round(rows.reduce((a, b) => a + b, 0) * 100) / 100, text: el.textContent };
    });
  });
  const bad = days.filter((d) => Math.abs(d.total - d.sum) > 0.001);
  check("práce: zobrazené řádky dávají zobrazený denní součet", days.length > 0 && bad.length === 0, bad.map((d) => `${d.sum} ≠ ${d.text}`).join(", "));
  await ctx.close();
}
{
  const { ctx, page } = await open("/wot");
  const text = await page.locator("main").innerText();
  check("wot: žádná sekce „Připravujeme“", !/Připravujeme/.test(text));
  check("wot: žádné prázdné zástupné dlaždice", (await page.locator("main .border-dashed").count()) === 0);
  await ctx.close();
}

// 14) Roadmap 4C – AI asistent (mock /chat, žádný Groq).
const RAW_AI = /\b(add_work_session|add_finance_transaction|upsert_\w+|update_wot_resource|save_memory|modify_records|manage_reminder|undo_change|date_value|hourly_rate|subject_id)\b/;
async function aiSend(page, text) {
  const box = page.getByLabel("Zpráva pro Standa AI");
  await box.fill(text);
  await box.press("Enter");
}
{
  const { ctx, page, errors } = await open("/ai", { width: 1366, height: 900, setup: (p) => p.addInitScript(() => localStorage.setItem("standa-hub:jarvis-companion:v1", "off")) });
  const box = page.getByLabel("Zpráva pro Standa AI");
  const avatar = page.locator('header [data-testid="jarvis-avatar"]');
  check("jarvis ai: avatar je viditelný (companion vypnutý)", (await avatar.count()) === 1 && await avatar.isVisible());
  check("jarvis ai: výchozí stav idle", (await avatar.getAttribute("data-jarvis-state")) === "idle");
  check("jarvis ai: lokální asset, sm a dekorativní", (await avatar.getAttribute("data-jarvis-asset")) === "asset" && (await avatar.getAttribute("data-jarvis-size")) === "sm" && (await avatar.getAttribute("aria-hidden")) === "true");
  check("ai: pole pro zprávu má popisek", (await box.count()) === 1);
  const unlabeled = await page.evaluate(() =>
    [...document.querySelectorAll("main textarea, main select, main input:not([type=hidden])")].filter((el) => {
      const id = el.id;
      return !(el.getAttribute("aria-label") || (id && document.querySelector(`label[for="${id}"]`)) || el.closest("label"));
    }).length,
  );
  check("ai: žádné pole bez popisku", unlabeled === 0, String(unlabeled));
  check("ai: odeslat zakázané bez textu", await page.getByRole("button", { name: "Odeslat" }).isDisabled());

  // Shift+Enter = nový řádek, Enter = odeslat
  await box.fill("první");
  await box.press("Shift+Enter");
  await box.pressSequentially("druhý");
  check("ai: Shift+Enter vloží nový řádek", (await box.inputValue()) === "první\ndruhý");
  await box.fill("");

  // přepnutí konverzace (prázdný stav ověřuje „nový chat“ níže – mock si pamatuje zprávy z dřívějších běhů)
  const rail = page.getByRole("complementary", { name: "Konverzace" });
  await rail.getByRole("button", { name: /^Finance – září/ }).click();
  await page.waitForTimeout(600);
  check("ai: přepnutí konverzace načte její zprávy", (await page.getByText("Kolik jsem utratil v září?").count()) === 1);
  check("ai: aktivní konverzace označená (aria-current)", (await rail.locator('[aria-current="true"]').innerText()).includes("Finance"));

  // nový chat
  const before = await rail.locator("li").count();
  await rail.getByRole("button", { name: "+ Nový chat" }).click();
  await page.waitForTimeout(800);
  check("ai: nový chat přibyl v seznamu", (await rail.locator("li").count()) === before + 1);
  check("ai: nový chat je prázdný", (await page.getByRole("heading", { name: "Na co se chceš zeptat?" }).count()) === 1);
  check("ai: po založení fokus v poli pro zprávu", await box.evaluate((el) => el === document.activeElement));

  // odeslání: busy + přemýšlí, pak odpověď s Markdownem
  await aiSend(page, "Ahoj, jak se máš?");
  await page.waitForTimeout(200);
  check("ai: během odesílání busy tlačítko", (await page.locator('button[aria-busy="true"]', { hasText: "Odesílám" }).count()) === 1);
  check("ai: indikátor přemýšlení (role=status)", (await page.getByText("Standa AI přemýšlí…").count()) === 1);
  check("jarvis ai: odesílání = thinking", (await avatar.getAttribute("data-jarvis-state")) === "thinking");
  check("ai: pole se po odeslání vyprázdní", (await box.inputValue()) === "");
  await page.waitForTimeout(1200);
  check("ai: odpověď vykreslená (Markdown nadpis)", (await page.getByRole("heading", { name: "Odpověď" }).count()) === 1);

  // plán v chatu = karta Planneru
  await aiSend(page, "Jaký mám plán na tento týden?");
  await page.waitForTimeout(1500);
  check("ai: plán v chatu jako karta Planneru", (await page.getByText("Týdenní plán", { exact: true }).count()) >= 1);
  await page.screenshot({ path: `${OUT}ai-planner.png` });

  // pending akce: náhled → potvrzení → výsledek s Vrátit → vrácení jako nová karta → zamítnutí
  await aiSend(page, "Zapiš práci 6,5 h pro Klient XYZ");
  await page.waitForTimeout(1500);
  const card = page.getByRole("list", { name: "Akce čekající na potvrzení" }).locator("li").first();
  check("jarvis ai: čekající potvrzení = warning", (await avatar.getAttribute("data-jarvis-state")) === "warning");
  check("ai: karta akce s českým titulkem", (await card.getByRole("heading", { name: "Přidat pracovní záznam" }).count()) === 1);
  const cardText = await card.innerText();
  check("ai: karta ukazuje hodnoty a výdělek", /10\. 10\. 2026/.test(cardText) && /6,5 h/.test(cardText) && /2\s437,50 Kč/.test(cardText), cardText.replace(/\n/g, " | ").slice(0, 160));
  await page.screenshot({ path: `${OUT}ai-pending.png` });
  await card.getByRole("button", { name: "Potvrdit" }).click();
  await page.waitForTimeout(150);
  check("ai: potvrzení – busy stav", (await card.locator('button[aria-busy="true"]').count()) === 1);
  await page.waitForTimeout(1100);
  const outcome = page.getByRole("list", { name: "Výsledky akcí" });
  check("ai: výsledek „Hotovo“ s nabídkou Vrátit", (await outcome.getByRole("button", { name: /^Vrátit změnu/ }).count()) === 1);
  check("ai: zpráva o provedení v historii", (await page.getByText("Přidán pracovní záznam.").count()) >= 1);
  check("jarvis ai: dokončená akce = success", (await avatar.getAttribute("data-jarvis-state")) === "success");
  await page.screenshot({ path: `${OUT}jarvis-ai-success.png` });
  await outcome.getByRole("button", { name: /^Vrátit změnu/ }).click();
  await page.waitForTimeout(700);
  const undoCard = page.getByRole("list", { name: "Akce čekající na potvrzení" }).locator("li").first();
  check("ai: vrácení = nová karta k potvrzení", (await undoCard.getByText("Vrácení změny").count()) >= 1);
  await undoCard.getByRole("button", { name: "Zamítnout" }).click();
  await page.waitForTimeout(400);
  check("ai: zamítnutí – karta zmizí a zpráva v historii", (await page.getByRole("list", { name: "Akce čekající na potvrzení" }).count()) === 0 && (await page.getByText("Akce byla zrušena: Vrátit změnu.").count()) === 1);

  // dávka: počet, skryté položky, upozornění; první potvrzení selže → Zkusit znovu → projde
  await aiSend(page, "Smaž všechny obědy");
  await page.waitForTimeout(1500);
  const batch = page.getByRole("list", { name: "Akce čekající na potvrzení" }).locator(":scope > li").first();
  const batchText = await batch.innerText();
  check("ai: dávka ukazuje počet, další a upozornění", /12 záznamů/.test(batchText) && /a dalších 2/.test(batchText) && /nepůjde obnovit/.test(batchText));
  await batch.getByRole("button", { name: "Potvrdit" }).click();
  await page.waitForTimeout(1200);
  const failedCard = page.getByRole("list", { name: "Akce čekající na potvrzení" }).locator(":scope > li").first();
  check("ai: selhání potvrzení – Zkusit znovu", (await failedCard.getByRole("button", { name: "Zkusit znovu" }).count()) === 1);
  check("jarvis ai: selhání akce = error", (await avatar.getAttribute("data-jarvis-state")) === "error");
  await page.screenshot({ path: `${OUT}jarvis-ai-error.png` });
  // Roadmap 6A: selhání = krátký obrys (motion-error), karta se nehýbe (žádné třesení).
  const failedMotion = await failedCard.evaluate((el) => ({ cls: el.className, transform: getComputedStyle(el).transform }));
  check("ai: selhání – motion-error bez posunu", failedMotion.cls.includes("motion-error") && !failedMotion.cls.includes("motion-shake") && failedMotion.transform === "none", failedMotion.transform);
  await failedCard.getByRole("button", { name: "Zkusit znovu" }).click();
  await page.waitForTimeout(1200);
  check("ai: druhý pokus projde", (await page.getByRole("list", { name: "Akce čekající na potvrzení" }).count()) === 0);

  // chyby: rate limit (zkusit znovu), denní limit (bez zkusit znovu), 500
  await aiSend(page, "test limit");
  await page.waitForTimeout(1300);
  check("ai: rate limit – upozornění se Zkusit znovu", (await page.getByRole("alert").filter({ hasText: "vytížená" }).getByRole("button", { name: "Zkusit znovu" }).count()) === 1);
  check("jarvis ai: chyba požadavku = error", (await avatar.getAttribute("data-jarvis-state")) === "error");
  await page.screenshot({ path: `${OUT}ai-ratelimit.png` });
  await aiSend(page, "denní limit");
  await page.waitForTimeout(1300);
  const daily = page.getByRole("alert").filter({ hasText: "Denní limit" });
  check("ai: denní limit – bez Zkusit znovu", (await daily.count()) === 1 && (await daily.getByRole("button", { name: "Zkusit znovu" }).count()) === 0);
  await aiSend(page, "chyba");
  await page.waitForTimeout(1300);
  check("ai: chyba serveru – upozornění", (await page.getByRole("alert").filter({ hasText: "AI backend vrátil chybu" }).count()) === 1);

  const text = await page.locator("main").innerText();
  check("ai: žádné interní názvy toolů / klíčů", !RAW_AI.test(text), (text.match(RAW_AI) || [""])[0]);
  check("ai: právě jeden h1", (await page.locator("h1").count()) === 1);
  check("ai: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// Jarvis AI transientní stavy se nesmí přenést do jiné konverzace.
{
  const { ctx, page, errors } = await open("/ai", { width: 1366, height: 900 });
  const avatar = page.locator('header [data-testid="jarvis-avatar"]');
  await aiSend(page, "Zapiš práci 3 h");
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: "Potvrdit" }).first().click();
  await page.waitForTimeout(1200);
  check("jarvis ai lifecycle: úspěch v aktivním chatu", (await avatar.getAttribute("data-jarvis-state")) === "success");
  await page.getByRole("complementary", { name: "Konverzace" }).getByRole("button", { name: /^Finance – září/ }).click();
  await page.waitForTimeout(700);
  check("jarvis ai lifecycle: přepnutí chatu resetuje transientní stav", (await avatar.getAttribute("data-jarvis-state")) === "idle");
  check("jarvis ai lifecycle: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// přejmenování na místě a smazání přes ConfirmDialog
{
  const { ctx, page } = await open("/ai", { width: 1366, height: 900 });
  const rail = page.getByRole("complementary", { name: "Konverzace" });
  await rail.getByRole("button", { name: "+ Nový chat" }).click();
  await page.waitForTimeout(800);
  await rail.getByRole("button", { name: /^Přejmenovat chat Nový chat/ }).first().click();
  const input = rail.getByLabel("Nový název chatu");
  check("ai: přejmenování – pole s fokusem", await input.evaluate((el) => el === document.activeElement));
  await input.fill("Testovací chat");
  await input.press("Enter");
  await page.waitForTimeout(600);
  check("ai: přejmenování uloženo", (await rail.getByRole("button", { name: /^Testovací chat/ }).count()) === 1);
  await rail.getByRole("button", { name: "Smazat chat Testovací chat" }).click();
  const dialog = page.getByRole("dialog");
  check("ai: smazání chatu přes ConfirmDialog", (await dialog.count()) === 1 && (await dialog.getAttribute("aria-modal")) === "true");
  await dialog.getByRole("button", { name: "Smazat chat" }).click();
  await page.waitForTimeout(900);
  check("ai: chat smazán", (await rail.getByRole("button", { name: /^Testovací chat/ }).count()) === 0);
  await ctx.close();
}

// mobil: konverzace v Draweru (fokus, Escape, návrat fokusu, výběr zavře)
{
  const { ctx, page, errors } = await open("/ai", { width: 390, height: 844 });
  const avatar = page.locator('header [data-testid="jarvis-avatar"]');
  check("jarvis ai mobil: avatar sm je viditelný", await avatar.isVisible() && (await avatar.getAttribute("data-jarvis-size")) === "sm");
  check("ai mobil: bez postranního panelu konverzací", !(await page.getByRole("complementary", { name: "Konverzace" }).isVisible()));
  const opener = page.getByRole("button", { name: "Konverzace" });
  await opener.click();
  const drawer = page.getByRole("dialog", { name: "Konverzace" });
  check("ai mobil: Drawer konverzací", (await drawer.count()) === 1);
  await page.waitForTimeout(80);
  check("ai mobil: fokus v Draweru", await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))));
  await page.screenshot({ path: `${OUT}ai-drawer-mobile.png` });
  await page.keyboard.press("Escape");
  check("ai mobil: Escape zavře", (await drawer.count()) === 0);
  await page.waitForTimeout(60);
  check("ai mobil: fokus zpět na tlačítko", await opener.evaluate((el) => el === document.activeElement));
  await opener.click();
  await drawer.getByRole("button", { name: /^Plán na týden/ }).click();
  await page.waitForTimeout(700);
  check("ai mobil: výběr konverzace zavře Drawer", (await page.getByRole("dialog").count()) === 0);
  await aiSend(page, "Zapiš práci 2 h");
  await page.waitForTimeout(1500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check("ai mobil: karta akce bez přetečení", overflow <= 0, `${overflow}px`);
  const composerVisible = await page.getByLabel("Zpráva pro Standa AI").isVisible();
  check("ai mobil: pole pro zprávu viditelné", composerVisible);
  await page.screenshot({ path: `${OUT}ai-mobile-pending.png` });
  check("ai mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// omezený pohyb: indikátor přemýšlení a odpočet „Vrátit" bez animace
{
  const { ctx, page } = await open("/ai", { reducedMotion: "reduce" });
  await aiSend(page, "Zapiš práci 1 h");
  await page.waitForTimeout(150);
  const avatarMotion = await page.locator('header [data-testid="jarvis-avatar"]').evaluate((el) => ({
    state: el.getAttribute("data-jarvis-state"),
    self: getComputedStyle(el).animationName,
    after: getComputedStyle(el, "::after").animationName,
  }));
  check("jarvis reduced motion: thinking bez animace", avatarMotion.state === "thinking" && avatarMotion.self === "none" && avatarMotion.after === "none", JSON.stringify(avatarMotion));
  const dots = await page.evaluate(() => {
    const d = document.querySelector(".animate-bounce");
    return d ? getComputedStyle(d).animationName : "missing";
  });
  check("ai reduced motion: indikátor bez animace", dots === "none", dots);
  await page.waitForTimeout(1400);
  await page.getByRole("button", { name: "Potvrdit" }).first().click();
  await page.waitForTimeout(1100);
  const timer = await page.evaluate(() => {
    const t = document.querySelector(".motion-undo-timer");
    return t ? getComputedStyle(t).animationName : "missing";
  });
  check("ai reduced motion: odpočet Vrátit bez animace", timer === "none", timer);
  await page.screenshot({ path: `${OUT}jarvis-ai-reduced-motion.png` });
  await ctx.close();
}

// Skutečný stav diktování z browserového SpeechRecognition adapteru → listening.
{
  const { ctx, page, errors } = await open("/ai", {
    setup: (p) => p.addInitScript(() => {
      class FakeSpeechRecognition {
        onstart = null;
        onresult = null;
        onerror = null;
        onend = null;
        onspeechend = null;
        onsoundend = null;
        onaudioend = null;
        start() { setTimeout(() => this.onstart?.(), 25); }
        stop() { setTimeout(() => this.onend?.(), 25); }
        abort() { setTimeout(() => this.onend?.(), 25); }
      }
      Object.defineProperty(window, "SpeechRecognition", { value: FakeSpeechRecognition, configurable: true });
      Object.defineProperty(window, "webkitSpeechRecognition", { value: FakeSpeechRecognition, configurable: true });
    }),
  });
  const avatar = page.locator('header [data-testid="jarvis-avatar"]');
  await page.getByRole("button", { name: "Diktovat zprávu (Ctrl+Shift+M)" }).click();
  await page.getByRole("region", { name: "Chat" }).getByText("Poslouchám…").waitFor();
  check("jarvis ai: skutečné diktování = listening", (await avatar.getAttribute("data-jarvis-state")) === "listening");
  check("companion ai: skutečné diktování = listening", (await page.getByTestId("jarvis-companion").getAttribute("data-companion-state")) === "listening");
  await page.getByRole("button", { name: "Zastavit diktování" }).click();
  check("jarvis ai listening: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// Chybějící asset nesmí rozbít AI hlavičku: komponenta přepne na lokální vektorový fallback.
{
  const { ctx, page, errors } = await open("/ai", {
    setup: async (p) => {
      await p.addInitScript(() => localStorage.setItem("standa-hub:jarvis-companion:v1", "off"));
      await p.route("**/jarvis/jarvis-shell.svg", (route) => route.abort());
    },
  });
  const avatar = page.locator('header [data-testid="jarvis-avatar"]');
  await avatar.locator('[data-testid="jarvis-fallback"]').waitFor();
  check("jarvis fallback: chyba assetu přepne bezpečný fallback", (await avatar.getAttribute("data-jarvis-asset")) === "fallback");
  check("jarvis fallback: avatar zůstává viditelný", await avatar.isVisible());
  check("jarvis fallback: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// 15) Roadmap 4C – proxy.ts (dříve middleware.ts) a login: skutečné přesměrování podle session cookie z mock API.
{
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  await ctx.addCookies([{ name: "standa_hub_session", value: "expired", domain: "127.0.0.1", path: "/" }]);
  const page = await ctx.newPage();
  const errors = [];
  const requests = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("request", (r) => requests.push(new URL(r.url()).pathname));
  await page.goto(`${BASE}/ai`, { waitUntil: "networkidle" });
  const u = new URL(page.url());
  check("proxy: chráněná stránka bez session → /login", u.pathname === "/login" && u.searchParams.get("next") === "/ai", page.url());
  check("login: bez zvonku a navigace", (await page.locator('button[aria-label^="Notifikace"]').count()) === 0 && (await page.locator("nav").count()) === 0);
  check("login: žádné dotazy na notifikace", !requests.some((r) => r.startsWith("/notifications")), requests.join(","));
  await page.waitForTimeout(500);
  check("login: bez smyčky přesměrování", new URL(page.url()).pathname === "/login");
  const pin = page.getByLabel("PIN", { exact: true });
  await pin.fill("0000");
  await page.getByRole("button", { name: "Přihlásit" }).click();
  await page.waitForTimeout(700);
  const alert = page.locator("main").getByRole("alert"); // Next má vlastní route announcer s role=alert mimo <main>
  check("login: neplatný PIN česky", (await alert.count()) === 1 && /Neplatný PIN/.test(await alert.innerText()), await alert.innerText().catch(() => ""));
  await pin.fill("1234");
  await page.getByRole("button", { name: "Přihlásit" }).click();
  await page.waitForURL("**/ai", { timeout: 5000 }).catch(() => undefined);
  await page.waitForTimeout(800);
  check("login: úspěch → zpět na původní stránku", new URL(page.url()).pathname === "/ai", page.url());
  check("login: po přihlášení aplikace se zvonkem", (await page.locator('button[aria-label^="Notifikace"]').count()) === 1);
  await page.goto(`${BASE}/login?next=%2Ffinance`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  check("login: přihlášený uživatel na /login → přesměrován dál", new URL(page.url()).pathname === "/finance", page.url());
  check("proxy/login: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// 16) Roadmap 4D – globální vyhledávání (Ctrl+K), mock /search = odpovědi skutečné search_service.
const MOCK_API = process.env.MOCK_API_URL || "http://127.0.0.1:8000";
async function searchCalls() {
  return (await fetch(`${MOCK_API}/__mock/search-calls`)).json();
}
{
  const { ctx, page, errors } = await open("/", { width: 1366, height: 900 });
  check("hledání: paleta na začátku zavřená", (await page.getByRole("dialog").count()) === 0);
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  check("hledání: Ctrl+K otevře paletu", (await dialog.count()) === 1);
  const input = dialog.getByRole("combobox", { name: "Hledat stránku nebo záznam" });
  await page.waitForTimeout(80);
  check("hledání: fokus v poli (combobox s popiskem)", await input.evaluate((el) => el === document.activeElement));
  check("hledání: prázdný dotaz ukáže navigaci", (await dialog.getByRole("group", { name: "Navigace" }).getByRole("option").count()) === 14);
  await page.screenshot({ path: `${OUT}search-empty.png` });

  const first = async () => (await dialog.getByRole("option").first().innerText()).split("\n")[0];
  await input.fill("prace");
  await page.waitForTimeout(500);
  check("hledání: „prace“ najde stránku Práce (bez diakritiky)", (await first()) === "Práce", await first());
  await input.fill("test");
  await page.waitForTimeout(500);
  const school = dialog.getByRole("group", { name: "Škola" });
  check("hledání: zkouška „test“ ve skupině Škola", (await school.getByRole("option", { name: /^test Test · Fyzika/ }).count()) === 1);
  for (const [q, re, group] of [
    ["tvp", /^TVP T 50\/51/, "World of Tanks"],
    ["luna", /^Luna Snow/, "Marvel FF"],
    ["ucim", /^Nejlíp se učím ráno/, "Paměť"],
    ["obed", /^Oběd Výdaj · 189,90\s?Kč · Jídlo/, "Finance"],
    ["kvetiny", /^Zalít květiny/, "Připomínky"],
  ]) {
    await input.fill(q);
    await page.waitForTimeout(500);
    const hit = dialog.getByRole("group", { name: group }).getByRole("option", { name: re });
    check(`hledání: „${q}“ → ${group}`, (await hit.count()) === 1);
  }
  await input.fill("fyzika");
  await page.waitForTimeout(500);
  check("hledání: více skupin a počet ve stavu", /\d+ výsled/.test(await dialog.getByRole("status").innerText()));
  await page.screenshot({ path: `${OUT}search-results.png` });

  // debounce: psaní po znacích = málo dotazů
  await input.fill("");
  await searchCalls();
  await input.pressSequentially("luna snow", { delay: 35 });
  await page.waitForTimeout(600);
  const calls = await searchCalls();
  check("hledání: debounce (psaní nespouští dotaz na každý znak)", calls.length >= 1 && calls.length <= 2, calls.join(" | "));

  // prázdný výsledek
  await input.fill("xyznic");
  await page.waitForTimeout(600);
  check("hledání: „Nic nenalezeno“", (await dialog.getByText("Nic nenalezeno.", { exact: false }).count()) >= 1);
  await page.screenshot({ path: `${OUT}search-none.png` });

  // šipky + Enter → přímo na záznam
  await input.fill("fyzika");
  await page.waitForTimeout(500);
  const sel = async () => input.getAttribute("aria-activedescendant");
  const count = await dialog.getByRole("option").count();
  const a0 = await sel();
  await input.press("ArrowDown");
  const a1 = await sel();
  await input.press("ArrowUp");
  const back = await sel();
  await input.press("ArrowUp");
  const wrapped = await sel();
  const lastId = await dialog.getByRole("option").nth(count - 1).getAttribute("id");
  check("hledání: šipky mění vybraný řádek a cyklí", Boolean(a0) && a1 !== a0 && back === a0 && wrapped === lastId, `${count} řádků`);
  await input.fill("luna");
  await page.waitForTimeout(500);
  check("hledání: vybraný řádek má aria-selected", (await dialog.locator('[role="option"][aria-selected="true"]').count()) === 1);
  await input.press("Enter");
  await page.waitForURL("**/mff?character=*", { timeout: 5000 }).catch(() => undefined);
  check("hledání: Enter otevře záznam", /\/mff\?character=\d+$/.test(page.url()), page.url());
  await page.waitForTimeout(1200);
  const target = await page.evaluate(() => {
    const el = document.activeElement;
    return { attr: el?.getAttribute("data-search-target") ?? "", highlighted: Boolean(el?.classList.contains("search-target-active")) };
  });
  check("hledání: záznam má fokus a zvýraznění", target.attr.startsWith("character-") && target.highlighted, JSON.stringify(target));
  check("hledání: paleta po otevření výsledku zavřená", (await page.getByRole("dialog").count()) === 0);
  await page.screenshot({ path: `${OUT}search-deeplink.png` });

  // nedávno otevřené + Esc vrací fokus na tlačítko v shellu
  const field = page.getByRole("button", { name: /^Hledat…/ });
  await field.click();
  await page.waitForTimeout(100);
  check("hledání: nedávno otevřené", (await page.getByRole("group", { name: "Nedávno otevřené" }).getByRole("option", { name: /^Luna Snow/ }).count()) === 1);
  await page.keyboard.press("Escape");
  check("hledání: Esc zavře", (await page.getByRole("dialog").count()) === 0);
  await page.waitForTimeout(60);
  check("hledání: fokus zpět na spouštěč", await field.evaluate((el) => el === document.activeElement));
  check("hledání: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// mobil: tlačítko v hlavičce, celá obrazovka, ťuknutí otevře záznam
{
  const { ctx, page, errors } = await open("/", { width: 390, height: 844 });
  await page.getByRole("button", { name: "Hledat", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  check("hledání mobil: otevře se tlačítkem v hlavičce", (await dialog.count()) === 1);
  const box = await dialog.boundingBox();
  check("hledání mobil: přes celou obrazovku", Boolean(box && box.width >= 389 && box.height >= 843), `${box?.width}×${box?.height}`);
  await page.keyboard.type("tvp");
  await page.waitForTimeout(600);
  const opt = dialog.getByRole("option", { name: /^TVP T 50\/51/ });
  const optBox = await opt.boundingBox();
  check("hledání mobil: dotykový cíl ≥ 44 px", Boolean(optBox && optBox.height >= 44), String(optBox?.height));
  check("hledání mobil: bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  await page.screenshot({ path: `${OUT}search-mobile.png` });
  await opt.tap();
  await page.waitForURL("**/wot?grind=*", { timeout: 5000 }).catch(() => undefined);
  check("hledání mobil: ťuknutí otevře záznam", /\/wot\?grind=\d+$/.test(page.url()), page.url());
  await page.getByRole("button", { name: "Hledat", exact: true }).click();
  await page.getByRole("button", { name: "Zavřít" }).click();
  check("hledání mobil: Zavřít", (await page.getByRole("dialog").count()) === 0);
  check("hledání mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// login: žádné vyhledávání ani dotazy /search; omezený pohyb; světlý motiv OS
{
  const requests = [];
  const { ctx, page } = await open("/login", {
    setup: async (p) => {
      p.on("request", (r) => requests.push(new URL(r.url()).pathname));
      await p.route("**/auth/session/validate", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ valid: false, auth_disabled: false }) }),
      );
    },
  });
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(200);
  check("login: bez vyhledávání (Ctrl+K nic neotevře)", (await page.getByRole("dialog").count()) === 0 && (await page.getByRole("button", { name: /^Hledat/ }).count()) === 0);
  check("login: žádné dotazy /search", !requests.some((r) => r.startsWith("/search")));
  await ctx.close();
}
for (const [scheme, motion] of [["dark", "reduce"], ["light", "no-preference"]]) {
  const { ctx, page } = await open("/", { scheme, reducedMotion: motion });
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(150);
  const style = await page.evaluate(() => {
    const d = document.querySelector('[role="dialog"]');
    const cs = d ? getComputedStyle(d) : null;
    return { anim: cs?.animationName ?? "missing", bg: cs?.backgroundColor ?? "" };
  });
  if (motion === "reduce") check("hledání reduced motion: paleta bez animace", style.anim === "none", style.anim);
  else check("hledání (světlý motiv OS): paleta zůstává tmavá", !/255, 255, 255/.test(style.bg) && style.bg !== "", style.bg);
  await ctx.close();
}

// 17) Roadmap 4E – Rychlé přidání (Ctrl+Shift+K / „+"), mock /quick-add/parse = odpovědi skutečného parseru.
const quickAddLog = async () => (await fetch("http://127.0.0.1:8000/__mock/quick-add")).json();
const qaDialog = (page) => page.getByRole("dialog", { name: "Rychlé přidání" });
async function qaType(page, text) {
  const input = qaDialog(page).getByLabel("Co chceš přidat?");
  await input.fill(text);
  await page.waitForTimeout(450);
  return input;
}
{
  const { ctx, page, errors } = await open("/");
  await quickAddLog();
  await page.keyboard.press("Control+Shift+K");
  const dialog = qaDialog(page);
  check("quick add: Ctrl+Shift+K otevře Rychlé přidání", (await dialog.count()) === 1);
  check("quick add: Ctrl+Shift+K neotevře vyhledávání", (await page.getByRole("dialog", { name: "Hledat v Standa Hubu" }).count()) === 0);
  const input = dialog.getByLabel("Co chceš přidat?");
  check("quick add: fokus v poli", await input.evaluate((el) => el === document.activeElement));
  check("quick add: prázdný stav s příklady", (await dialog.getByRole("list", { name: "Příklady" }).getByRole("button").count()) >= 5);
  await page.screenshot({ path: `${OUT}quick-add-empty.png` });

  // finance: náhled → úprava pole → Enter neukládá → Uložit
  await qaType(page, "oběd 189,90 Kč");
  const preview = dialog.getByTestId("quick-add-preview");
  check("quick add: finance náhled", (await preview.getAttribute("data-kind")) === "finance" && (await preview.getByText("Rozpoznáno").count()) === 1);
  check("quick add: finance částka a kategorie", (await dialog.getByLabel(/^Částka/).inputValue()) === "189,9" && (await dialog.getByLabel("Kategorie").inputValue()) === "Jídlo");
  await page.screenshot({ path: `${OUT}quick-add-finance.png` });
  await dialog.getByLabel("Kategorie").fill("Restaurace");
  await input.press("Enter");
  await page.waitForTimeout(450);
  let log = await quickAddLog();
  check("quick add: rozbor nezapisuje a Enter neukládá", log.prepared.length === 0 && log.confirmed.length === 0, `${log.parse.length} rozborů`);
  await dialog.getByLabel("Kategorie").fill("Restaurace");
  await dialog.getByTestId("quick-add-save").click();
  await dialog.getByTestId("quick-add-saved").waitFor({ timeout: 4000 }).catch(() => undefined);
  log = await quickAddLog();
  check("quick add: Uložit = prepare + confirm s upraveným polem", log.prepared.length === 1 && log.prepared[0].fields.category === "Restaurace" && log.confirmed.length === 1, JSON.stringify(log.prepared[0]?.fields));
  check("quick add: potvrzení se zdrojem „Rychlé přidání“", (await dialog.getByText("v Aktivitě jako „Rychlé přidání“", { exact: false }).count()) === 1 && (await dialog.getByText("Uloženo").count()) >= 1);
  check("quick add: u vytvoření se nenabízí Vrátit", (await dialog.getByRole("button", { name: /Vrátit/ }).count()) === 0);
  await dialog.getByRole("button", { name: "Přidat další" }).click();
  check("quick add: Přidat další vyčistí pole a vrátí fokus", (await input.inputValue()) === "" && (await input.evaluate((el) => el === document.activeElement)));

  // nejednoznačné: „Albert 820" → otázka, Uložit zakázané, Enter nic, „Ano" povolí
  await qaType(page, "Albert 820");
  const save = dialog.getByTestId("quick-add-save");
  check("quick add: „Albert 820“ se ptá „Je to 820 Kč?“", (await dialog.getByText("Je to 820 Kč?").count()) >= 1 && (await preview.getByText("Zkontroluj").count()) === 1);
  check("quick add: nejednoznačné nejde uložit", await save.isDisabled());
  await input.press("Enter");
  await page.waitForTimeout(400);
  check("quick add: Enter nepotvrdí nejednoznačný náhled", (await quickAddLog()).prepared.length === 0);
  await page.screenshot({ path: `${OUT}quick-add-ambiguous.png` });
  await dialog.getByRole("button", { name: "Ano", exact: true }).click();
  check("quick add: po „Ano“ jde uložit", await save.isEnabled());

  // neznámé
  await qaType(page, "asdf qwer");
  check("quick add: „Tomu zatím nerozumím.“ + příklady", (await dialog.getByTestId("quick-add-unknown").count()) === 1 && (await dialog.getByRole("list", { name: "Příklady" }).count()) === 1);
  check("quick add: neznámé nejde uložit", await save.isDisabled());
  await page.screenshot({ path: `${OUT}quick-add-unknown.png` });

  // příklad z prázdného stavu vyplní pole
  await qaType(page, "");
  await dialog.getByRole("button", { name: "6,5 h Workshop za 375 Kč/h" }).click();
  await page.waitForTimeout(450);
  check("quick add: práce – sazba a výdělek", (await preview.getAttribute("data-kind")) === "work" && /2\s437,50\sKč/.test(await preview.innerText()) && (await dialog.getByLabel(/^Sazba/).inputValue()) === "375");
  await page.screenshot({ path: `${OUT}quick-add-work.png` });

  // připomínka: relativní den
  await qaType(page, "zítra fyzio v 17:00");
  check("quick add: připomínka zítra v 17:00", (await preview.getAttribute("data-kind")) === "reminder" && (await dialog.getByLabel(/^Kdy/).inputValue()) === "2026-10-12T17:00" && (await preview.getByText("zítra v 17:00").count()) === 1);
  await page.screenshot({ path: `${OUT}quick-add-reminder.png` });

  // škola: předmět + datum; neznámý předmět = otázka, výběr ze seznamu povolí uložení
  await qaType(page, "test z fyziky 18. 10.");
  check("quick add: škola – předmět a termín", (await preview.getAttribute("data-kind")) === "exam" && (await dialog.getByLabel(/^Předmět/).inputValue()) === "2" && (await dialog.getByLabel(/^Termín/).inputValue()) === "2026-10-18");
  await page.screenshot({ path: `${OUT}quick-add-school.png` });
  await qaType(page, "test z práva 18. 10.");
  check("quick add: neznámý předmět se nehádá", (await dialog.getByText("Ke kterému předmětu to patří?").count()) >= 1 && (await dialog.getByLabel(/^Předmět/).inputValue()) === "" && (await save.isDisabled()));
  await dialog.getByLabel(/^Předmět/).selectOption({ label: "Matematika" });
  check("quick add: výběr předmětu povolí uložení", await save.isEnabled());

  // neplatné: 40 h
  await qaType(page, "40 h práce");
  check("quick add: 40 h = chyba u pole", (await dialog.getByText("Hodiny musí být mezi 0 a 24.").count()) >= 1 && (await save.isDisabled()));

  // chyba rozboru → znovu
  await qaType(page, "simuluj chybu");
  check("quick add: chyba rozboru s „Zkusit znovu“", (await dialog.getByRole("button", { name: /Zkusit znovu/ }).count()) === 1);

  // selhání potvrzení → „Zkusit znovu" potvrdí TUTÉŽ pending akci
  await quickAddLog();
  await qaType(page, "oběd 189,90 Kč");
  await dialog.getByLabel("Popis").fill("chyba");
  await save.click();
  await dialog.getByRole("alert").waitFor({ timeout: 4000 }).catch(() => undefined);
  check("quick add: selhání uložení je vidět", /simulace/.test(await dialog.getByRole("alert").innerText().catch(() => "")));
  await dialog.getByTestId("quick-add-save").click();
  await dialog.getByTestId("quick-add-saved").waitFor({ timeout: 4000 }).catch(() => undefined);
  log = await quickAddLog();
  check("quick add: opakování nevytvoří druhou akci", log.prepared.length === 1 && log.confirmed.length === 1 && (await dialog.getByTestId("quick-add-saved").count()) === 1, JSON.stringify({ p: log.prepared.length, c: log.confirmed.length }));

  // Esc zavře a vrátí fokus na „+" v postranním panelu
  await page.keyboard.press("Escape");
  const plus = page.getByRole("button", { name: /^Rychlé přidání/ });
  await plus.click();
  check("quick add: „+“ v postranním panelu otevře dialog", (await dialog.count()) === 1);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(60);
  check("quick add: Esc zavře a vrátí fokus", (await dialog.count()) === 0 && (await plus.evaluate((el) => el === document.activeElement)));
  check("quick add: Ctrl+K dál otevírá vyhledávání", await (async () => {
    await page.keyboard.press("Control+k");
    const ok = (await page.getByRole("dialog", { name: "Hledat v Standa Hubu" }).count()) === 1 && (await dialog.count()) === 0;
    await page.keyboard.press("Escape");
    return ok;
  })());
  check("quick add: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// mobil 390 px: „+" v hlavičce, celá obrazovka, pole pod sebou, Uložit dosažitelné
{
  const { ctx, page, errors } = await open("/", { width: 390, height: 844 });
  await page.getByRole("button", { name: "Rychlé přidání", exact: true }).tap();
  const dialog = qaDialog(page);
  const box = await dialog.boundingBox();
  check("quick add mobil: přes celou obrazovku", Boolean(box && box.width >= 389 && box.height >= 843), `${box?.width}×${box?.height}`);
  await qaType(page, "příjem Servind 5000 Kč");
  const [a, b] = [await dialog.getByLabel("Typ").boundingBox(), await dialog.getByLabel(/^Částka/).boundingBox()];
  check("quick add mobil: pole pod sebou", Boolean(a && b && Math.abs(a.x - b.x) < 2 && b.y > a.y), `${a?.x}/${b?.x}`);
  const saveBox = await dialog.getByTestId("quick-add-save").boundingBox();
  check("quick add mobil: Uložit ve výřezu a ≥ 44 px", Boolean(saveBox && saveBox.y + saveBox.height <= 844 && saveBox.height >= 44), JSON.stringify(saveBox));
  check("quick add mobil: bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  await page.screenshot({ path: `${OUT}quick-add-mobile.png` });
  await dialog.getByTestId("quick-add-save").tap();
  await dialog.getByTestId("quick-add-saved").waitFor({ timeout: 4000 }).catch(() => undefined);
  check("quick add mobil: uloženo", (await dialog.getByTestId("quick-add-saved").count()) === 1);
  await page.screenshot({ path: `${OUT}quick-add-mobile-saved.png` });
  check("quick add mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// login: žádné Rychlé přidání ani dotazy /quick-add; neautorizovaný dotaz = 401
{
  const requests = [];
  const { ctx, page } = await open("/login", {
    setup: async (p) => {
      p.on("request", (r) => requests.push(new URL(r.url()).pathname));
      await p.route("**/auth/session/validate", (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ valid: false, auth_disabled: false }) }),
      );
    },
  });
  await page.keyboard.press("Control+Shift+K");
  await page.waitForTimeout(200);
  check("login: bez Rychlého přidání", (await page.getByRole("dialog").count()) === 0 && (await page.getByRole("button", { name: /Rychlé přidání/ }).count()) === 0);
  check("login: žádné dotazy /quick-add", !requests.some((r) => r.startsWith("/quick-add")));
  await ctx.addCookies([{ name: "standa_hub_session", value: "expired", domain: "127.0.0.1", path: "/" }]);
  const status = await page.evaluate(async () =>
    (await fetch("http://127.0.0.1:8000/quick-add/parse", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "oběd 100 Kč" }) })).status,
  );
  check("quick add: bez platné session 401", status === 401, String(status));
  await ctx.close();
}
{
  const { ctx, page } = await open("/", { reducedMotion: "reduce" });
  await page.keyboard.press("Control+Shift+K");
  await page.waitForTimeout(150);
  const anim = await qaDialog(page).evaluate((d) => getComputedStyle(d).animationName);
  check("quick add reduced motion: bez animace", anim === "none", anim);
  await ctx.close();
}

// 18) Roadmap 4F – Řídicí centrum na míru: registr widgetů, rozložení v localStorage (klíč verze 1).
const LAYOUT_KEY = "standa-hub:dashboard-layout:v1";
const DEFAULT_ORDER = ["daily_briefing", "weekly_review", "today", "attention", "key_metrics", "goals", "upcoming", "work", "finance", "games", "quick_actions"];
const widgetOrder = (page) =>
  page.evaluate(() =>
    [...document.querySelectorAll("[data-widget]")].sort((a, b) => Number(a.style.order) - Number(b.style.order)).map((el) => el.getAttribute("data-widget")),
  );
const storedLayout = (page) => page.evaluate((k) => localStorage.getItem(k), LAYOUT_KEY);
const focusedName = (page) => page.evaluate(() => document.activeElement?.getAttribute("aria-label") || document.activeElement?.textContent?.trim() || "");
function countRequests(page) {
  const counts = {};
  page.on("request", (r) => {
    const path = new URL(r.url()).pathname;
    if (["/dashboard", "/briefing/today", "/weekly-review"].includes(path)) counts[path] = (counts[path] || 0) + 1;
  });
  return counts;
}
{
  let counts = {};
  const { ctx, page, errors } = await open("/", { setup: async (p) => (counts = countRequests(p)) });
  check("dashboard: výchozí pořadí widgetů", JSON.stringify(await widgetOrder(page)) === JSON.stringify(DEFAULT_ORDER), (await widgetOrder(page)).join(","));
  check("dashboard: normální režim bez ovládání úprav", (await page.getByRole("button", { name: /^Posunout/ }).count()) === 0 && (await page.getByRole("button", { name: /^Skrýt widget/ }).count()) === 0);
  check("dashboard: bez uloženého rozložení nic v localStorage", (await storedLayout(page)) === null);
  const widths = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll("[data-widget]")].map((el) => [el.getAttribute("data-widget"), Math.round(el.getBoundingClientRect().width)])));
  check("dashboard: výchozí vyvážení (přehled 2/3, týden 1/3, čísla celá šířka)", widths.daily_briefing > widths.weekly_review * 1.8 && widths.key_metrics > widths.daily_briefing * 1.4 && widths.work === widths.goals, JSON.stringify(widths));
  check("dashboard: jeden dotaz na každý zdroj", counts["/dashboard"] === 1 && counts["/briefing/today"] === 1 && counts["/weekly-review"] === 1, JSON.stringify(counts));
  await page.screenshot({ path: `${OUT}dashboard-default.png`, fullPage: true });

  await page.getByRole("button", { name: "Upravit dashboard" }).click();
  await page.waitForTimeout(100);
  check("dashboard úpravy: režim úprav je zřetelný", (await page.getByRole("note").filter({ hasText: "Režim úprav" }).count()) === 1);
  check("dashboard úpravy: fokus na Hotovo", (await focusedName(page)) === "Hotovo");
  check("dashboard úpravy: každý widget je pojmenovaná skupina", (await page.getByRole("group", { name: "Finance" }).count()) === 1 && (await page.locator('[role="group"][aria-labelledby^="widget-"]').count()) === 11);
  check(
    "dashboard úpravy: obsah widgetů je neaktivní (inert)",
    await page.evaluate(() => {
      const a = document.querySelector('[data-widget="today"] a[href="/planner"]');
      a?.focus();
      return Boolean(a?.closest("[inert]")) && document.activeElement !== a;
    }),
  );
  check("dashboard úpravy: první nahoru / poslední dolů zakázané", (await page.getByRole("button", { name: "Posunout nahoru: Denní přehled" }).isDisabled()) && (await page.getByRole("button", { name: "Posunout dolů: Rychlé akce" }).isDisabled()));
  check("dashboard úpravy: velikost jen z povolených", JSON.stringify(await page.getByLabel("Velikost: Práce").locator("option").allInnerTexts()) === JSON.stringify(["Malý", "Střední"]));
  await page.screenshot({ path: `${OUT}dashboard-customize.png`, fullPage: true });

  await page.getByRole("button", { name: "Posunout dolů: Denní přehled" }).click();
  await page.waitForTimeout(100);
  let order = await widgetOrder(page);
  check("dashboard úpravy: přesun dolů", order[0] === "weekly_review" && order[1] === "daily_briefing", order.slice(0, 3).join(","));
  check("dashboard úpravy: fokus zůstává na tlačítku", (await focusedName(page)) === "Posunout dolů: Denní přehled");
  check("dashboard úpravy: přesun ohlášen čtečce", /Denní přehled: pozice 2 z 11/.test(await page.getByRole("status").filter({ hasText: "pozice" }).innerText().catch(() => "")));
  check("dashboard úpravy: uloženo hned", JSON.parse((await storedLayout(page)) || "{}").widgets?.[0]?.id === "weekly_review");

  await page.getByRole("button", { name: "Skrýt widget: Hry" }).click();
  await page.waitForTimeout(100);
  check("dashboard úpravy: skrytý widget zmizí", !(await widgetOrder(page)).includes("games"));
  const restore = page.getByRole("button", { name: "Zobrazit widget: Hry" });
  check("dashboard úpravy: Skryté widgety s obnovou + fokus", (await restore.count()) === 1 && (await focusedName(page)) === "Zobrazit widget: Hry");
  await page.screenshot({ path: `${OUT}dashboard-hidden.png`, fullPage: true });

  await page.getByLabel("Velikost: Finance").selectOption("medium");
  await page.waitForTimeout(100);
  const fin = page.locator('[data-widget="finance"]');
  check("dashboard úpravy: změna velikosti hned v rozložení", (await fin.getAttribute("data-size")) === "medium" && Math.round((await fin.boundingBox()).width) > widths.finance * 1.3, String((await fin.boundingBox())?.width));
  await page.screenshot({ path: `${OUT}dashboard-resized.png`, fullPage: true });
  check("dashboard úpravy: úpravy nic znovu nenačítají", counts["/dashboard"] === 1 && counts["/briefing/today"] === 1 && counts["/weekly-review"] === 1, JSON.stringify(counts));

  await page.getByRole("button", { name: "Hotovo" }).click();
  await page.waitForTimeout(150);
  check("dashboard: Hotovo vrátí čistý režim a fokus", (await page.getByRole("button", { name: /^Posunout/ }).count()) === 0 && (await focusedName(page)) === "Upravit dashboard");
  await page.screenshot({ path: `${OUT}dashboard-reordered.png`, fullPage: true });

  // regrese shellu: vyhledávání, Rychlé přidání, zvonek
  await page.keyboard.press("Control+k");
  check("dashboard: Ctrl+K dál otevírá vyhledávání", (await page.getByRole("dialog", { name: "Hledat v Standa Hubu" }).count()) === 1);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+Shift+K");
  check("dashboard: Ctrl+Shift+K dál otevírá Rychlé přidání", (await page.getByRole("dialog", { name: "Rychlé přidání" }).count()) === 1);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /^Notifikace/ }).click();
  check("dashboard: zvonek dál otevírá notifikace", (await page.getByRole("dialog").count()) === 1);
  await page.keyboard.press("Escape");

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  order = await widgetOrder(page);
  check("dashboard: po obnovení stránky rozložení drží", order[0] === "weekly_review" && !order.includes("games") && (await page.locator('[data-widget="finance"]').getAttribute("data-size")) === "medium", order.join(","));

  await page.getByRole("button", { name: "Upravit dashboard" }).click();
  await page.getByRole("button", { name: "Zobrazit widget: Hry" }).click();
  check("dashboard úpravy: obnova skrytého widgetu", (await widgetOrder(page)).includes("games") && (await focusedName(page)) === "Skrýt widget: Hry");
  await page.getByRole("button", { name: "Obnovit výchozí rozložení" }).click();
  const dlg = page.getByRole("dialog", { name: "Obnovit výchozí rozložení?" });
  check("dashboard: reset se potvrzuje dialogem", (await dlg.count()) === 1 && JSON.parse((await storedLayout(page)) || "{}").widgets?.[0]?.id === "weekly_review");
  await dlg.getByRole("button", { name: "Obnovit výchozí" }).click();
  await page.waitForTimeout(150);
  check("dashboard: reset = výchozí pořadí a velikosti", JSON.stringify(await widgetOrder(page)) === JSON.stringify(DEFAULT_ORDER) && (await storedLayout(page)) === null && (await page.locator('[data-widget="finance"]').getAttribute("data-size")) === "small");
  check("dashboard: reset tlačítko zakázané u výchozího", await page.getByRole("button", { name: "Obnovit výchozí rozložení" }).isDisabled());
  check("dashboard: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// klávesnice: celé úpravy bez myši
{
  const { ctx, page, errors } = await open("/");
  const tabTo = async (name, max = 60) => {
    for (let i = 0; i < max; i++) {
      if ((await focusedName(page)) === name) return true;
      await page.keyboard.press("Tab");
    }
    return false;
  };
  check("klávesnice: Tab na Upravit dashboard", await tabTo("Upravit dashboard"));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  check("klávesnice: Enter zapne úpravy, fokus na Hotovo", (await focusedName(page)) === "Hotovo");
  check("klávesnice: Tab k posunu widgetu", await tabTo("Posunout dolů: Týdenní přehled"));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  let order = await widgetOrder(page);
  check("klávesnice: dvakrát dolů (fokus drží)", order.indexOf("weekly_review") === 3 && (await focusedName(page)) === "Posunout dolů: Týdenní přehled", order.join(","));
  await page.keyboard.press("Shift+Tab");
  check("klávesnice: posun nahoru", (await focusedName(page)) === "Posunout nahoru: Týdenní přehled");
  await page.keyboard.press("Space");
  await page.waitForTimeout(100);
  check("klávesnice: nahoru o jednu", (await widgetOrder(page)).indexOf("weekly_review") === 2);
  check("klávesnice: Tab ke Skrýt", await tabTo("Skrýt widget: Týdenní přehled", 6));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  check("klávesnice: skrytí → fokus na obnovu", (await focusedName(page)) === "Zobrazit widget: Týdenní přehled");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  check("klávesnice: obnova → fokus na Skrýt", (await focusedName(page)) === "Skrýt widget: Týdenní přehled" && (await widgetOrder(page)).includes("weekly_review"));
  await page.keyboard.press("Shift+Tab");
  check("klávesnice: výběr velikosti má popisek", (await page.evaluate(() => document.activeElement?.labels?.[0]?.textContent?.trim())) === "Velikost: Týdenní přehled");
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(100);
  check("klávesnice: velikost šipkou", (await page.locator('[data-widget="weekly_review"]').getAttribute("data-size")) === "medium");
  await page.getByRole("button", { name: "Obnovit výchozí rozložení" }).focus();
  await page.keyboard.press("Enter");
  const dlg = page.getByRole("dialog", { name: "Obnovit výchozí rozložení?" });
  check("klávesnice: reset otevře dialog", (await dlg.count()) === 1);
  check("klávesnice: v dialogu potvrzení", await tabTo("Obnovit výchozí", 4));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  check("klávesnice: reset proveden, fokus na Hotovo", JSON.stringify(await widgetOrder(page)) === JSON.stringify(DEFAULT_ORDER) && (await focusedName(page)) === "Hotovo");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  check("klávesnice: Hotovo Enterem", (await focusedName(page)) === "Upravit dashboard");
  check("klávesnice: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// uložená data: poškozená, neznámá, vše skryté, žádné bliknutí výchozího
async function openSeeded(value, opts = {}) {
  let counts = {};
  const res = await open("/", {
    ...opts,
    setup: async (p) => {
      counts = countRequests(p);
      await p.addInitScript(([k, v]) => {
        if (!sessionStorage.getItem("seeded")) {
          localStorage.setItem(k, v);
          sessionStorage.setItem("seeded", "1");
        }
        window.__seenGames = false;
        new MutationObserver(() => {
          if (document.querySelector('[data-widget="games"]')) window.__seenGames = true;
        }).observe(document, { subtree: true, childList: true });
      }, [LAYOUT_KEY, value]);
    },
  });
  return { ...res, counts };
}
{
  const { ctx, page, errors } = await openSeeded("{not json");
  check("dashboard: poškozený JSON → výchozí rozložení bez chyby", JSON.stringify(await widgetOrder(page)) === JSON.stringify(DEFAULT_ORDER) && errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const seeded = JSON.stringify({ version: 1, widgets: [
    { id: "finance", visible: true, order: 10, size: "medium" },
    { id: "zastaraly_widget", visible: true, order: 20, size: "small" },
    { id: "games", visible: false, order: 30, size: "full" },
    { id: "work", visible: true, order: 40, size: "obrovsky" },
  ] });
  const { ctx, page, errors } = await openSeeded(seeded);
  const order = await widgetOrder(page);
  check("dashboard: uložené volby zachovány, neznámé zahozeno, chybějící doplněno", order.length === 10 && !order.includes("games") && !order.includes("zastaraly_widget") && order.indexOf("finance") < order.indexOf("work") && (await page.locator('[data-widget="work"]').getAttribute("data-size")) === "small", order.join(","));
  check("dashboard: uložené rozložení bez bliknutí výchozího", !(await page.evaluate(() => window.__seenGames)));
  check("dashboard: neplatná data bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const allHidden = JSON.stringify({ version: 1, widgets: DEFAULT_ORDER.map((id, i) => ({ id, visible: false, order: (i + 1) * 10, size: "full" })) });
  const { ctx, page, counts } = await openSeeded(allHidden);
  check("dashboard: vše skryté → prázdný stav s cestou zpět", (await page.getByText("Všechny widgety jsou skryté.").count()) === 1 && (await page.getByRole("button", { name: "Upravit dashboard" }).count()) >= 1);
  check("dashboard: skryté widgety nic nenačítají", !counts["/dashboard"] && !counts["/briefing/today"] && !counts["/weekly-review"], JSON.stringify(counts));
  await page.getByRole("button", { name: "Upravit dashboard" }).first().click();
  await page.getByRole("button", { name: "Zobrazit widget: Finance" }).click();
  await page.waitForTimeout(400);
  check("dashboard: zobrazení widgetu načte jen jeho data", counts["/dashboard"] === 1 && !counts["/briefing/today"], JSON.stringify(counts));
  await ctx.close();
}
// mobil 390 px: úpravy bez tažení, ovládání se vejde, rozložení drží po obnovení
{
  const { ctx, page, errors } = await open("/", { width: 390, height: 844 });
  await page.getByRole("button", { name: "Upravit dashboard" }).tap();
  await page.waitForTimeout(100);
  const groups = page.locator('[role="group"][aria-labelledby^="widget-"]');
  const boxes = await groups.evaluateAll((els) => els.map((el) => el.getBoundingClientRect()).map((r) => [Math.round(r.x), Math.round(r.right)]));
  check("dashboard mobil: jeden widget na řádek, ovládání se vejde", boxes.every(([x, r]) => x >= 0 && r <= 390) && new Set(boxes.map(([x]) => x)).size === 1, JSON.stringify(boxes.slice(0, 3)));
  check("dashboard mobil: bez přetečení v úpravách", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  const up = await page.getByRole("button", { name: "Posunout nahoru: Finance" }).boundingBox();
  check("dashboard mobil: tlačítka ≥ 44 px", Boolean(up && up.height >= 44 && up.width >= 44), JSON.stringify(up));
  await page.screenshot({ path: `${OUT}dashboard-mobile-customize.png` });
  await page.getByRole("button", { name: "Posunout nahoru: Finance" }).tap();
  await page.getByRole("button", { name: "Skrýt widget: Cíle" }).tap();
  await page.waitForTimeout(100);
  let order = await widgetOrder(page);
  check("dashboard mobil: přesun a skrytí", order.indexOf("finance") === order.indexOf("work") - 1 && !order.includes("goals"), order.join(","));
  await page.getByRole("button", { name: "Zobrazit widget: Cíle" }).tap();
  check("dashboard mobil: obnova", (await widgetOrder(page)).includes("goals"));
  await page.getByRole("button", { name: "Skrýt widget: Cíle" }).tap();
  await page.getByRole("button", { name: "Hotovo" }).tap();
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(400);
  order = await widgetOrder(page);
  check("dashboard mobil: po obnovení drží", order.indexOf("finance") === order.indexOf("work") - 1 && !order.includes("goals"));
  check("dashboard mobil: bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  await page.screenshot({ path: `${OUT}dashboard-mobile.png` });
  check("dashboard mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}

// 19) Roadmap 4G – režim Dnes (/today), mock GET /today = odpovědi skutečného today_service.
await fetch("http://127.0.0.1:8000/__mock/today/reset", { method: "POST" });
const todayFixture = (name) => readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8");
const serveToday = (body, status = 200) => async (p) =>
  p.route("http://127.0.0.1:8000/today", (route) => route.fulfill({ status, contentType: "application/json", body }));
{
  let todayCalls = 0;
  const { ctx, page, errors } = await open("/today", { setup: async (p) => p.on("request", (r) => { const u = new URL(r.url()); if (u.port === "8000" && u.pathname === "/today") todayCalls++; }) });
  const todayAvatar = page.locator('main [data-testid="jarvis-avatar"]').first();
  check("jarvis dnes: idle avatar sm je viditelný", await todayAvatar.isVisible() && (await todayAvatar.getAttribute("data-jarvis-state")) === "idle" && (await todayAvatar.getAttribute("data-jarvis-size")) === "sm");
  check("dnes: jeden dotaz /today", todayCalls === 1, String(todayCalls));
  check("dnes: h1 Dnes + český datum", (await page.getByRole("heading", { level: 1, name: "Dnes" }).count()) === 1 && (await page.getByText("Neděle 11. 10. 2026").count()) >= 1);
  check("dnes: souhrn s další položkou", (await page.getByRole("heading", { name: "Další: Fyzioterapie v 18:30" }).count()) === 1 && (await page.getByText(/za 4 h/).count()) >= 1);
  const section = (id) => page.locator(`[data-section="${id}"]`);
  const ids = (loc) => loc.locator("[data-item]").evaluateAll((els) => els.map((e) => e.getAttribute("data-item")));
  const att = await ids(section("attention"));
  check("dnes: Vyžaduje pozornost (po termínu nejdřív)", att[0] === "assignment:1" && att.length === 4 && (await section("attention").getByText("Důležité").count()) >= 1, att.join(","));
  check("dnes: dnešní plán z plánovače", (await ids(section("plan"))).length >= 1 && (await section("plan").getByText(/^Plán #\d/).count()) >= 1);
  const tl = await ids(section("timeline"));
  check("dnes: časová osa chronologicky, bez času „Během dne“", JSON.stringify(tl.slice(0, 3)) === JSON.stringify(["reminder:4", "reminder:7", "reminder:1"]) && (await section("timeline").getByRole("heading", { name: "Během dne" }).count()) === 1, tl.join(","));
  const next = section("timeline").locator('[aria-current="true"]');
  check("dnes: další položka označená textem (ne jen barvou)", (await next.getAttribute("data-item")) === "reminder:1" && (await next.getByText("Další", { exact: true }).count()) === 1);
  check("dnes: stavy slovem", (await section("timeline").getByText("proběhlo").count()) >= 1 && (await section("timeline").getByText("k vyřízení").count()) >= 1);
  const doneSummary = section("timeline").locator("summary");
  check("dnes: hotové sbalené", (await doneSummary.innerText()).includes("Hotovo (1 položka)") && !(await section("timeline").locator('[data-item="reminder:6"]').isVisible()));
  await doneSummary.click();
  check("dnes: hotové se rozbalí", await section("timeline").locator('[data-item="reminder:6"]').isVisible());
  const all = await page.locator("[data-item]").evaluateAll((els) => els.map((e) => e.getAttribute("data-item")));
  check("dnes: žádný záznam dvakrát", all.length === new Set(all).size, all.join(","));
  check("dnes: Potom max. 3", (await ids(section("upcoming"))).length <= 3 && (await ids(section("upcoming"))).length >= 1);
  await page.screenshot({ path: `${OUT}today.png`, fullPage: true });

  await page.getByRole("button", { name: "Přidat" }).click();
  check("dnes: + Přidat otevře Rychlé přidání", (await page.getByRole("dialog", { name: "Rychlé přidání" }).count()) === 1);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+k");
  const search = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  await search.getByRole("combobox").fill("dnes");
  await page.waitForTimeout(400);
  check("dnes: Ctrl+K funguje a najde stránku Dnes", (await search.getByRole("option").first().innerText()).startsWith("Dnes"));
  await page.keyboard.press("Escape");
  check("dnes: položka v navigaci aktivní", (await page.locator('nav a[href="/today"][aria-current="page"]').count()) >= 1);

  await section("attention").getByRole("link", { name: /Sada/ }).click();
  await page.waitForURL("**/school?assignment=1", { timeout: 5000 }).catch(() => undefined);
  check("dnes: položka vede na záznam (deep link)", /\/school\?assignment=1$/.test(page.url()), page.url());
  await page.waitForTimeout(1000);
  check("dnes: záznam zvýrazněn", await page.evaluate(() => document.activeElement?.getAttribute("data-search-target") === "assignment-1"));
  check("dnes: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/today", { setup: serveToday(todayFixture("today-empty")) });
  check("dnes prázdný: záměrný prázdný stav", (await page.getByTestId("today-empty").innerText()) === "Dnes nemáš nic naplánovaného." && (await page.locator("[data-section]").count()) === 0);
  check("dnes prázdný: Přidat + Plánovač", (await page.getByRole("button", { name: "Přidat" }).count()) >= 1 && (await page.getByRole("link", { name: "Plánovač →" }).count()) === 1);
  await page.screenshot({ path: `${OUT}today-empty.png` });
  check("dnes prázdný: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/today", { setup: serveToday(todayFixture("today-partial")) });
  const plan = page.locator('[data-section="plan"]');
  check("dnes částečná chyba: jen sekce plánu hlásí chybu", (await plan.getByText("Dnešní plán se nepodařilo sestavit.").count()) === 1 && (await page.getByText("se nepodařilo").count()) === 1);
  check("dnes částečná chyba: ostatní sekce běží", (await page.locator('[data-section="timeline"] [data-item]').count()) >= 3 && (await page.locator('[data-section="attention"] [data-item]').count()) >= 1);
  await page.screenshot({ path: `${OUT}today-partial.png`, fullPage: true });
  check("dnes částečná chyba: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const { ctx, page } = await open("/today", { setup: serveToday(JSON.stringify({ detail: "boom" }), 500) });
  check("dnes výpadek: chyba s opakováním", (await page.getByRole("button", { name: /Zkusit znovu/ }).count()) === 1);
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/today", { width: 390, height: 844 });
  const head = await page.getByRole("heading", { name: /^Další:/ }).boundingBox();
  check("dnes mobil: další položka v prvním výřezu", Boolean(head && head.y + head.height < 844), JSON.stringify(head));
  const add = await page.getByRole("button", { name: "Přidat" }).boundingBox();
  check("dnes mobil: Přidat nahoře a ≥ 44 px", Boolean(add && add.y < 400 && add.height >= 44), JSON.stringify(add));
  check("dnes mobil: bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  const small = await page.locator("[data-item] > a").evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().height < 44).length);
  check("dnes mobil: položky ≥ 44 px", small === 0, String(small));
  await page.screenshot({ path: `${OUT}today-mobile.png`, fullPage: true });
  await page.getByRole("button", { name: "Rychlé přidání", exact: true }).tap();
  check("dnes mobil: Rychlé přidání z hlavičky", (await page.getByRole("dialog", { name: "Rychlé přidání" }).count()) === 1);
  check("dnes mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
for (const [scheme, motion] of [["light", "no-preference"], ["dark", "reduce"]]) {
  const { ctx, page } = await open("/today", { scheme, reducedMotion: motion });
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (scheme === "light") check("dnes (světlý motiv OS): zůstává tmavý", !/255, 255, 255/.test(bg), bg);
  else {
    const anims = await page.evaluate(() => [...document.querySelectorAll("main *")].filter((el) => getComputedStyle(el).animationName !== "none").length);
    check("dnes reduced motion: bez animací", anims === 0, String(anims));
  }
  await ctx.close();
}

// 20) Roadmap 4H – akce z režimu Dnes (mock: stav dne po akci = fixture ze skutečného backendu).
const MOCK = "http://127.0.0.1:8000";
const todayMock = async (path) => (await fetch(MOCK + path, { method: "POST" })).json();
const todayCalls = async () => (await fetch(`${MOCK}/__mock/today`)).json();
const rowOf = (page, id) => page.locator(`[data-item="${id}"]`);
const focusedLabel = (page) => page.evaluate(() => document.activeElement?.getAttribute("aria-label") || document.activeElement?.textContent?.trim() || "");
async function countTodayGets(page) {
  const counter = { n: 0 };
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.port === "8000" && u.pathname === "/today" && r.method() === "GET") counter.n++;
  });
  return counter;
}
{
  await todayMock("/__mock/today/reset");
  let gets;
  const { ctx, page, errors } = await open("/today", { setup: async (p) => (gets = await countTodayGets(p)) });
  const r7 = rowOf(page, "reminder:7");
  check("dnes akce: připomínka má Hotovo + Odložit", (await r7.getByRole("button", { name: "Dokončit připomínku: Vyndat prádlo" }).count()) === 1 && (await r7.getByRole("button", { name: "Odložit připomínku: Vyndat prádlo" }).count()) === 1);
  // Regrese 4H: „+N min" se počítá od teď – budoucí připomínku by odložení přiblížilo → jen Hotovo
  check("dnes akce: nadcházející připomínka jen Hotovo", (await rowOf(page, "reminder:1").getByRole("button").count()) === 1 && (await rowOf(page, "reminder:1").getByRole("button", { name: /^Odložit/ }).count()) === 0);
  check("dnes akce: opakovaná / hotová / Potom bez akcí", (await rowOf(page, "reminder:4").getByRole("button").count()) === 0 && (await page.locator('[data-section="upcoming"] button').count()) === 0);
  check("dnes akce: úkol jen Hotovo", (await rowOf(page, "assignment:1").getByRole("button").count()) === 1);
  check("dnes akce: zkouška = odkaz Zapsat výsledek", (await rowOf(page, "exam:3").getByRole("link", { name: "Zapsat výsledek zkoušky: test" }).getAttribute("href")) === "/school?exam=3");
  await page.screenshot({ path: `${OUT}today-actions.png`, fullPage: true });

  // Hotovo připomínky → jedno obnovení, řádek do Hotovo, fokus na další akční řádek
  const before = gets.n;
  await r7.getByRole("button", { name: "Dokončit připomínku: Vyndat prádlo" }).click();
  await page.getByText("Připomínka „Vyndat prádlo“ je hotová.").waitFor({ timeout: 5000 }).catch(() => undefined);
  await page.waitForTimeout(300);
  check("dnes akce: hotovo ohlášeno (role=status)", (await page.locator('[data-today-notice][role="status"]').innerText()).includes("je hotová"));
  check("dnes akce: jedno obnovení /today", gets.n - before === 1, String(gets.n - before));
  check("dnes akce: připomínka v Hotovo", (await rowOf(page, "reminder:7").getAttribute("data-status")) === "done" && (await page.locator('[data-section="timeline"] summary').innerText()).includes("2 položky"));
  check("dnes akce: fokus na další akční řádek", (await focusedLabel(page)) === "Dokončit připomínku: Fyzioterapie", await focusedLabel(page));
  check("dnes akce: volání se zdrojem Dnes", JSON.stringify(await todayCalls()) === JSON.stringify(["done:reminder:7"]));
  await page.screenshot({ path: `${OUT}today-action-success.png` });

  // Odložit: volby ze serveru, Esc zavře a vrátí fokus
  await todayMock("/__mock/today/reset");
  await page.getByRole("button", { name: "Obnovit", exact: true }).click();
  await page.waitForTimeout(500);
  const toggle = rowOf(page, "reminder:7").getByRole("button", { name: "Odložit připomínku: Vyndat prádlo" });
  await toggle.click();
  const group = page.getByRole("group", { name: "Odložit „Vyndat prádlo“ – na kdy?" });
  check("dnes odložit: nabídka s pevnými volbami", JSON.stringify(await group.getByRole("button").allInnerTexts()) === JSON.stringify(["+15 min", "+1 h", "+3 h", "Zítra 8:00", "Zrušit"]) && (await toggle.getAttribute("aria-expanded")) === "true");
  check("dnes odložit: fokus na první volbu", (await focusedLabel(page)) === "+15 min: Vyndat prádlo");
  await page.screenshot({ path: `${OUT}today-snooze.png` });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(80);
  check("dnes odložit: Esc zavře a vrátí fokus", (await group.count()) === 0 && (await focusedLabel(page)) === "Odložit připomínku: Vyndat prádlo");
  check("dnes odložit: Esc nespustí globální zkratky", (await page.getByRole("dialog").count()) === 0);
  await toggle.click();
  await group.getByRole("button", { name: "Zítra 8:00: Vyndat prádlo" }).click();
  await page.getByText(/^Odloženo: Vyndat prádlo/).waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes odložit: zítra 8:00 (pražské datum ze serveru)", (await todayCalls()).includes("snooze:reminder:7:2026-10-12T08:00"));
  check("dnes odložit: obnoveno", (await page.locator('[data-today-notice]').innerText()).includes("Odloženo: Vyndat prádlo (Zítra 8:00)"));

  // úkol: prepare + confirm, zmizí z Pozornosti, Vrátit = existující undo
  await todayMock("/__mock/today/reset");
  await page.getByRole("button", { name: "Obnovit", exact: true }).click();
  await page.waitForTimeout(500);
  await rowOf(page, "assignment:1").getByRole("button", { name: "Dokončit úkol: Sada" }).click();
  await page.getByText("Úkol „Sada“ je hotový.").waitFor({ timeout: 5000 }).catch(() => undefined);
  await page.waitForTimeout(300);
  check("dnes úkol: prepare + confirm", JSON.stringify(await todayCalls()) === JSON.stringify(["prepare:assignment:1", "confirm:today-1"]));
  check("dnes úkol: zmizí z Pozornosti", (await page.locator('[data-section="attention"] [data-item="assignment:1"]').count()) === 0);
  const undo = page.locator("[data-today-notice]").getByRole("button", { name: "Vrátit" });
  check("dnes úkol: nabídne Vrátit (existující undo)", (await undo.count()) === 1);
  await undo.click();
  await page.getByText(/^Vráceno/).waitFor({ timeout: 5000 }).catch(() => undefined);
  await page.waitForTimeout(300);
  check("dnes úkol: vrácení přes /actions/undo + confirm", JSON.stringify((await todayCalls()).slice(2)) === JSON.stringify(["undo:today-1", "confirm:today-undo-today-1"]) && (await page.locator('[data-section="attention"] [data-item="assignment:1"]').count()) === 1);

  // selhání: řádek zůstane, Zkusit znovu potvrdí TUTÉŽ pending akci
  await todayMock("/__mock/today/reset");
  await page.getByRole("button", { name: "Obnovit", exact: true }).click();
  await page.waitForTimeout(500);
  await todayMock("/__mock/today/fail?mode=confirm_error");
  await rowOf(page, "assignment:1").getByRole("button", { name: "Dokončit úkol: Sada" }).click();
  const alert = rowOf(page, "assignment:1").getByRole("alert");
  await alert.waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes chyba: řádek zůstane s hláškou", (await alert.innerText()).includes("Akci se nepodařilo provést"));
  check("dnes chyba: zbytek stránky běží", (await page.locator('[data-section="timeline"] [data-item]').count()) >= 5);
  await page.screenshot({ path: `${OUT}today-action-error.png` });
  await alert.getByRole("button", { name: "Zkusit znovu" }).click();
  await page.getByText("Úkol „Sada“ je hotový.").waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes chyba: opakování bez druhé pending akce", JSON.stringify(await todayCalls()) === JSON.stringify(["prepare:assignment:1", "confirm:today-1", "confirm:today-1"]));

  // zastaralé: už hotová jinde → hláška + obnovený stav, žádné opakování
  await todayMock("/__mock/today/reset");
  await page.getByRole("button", { name: "Obnovit", exact: true }).click();
  await page.waitForTimeout(500);
  await todayMock("/__mock/today/fail?mode=stale");
  await rowOf(page, "reminder:7").getByRole("button", { name: "Dokončit připomínku: Vyndat prádlo" }).click();
  await page.getByText(/už je hotová nebo zrušená/).waitFor({ timeout: 5000 }).catch(() => undefined);
  await page.waitForTimeout(300);
  check("dnes zastaralé: hláška a obnovený stav", (await page.locator("[data-today-notice]").innerText()).includes("Stav jsem obnovil") && (await rowOf(page, "reminder:7").getAttribute("data-status")) === "done" && (await rowOf(page, "reminder:7").getByRole("alert").count()) === 0);

  // obecná chyba připomínky → Zkusit znovu
  await todayMock("/__mock/today/reset");
  await page.getByRole("button", { name: "Obnovit", exact: true }).click();
  await page.waitForTimeout(500);
  await todayMock("/__mock/today/fail?mode=error");
  await rowOf(page, "reminder:1").getByRole("button", { name: "Dokončit připomínku: Fyzioterapie" }).click();
  await rowOf(page, "reminder:1").getByRole("alert").waitFor({ timeout: 5000 }).catch(() => undefined);
  await rowOf(page, "reminder:1").getByRole("button", { name: "Zkusit znovu" }).click();
  await page.getByText("Připomínka „Fyzioterapie“ je hotová.").waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes chyba připomínky: opakování projde", (await todayCalls()).filter((c) => c === "done:reminder:1").length === 2);

  // regrese: odkaz řádku, vyhledávání, Rychlé přidání
  await page.keyboard.press("Control+k");
  check("dnes akce: Ctrl+K dál funguje", (await page.getByRole("dialog", { name: "Hledat v Standa Hubu" }).count()) === 1);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Přidat" }).click();
  check("dnes akce: Rychlé přidání dál funguje", (await page.getByRole("dialog", { name: "Rychlé přidání" }).count()) === 1);
  await page.keyboard.press("Escape");
  await rowOf(page, "exam:3").getByRole("link", { name: "Zapsat výsledek zkoušky: test" }).click();
  await page.waitForURL("**/school?exam=3", { timeout: 5000 }).catch(() => undefined);
  check("dnes akce: Zapsat výsledek vede do Školy", /\/school\?exam=3$/.test(page.url()), page.url());
  check("dnes akce: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// klávesnice: Hotovo a Odložit bez myši
{
  await todayMock("/__mock/today/reset");
  const { ctx, page, errors } = await open("/today");
  const tabTo = async (name, max = 80) => {
    for (let i = 0; i < max; i++) {
      if ((await focusedLabel(page)) === name) return true;
      await page.keyboard.press("Tab");
    }
    return false;
  };
  check("klávesnice dnes: Tab na Hotovo připomínky", await tabTo("Dokončit připomínku: Vyndat prádlo"));
  await page.keyboard.press("Enter");
  await page.getByText("Připomínka „Vyndat prádlo“ je hotová.").waitFor({ timeout: 5000 }).catch(() => undefined);
  await page.waitForTimeout(300);
  check("klávesnice dnes: Enter dokončí, fokus dál", (await focusedLabel(page)) === "Dokončit připomínku: Fyzioterapie");
  // Odložit jen u připomínky, která už zazněla (nadcházející „Fyzioterapie" ho nenabízí)
  await todayMock("/__mock/today/reset");
  await page.reload();
  await page.waitForTimeout(500);
  await tabTo("Dokončit připomínku: Vyndat prádlo");
  await page.keyboard.press("Tab");
  check("klávesnice dnes: Tab na Odložit", (await focusedLabel(page)) === "Odložit připomínku: Vyndat prádlo");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(80);
  await page.keyboard.press("Tab");
  check("klávesnice dnes: Tab na volbu +1 h", (await focusedLabel(page)) === "+1 h: Vyndat prádlo");
  await page.keyboard.press("Enter");
  await page.getByText(/^Odloženo: Vyndat prádlo \(\+1 h\)/).waitFor({ timeout: 5000 }).catch(() => undefined);
  check("klávesnice dnes: odloženo o hodinu", (await todayCalls()).includes("snooze:reminder:7:+60"));
  check("klávesnice dnes: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// mobil 390 px: akce ≥ 44 px, odložení se vejde, žádné přetečení
{
  await todayMock("/__mock/today/reset");
  const { ctx, page, errors } = await open("/today", { width: 390, height: 844 });
  const row = rowOf(page, "reminder:7");
  const done = await row.getByRole("button", { name: "Dokončit připomínku: Vyndat prádlo" }).boundingBox();
  check("dnes mobil: Hotovo ≥ 44 px", Boolean(done && done.height >= 44), JSON.stringify(done));
  await row.getByRole("button", { name: "Odložit připomínku: Vyndat prádlo" }).tap();
  const opts = await row.getByRole("group").getByRole("button").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), Math.round(r.height)]; }));
  check("dnes mobil: volby odložení se vejdou a jsou ≥ 44 px", opts.every(([l, r, h]) => l >= 0 && r <= 390 && h >= 44), JSON.stringify(opts));
  check("dnes mobil: bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  const title = await row.getByText(/Vyndat prádlo$/).first().boundingBox();
  const rowBox = await row.boundingBox();
  check("dnes mobil: název nahoře v řádku", Boolean(title && rowBox && title.y - rowBox.y < 80), JSON.stringify({ t: title?.y, r: rowBox?.y }));
  await row.screenshot({ path: `${OUT}today-mobile-actions.png` });
  await row.getByRole("button", { name: "+15 min: Vyndat prádlo" }).tap();
  await page.getByText(/^Odloženo: Vyndat prádlo/).waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes mobil: odložení ťuknutím", (await todayCalls()).includes("snooze:reminder:7:+15"));
  check("dnes mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
  await todayMock("/__mock/today/reset");
}

// 21) Game Enrichment A – herní obrázky. Skutečné assety se necommitují (public/game-assets je gitignore), proto
// test podstrčí manifest (fixtures/game-assets-manifest.json) a neutrální testovací PNG/SVG (NE herní grafika) přes page.route.
const wotReset = () => fetch(`${MOCK}/__mock/wot/reset`, { method: "POST" });
await wotReset();
// Manifest ve tvaru výstupu skriptu (verze 2) se skutečnými metadaty z Tankopedie – sdílený s unit testy.
// Žádný registr tanků: názvy grindů se k vozidlům přiřadí za běhu. Object 279 early (#46849) nemá soubor → chyba načtení.
const TEST_MANIFEST = JSON.parse(readFileSync(new URL("./fixtures/game-assets-manifest.json", import.meta.url), "utf8"));
const MISSING_TANK_FILE = "/game-assets/wot/tanks/46849.png";
const STUB_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 14"><rect width="18" height="14" rx="3" fill="#8b96a8"/></svg>';
async function withGameAssets(p, manifest = TEST_MANIFEST, requests = null) {
  await p.route("**/game-assets/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    requests?.push(path);
    if (path === "/game-assets/manifest.json") {
      return manifest ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(manifest) }) : route.fulfill({ status: 404, body: "" });
    }
    if (path.startsWith("/game-assets/wot/tanks/") && path !== MISSING_TANK_FILE) {
      return route.fulfill({ status: 200, contentType: "image/png", body: stubPng(160, 100, [62, 74, 70]) });
    }
    if (path.startsWith("/game-assets/wot/resources/")) return route.fulfill({ status: 200, contentType: "image/svg+xml", body: STUB_SVG });
    if (path === "/game-assets/mff/characters/luna_snow.png") return route.fulfill({ status: 200, contentType: "image/png", body: stubPng(96, 96, [70, 86, 110]) });
    return route.fulfill({ status: 404, body: "" });
  });
}
/** Podstrčí jiné názvy grindů / postav (jen v prohlížeči) – ověří párování bez úpravy kódu i fixtures. */
const withApiList = (p, path, items) =>
  p.route(`http://127.0.0.1:8000${path}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(items) }));
const imageState = (page, sel) =>
  page.locator(sel).evaluateAll((els) =>
    els.map((el) => {
      const img = el.querySelector("img");
      const r = el.getBoundingClientRect();
      return {
        state: el.getAttribute("data-state"),
        alt: img?.getAttribute("alt") ?? el.getAttribute("aria-label"),
        src: img?.getAttribute("src")?.split("/game-assets/")[1] ?? null,
        loaded: img ? img.complete && img.naturalWidth > 0 : null,
        lazy: img ? img.loading === "lazy" : null,
        text: el.textContent,
        w: Math.round(r.width),
        h: Math.round(r.height),
      };
    }),
  );
const byAlt = (list, alt) => list.find((x) => x.alt === alt);
{
  const { ctx, page, errors } = await open("/wot", { setup: (p) => withGameAssets(p) });
  await page.waitForTimeout(800);
  const row = (tank) => page.locator(`[data-search-target]`).filter({ hasText: tank }).locator('[data-game-image="tank"]');
  const tanks = await imageState(page, '[data-search-target] [data-game-image="tank"]');
  const kranvagn = byAlt(tanks, "Tank Kranvagn");
  check("wot obrázky: tank z manifestu Tankopedie se načte (alt = název)", kranvagn?.state === "image" && kranvagn.loaded === true && kranvagn.src === "wot/tanks/2433.png", JSON.stringify(kranvagn));
  const tvp = byAlt(tanks, "Tank TVP T 50/51");
  check("wot obrázky: tank bez ručního registru se spáruje sám", tvp?.state === "image" && tvp.src === "wot/tanks/2417.png", JSON.stringify(tvp));
  await page.waitForTimeout(300);
  const obj = byAlt(await imageState(page, '[data-game-image="tank"]'), "Tank Object 279 (e)");
  check("wot obrázky: chyba načtení → monogram, žádný rozbitý obrázek", obj?.state === "fallback" && obj.text === "O279", JSON.stringify(obj));
  const sizes = await imageState(page, '[data-search-target] [data-game-image="tank"]');
  check("wot obrázky: pevný rámeček 64 × 40 (žádný posun)", sizes.length >= 3 && sizes.every((x) => x.w === 64 && x.h === 40), JSON.stringify(sizes.map((x) => [x.w, x.h])));
  check("wot obrázky: aktivní grind má tank", (await row("Kranvagn").count()) === 1);
  // Game Enrichment B: splněné grindy jsou v historii (malá miniatura), milníky mají tank taky
  const done = await imageState(page, '[data-section="wot-completed"] [data-game-image="tank"]');
  check("wot obrázky: splněný grind v historii má tank (mimo manifest = monogram)", byAlt(done, "Tank T-100 LT")?.state === "image" && byAlt(done, "Tank Progetto 65")?.state === "fallback" && done.length === 2, JSON.stringify(done.map((x) => [x.alt, x.state])));
  const ms = await imageState(page, '[aria-label="Milníky"] [data-game-image="tank"]');
  check("wot obrázky: milník (Mko) má tank z manifestu", ms.length === 4 && byAlt(ms, "Tank Kranvagn")?.state === "image" && ms.every((x) => x.state === "image" || x.state === "fallback"), JSON.stringify(ms.map((x) => [x.alt, x.state])));
  const res = await imageState(page, '#resources [data-game-image="resource"]');
  check("wot měny: oficiální ikona u všech čtyř měn", res.length === 4 && res.every((x) => x.state === "image" && x.loaded === true), JSON.stringify(res.map((x) => [x.state, x.src])));
  check("wot měny: Credits / Gold / Bonds / Free XP ze správného souboru", JSON.stringify(res.map((x) => x.src).sort()) === JSON.stringify(["wot/resources/bonds.svg", "wot/resources/credits.svg", "wot/resources/free_xp.svg", "wot/resources/gold.svg"]), JSON.stringify(res.map((x) => x.src)));
  check("wot měny: ikony dekorativní (prázdný alt)", res.every((x) => x.alt === ""));
  check("wot měny: malé ikony 24 px", res.every((x) => x.w === 24 && x.h === 24), JSON.stringify(res.map((x) => [x.w, x.h])));
  const resText = await page.locator("#resources").innerText();
  check("wot měny: textové popisky a částky zůstávají", ["CREDITS", "GOLD", "BONDS", "FREE XP"].every((l) => resText.toUpperCase().includes(l)) && /8\s?450\s?000/.test(resText), resText.replace(/\s+/g, " ").slice(0, 120));
  await page.screenshot({ path: `${OUT}wot-assets.png`, fullPage: true });
  await page.locator("#resources").screenshot({ path: `${OUT}wot-resources.png` });
  check("wot obrázky: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  // skutečné grindy uživatele + tank, který v kódu nikde není → jen manifest; neznámý název → monogram
  const grind = (id, tank) => ({ id, tank, xp_remaining: 100000, priority: "high", status: "active" });
  const requests = [];
  const { ctx, page, errors } = await open("/wot", {
    setup: async (p) => {
      await withGameAssets(p, TEST_MANIFEST, requests);
      await withApiList(p, "/wot/grinds", [grind(1, "VZ.55"), grind(2, "T34/100"), grind(3, "Hirschkäfer"), grind(4, "CAV 71"), grind(5, "Leopard 1"), grind(6, "Neexistující tank")]);
    },
  });
  await page.waitForTimeout(900);
  const tanks = await imageState(page, '[data-game-image="tank"]');
  const expected = { "VZ.55": "2929", "T34/100": "1649", "Hirschkäfer": "40977", "CAV 71": "6817" };
  for (const [name, id] of Object.entries(expected)) {
    const t = byAlt(tanks, `Tank ${name}`);
    check(`wot reálný grind: ${name} → obrázek z Tankopedie`, t?.state === "image" && t.loaded === true && t.src === `wot/tanks/${id}.png`, JSON.stringify(t));
  }
  const future = byAlt(tanks, "Tank Leopard 1");
  check("wot budoucí tank: spáruje se z manifestu bez úpravy kódu", future?.state === "image" && future.loaded === true && future.src === "wot/tanks/14609.png", JSON.stringify(future));
  const unknown = byAlt(tanks, "Tank Neexistující tank");
  check("wot neznámý tank: monogram s popiskem", unknown?.state === "fallback" && unknown.text === "NT", JSON.stringify(unknown));
  check("wot obrázky: líné načítání", tanks.filter((x) => x.state === "image").every((x) => x.lazy === true));
  // grindy + historie + Mka: stahují se jen soubory tanků, které jsou na stránce vidět
  const tankFiles = [...new Set(requests.filter((r) => r.startsWith("/game-assets/wot/tanks/")))];
  const shown = new Set((await imageState(page, '[data-game-image="tank"] img')).length ? (await page.locator('[data-game-image="tank"] img').evaluateAll((els) => els.map((i) => new URL(i.src).pathname))) : []);
  const manifestLoads = requests.filter((r) => r.endsWith("manifest.json")).length;
  check("wot obrázky: prohlížeč stáhne jen zobrazené tanky (ne celou cache)", tankFiles.length > 0 && tankFiles.length <= 10 && tankFiles.every((f) => shown.has(f) || f === MISSING_TANK_FILE) && manifestLoads === 1, JSON.stringify({ tankFiles: tankFiles.length, manifestLoads }));
  await page.screenshot({ path: `${OUT}wot-assets-real-grinds.png`, fullPage: true });
  check("wot reálné grindy: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await open("/wot", { setup: (p) => withGameAssets(p, null) });
  await page.waitForTimeout(600);
  const all = await imageState(page, "[data-game-image]");
  check("wot bez assetů: všude monogram, žádný <img>", all.length >= 8 && all.every((x) => x.state === "fallback") && (await page.locator("[data-game-image] img").count()) === 0, JSON.stringify(all.map((x) => x.state)));
  await page.screenshot({ path: `${OUT}wot-assets-fallback.png`, fullPage: true });
  check("wot bez assetů: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  // skutečný záznam se jmenuje „Luna" → alias na Luna Snow
  const chars = JSON.parse(readFileSync(new URL("./fixtures/mff-characters.json", import.meta.url), "utf8")).map((c) => (c.name === "Luna Snow" ? { ...c, name: "Luna" } : c));
  const { ctx, page, errors } = await open("/mff", {
    setup: async (p) => {
      await withGameAssets(p);
      await withApiList(p, "/mff/characters", chars);
    },
  });
  await page.waitForTimeout(800);
  const portraits = await imageState(page, '[data-game-image="character"]');
  const luna = byAlt(portraits, "Portrét: Luna");
  check("mff portréty: Luna → portrét Luna Snow", luna?.state === "image" && luna.loaded === true && luna.src === "mff/characters/luna_snow.png" && luna.w === 56 && luna.h === 56, JSON.stringify(luna));
  const thor = byAlt(portraits, "Portrét: Thor");
  check("mff portréty: bez assetu → monogram s popiskem", thor?.state === "fallback" && thor.text === "TH", JSON.stringify(thor));
  check("mff portréty: na každé kartě", portraits.length === (await page.locator('[aria-label="Sledované postavy"] > li').count()));
  check("mff portréty: jméno zůstává nadpisem", (await page.getByRole("heading", { level: 3, name: "Luna" }).count()) === 1);
  await page.screenshot({ path: `${OUT}mff-assets.png`, fullPage: true });
  check("mff portréty: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
for (const path of ["/wot", "/mff"]) {
  const { ctx, page, errors } = await open(path, { width: 390, height: 844, setup: (p) => withGameAssets(p) });
  await page.waitForTimeout(700);
  check(`${path} obrázky mobil: bez přetečení`, (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  const imgs = await imageState(page, path === "/wot" ? '[data-search-target] [data-game-image="tank"]' : '[data-game-image="character"]');
  check(`${path} obrázky mobil: menší miniatury zůstávají`, imgs.length >= 3 && imgs.every((x) => x.h === 40), JSON.stringify(imgs.map((x) => [x.w, x.h])));
  const titleSel = path === "/wot" ? "[data-search-target] div.break-words.font-medium" : '[aria-label="Sledované postavy"] h3';
  const widths = await page.locator(titleSel).evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
  check(`${path} obrázky mobil: názvy mají místo (≥ 180 px)`, widths.length >= 3 && widths.every((w) => w >= 180), JSON.stringify(widths));
  if (path === "/wot") {
    const res = await imageState(page, '#resources [data-game-image="resource"]');
    check("/wot měny mobil: ikony zůstávají malé", res.length === 4 && res.every((x) => x.state === "image" && x.w === 24 && x.h === 24), JSON.stringify(res.map((x) => [x.state, x.w])));
  }
  await page.screenshot({ path: `${OUT}${path.slice(1)}-assets-mobile.png`, fullPage: true });
  check(`${path} obrázky mobil: bez chyb JS`, errors.length === 0, errors.join("; "));
  await ctx.close();
}

// 22) Game Enrichment B – splnění grindu, historie, Mka a galerie screenshotů (stavový mock, screenshoty = neutrální PNG).
const activeRow = (page, tank) => page.locator('[aria-label="Aktivní grindy"] > *').filter({ hasText: tank });
const historyIds = (page) => page.locator('[data-section="wot-completed"] [data-completion]').evaluateAll((els) => els.map((e) => e.getAttribute("data-completion")));
const milestoneIds = (page) => page.locator('[aria-label="Milníky"] > li').evaluateAll((els) => els.map((e) => e.getAttribute("data-milestone")));
const milestoneCard = (page, id) => page.locator(`[aria-label="Milníky"] > li[data-milestone="${id}"]`);
{
  await wotReset();
  const { ctx, page, errors } = await open("/wot", { setup: (p) => withGameAssets(p) });
  await page.waitForTimeout(600);
  // pořadí sekcí: zdroje → aktivní grindy → splněné → Mka
  const order = await page.evaluate(() =>
    ["#resources", '[aria-label="Aktivní grindy"]', '[data-section="wot-completed"]', '[aria-label="Milníky"]'].map((sel) => document.querySelector(sel)?.getBoundingClientRect().top ?? -1),
  );
  check("wot B: pořadí zdroje → aktivní → splněné → Mka", order.every((y, i) => y >= 0 && (i === 0 || y > order[i - 1])), JSON.stringify(order.map(Math.round)));
  check("wot B: aktivní seznam bez splněných grindů", (await activeRow(page, "Kranvagn").count()) === 1 && (await activeRow(page, "T-100 LT").count()) === 0 && (await activeRow(page, "Progetto 65").count()) === 0);
  check("wot B: průběh grindu z výchozího XP", (await activeRow(page, "Kranvagn").innerText()).includes("75 %") && (await page.getByRole("progressbar", { name: /Kranvagn: 75 %/ }).count()) === 1);
  check("wot B: grind bez výchozího XP nemá vymyšlený průběh", (await activeRow(page, "TVP T 50/51").getByRole("progressbar").count()) === 0);
  check("wot B: historie – Progetto 65 + starší T-100 LT", JSON.stringify(await historyIds(page)) === JSON.stringify(["completion:1", "grind:3"]));
  const histText = await page.locator('[data-section="wot-completed"]').innerText();
  check("wot B: historie – datum, doba a XP", /58 dn/.test(histText) && /165\s?000/.test(histText) && /datum neznámé/.test(histText), histText.replace(/\s+/g, " ").slice(0, 160));

  // Regrese B (lokální ověření): nový grind nejde založit jako „Dokončeno"; Splněno je obrys, ne plná zelená
  await page.getByRole("button", { name: "Přidat grind" }).click();
  const statusOptions = await page.getByLabel("Stav").locator("option").evaluateAll((els) => els.map((o) => o.value));
  check("wot B: nový grind nenabízí stav Dokončeno", JSON.stringify(statusOptions) === JSON.stringify(["active", "paused"]), JSON.stringify(statusOptions));
  await page.getByRole("button", { name: "Zrušit" }).first().click();
  const fills = await page.evaluate(() => {
    const bg = (el) => (el ? getComputedStyle(el).backgroundColor : "");
    const done = document.querySelector('[aria-label^="Splněno: "]');
    const add = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Přidat grind");
    return { done: bg(done), add: bg(add) };
  });
  const alpha = (c) => (/rgba?\(([^)]+)\)/.exec(c)?.[1].split(",")[3] ?? "1").trim();
  check("wot B: Splněno tišší než Přidat grind (bez plné výplně)", Number(alpha(fills.done)) < 0.2 && Number(alpha(fills.add)) > 0.9, JSON.stringify(fills));
  const headerText = () => page.locator("p, div").filter({ hasText: /^\d+ aktivn\S* · zbývá / }).last().innerText();
  const parseHeader = (t) => { const m = /^(\d+) aktivn\S* · zbývá ([\d\s ]+) XP/.exec(t.trim()); return m ? { n: Number(m[1]), xp: Number(m[2].replace(/\D/g, "")) } : null; };
  const headerBefore = parseHeader(await headerText());
  const kranvagnXp = Number(((await activeRow(page, "Kranvagn").innerText()).match(/Zbývá ([\d\s ]+) XP/)?.[1] ?? "").replace(/\D/g, ""));

  // Splněno → potvrzení → GRIND COMPLETE → historie
  await activeRow(page, "Kranvagn").getByRole("button", { name: "Splněno: Kranvagn" }).click();
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Označit Kranvagn jako splněný?" });
  check("wot B: Splněno chce lehké potvrzení", (await confirm.count()) === 1);
  check("wot B: XP samo nic nesplní (bez potvrzení beze změny)", JSON.stringify(await historyIds(page)) === JSON.stringify(["completion:1", "grind:3"]));
  await confirm.getByRole("button", { name: "Splněno", exact: true }).click();
  const badge = page.getByTestId("grind-complete");
  await badge.waitFor({ timeout: 3000 }).catch(() => undefined);
  const celebrating = activeRow(page, "Kranvagn");
  const anim = await celebrating.evaluate((el) => {
    const state = el.querySelector('[data-complete="true"].motion-completion');
    return state ? getComputedStyle(state, "::after").animationName : "none";
  }).catch(() => "none");
  check("wot B: GRIND COMPLETE se zobrazí na řádku", (await badge.count()) === 1 && /grind complete/i.test(await badge.innerText()), String(await badge.count()));
  check("wot B: oslava používá sdílený CompletionState", anim === "motion-glow-once", anim);
  check("wot B: při oslavě 100 % a bez akcí", (await celebrating.innerText()).includes("100 %") && (await celebrating.getByRole("button").count()) === 0);
  check("wot B: oznámení pro čtečky (role=status)", (await page.getByTestId("grind-complete-notice").getAttribute("role")) === "status");
  const headerDuring = parseHeader(await headerText());
  check("wot B: hlavička během oslavy už bez splněného grindu", Boolean(headerBefore && headerDuring && headerDuring.n === headerBefore.n - 1 && headerDuring.xp === headerBefore.xp - kranvagnXp), JSON.stringify({ headerBefore, headerDuring, kranvagnXp }));
  await page.screenshot({ path: `${OUT}wot-grind-complete.png` });
  // navigace není blokovaná: odkaz v menu je dál klikatelný (jen ověříme, že nic nepřekrývá stránku)
  check("wot B: oslava nic nepřekrývá", (await page.locator('[role="dialog"], [role="alertdialog"]').count()) === 0);
  await page.waitForTimeout(1700);
  check("wot B: po oslavě grind opustí aktivní seznam", (await activeRow(page, "Kranvagn").count()) === 0 && (await badge.count()) === 0);
  check("wot B: hlavička po obnovení sedí se stavem během oslavy", JSON.stringify(parseHeader(await headerText())) === JSON.stringify(headerDuring), await headerText());
  const hist = await historyIds(page);
  check("wot B: splnění je nahoře v historii (stabilní id)", hist.length === 3 && /^completion:\d+$/.test(hist[0]) && hist[0] !== "completion:1", hist.join(","));
  check("wot B: nové splnění zvýrazněné v historii", (await page.locator(`[data-completion="${hist[0]}"]`).innerText()).includes("Kranvagn"));

  // Mka: oblíbené první, pak podle data; značka Legendární; bez screenshotů žádná galerie
  check("wot B: Mka – oblíbené první, pak nejnovější", JSON.stringify(await milestoneIds(page)) === JSON.stringify(["2", "1", "3", "4"]), (await milestoneIds(page)).join(","));
  check("wot B: oblíbené = viditelná značka", (await milestoneCard(page, "2").getByTestId("favorite-marker").count()) === 1 && (await page.getByTestId("favorite-marker").count()) === 1);
  const p65 = await milestoneCard(page, "1").innerText();
  check("wot B: Progetto 65 – statistiky Mka", /5\s?205/.test(p65) && /1\s?754/.test(p65) && /1\s?208/.test(p65) && /Útesy/.test(p65) && /Mistr/.test(p65), p65.replace(/\s+/g, " ").slice(0, 200));
  check("wot B: milník bez screenshotů = bez galerie", (await milestoneCard(page, "3").locator("[data-shot]").count()) === 0);
  const thumbs = milestoneCard(page, "1").locator("[data-shot]");
  check("wot B: galerie – 3 náhledy", (await thumbs.count()) === 3);
  await page.waitForTimeout(400);
  const thumbImgs = await thumbs.locator("img").evaluateAll((els) => els.map((i) => ({ ok: i.complete && i.naturalWidth > 0, lazy: i.loading === "lazy", fit: getComputedStyle(i).objectFit })));
  check("wot B: náhledy se načtou líně, ořez 16:9", thumbImgs.length === 3 && thumbImgs.every((x) => x.ok && x.lazy && x.fit === "cover"), JSON.stringify(thumbImgs));
  const ratio = await thumbs.first().evaluate((el) => el.getBoundingClientRect().width / el.getBoundingClientRect().height);
  check("wot B: náhled má poměr 16:9", Math.abs(ratio - 16 / 9) < 0.05, ratio.toFixed(3));
  await page.waitForTimeout(300);
  check("wot B: chybějící soubor → náhradní stav, ne rozbitý obrázek", (await milestoneCard(page, "4").locator('[data-shot-state="missing"]').count()) === 1 && (await milestoneCard(page, "4").locator("img").count()) === 1);

  // zvětšení: dialog, fokus na Zavřít, šipky, Esc vrátí fokus
  await thumbs.first().click();
  const box = page.getByTestId("shot-lightbox");
  await box.waitFor({ timeout: 2000 }).catch(() => undefined);
  check("wot B: klik na náhled otevře zvětšení", (await box.count()) === 1 && (await box.getAttribute("role")) === "dialog");
  check("wot B: zvětšení – fokus na Zavřít", (await focusedLabel(page)) === "Zavřít náhled", await focusedLabel(page));
  const big = await box.locator("img").evaluate((i) => ({ fit: getComputedStyle(i).objectFit, ok: i.complete && i.naturalWidth > 0 })).catch(() => null);
  check("wot B: zvětšení zachová poměr stran (object-contain)", big?.fit === "contain", JSON.stringify(big));
  check("wot B: zvětšení – popisek a pozice", /Výsledková tabulka/.test(await box.innerText()) && /1 \/ 3/.test(await box.innerText()));
  await page.keyboard.press("ArrowRight");
  check("wot B: šipka → další screenshot", /2 \/ 3/.test(await box.innerText()) && /Mistr!/.test(await box.innerText()));
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  check("wot B: šipka ← dokola na poslední", /3 \/ 3/.test(await box.innerText()));
  await page.waitForTimeout(350);
  await page.screenshot({ path: `${OUT}wot-lightbox.png` });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250);
  check("wot B: Esc zavře a vrátí fokus na náhled", (await box.count()) === 0 && /^Zvětšit: Screenshot 1 z 3/.test(await focusedLabel(page)), await focusedLabel(page));

  // oblíbení: přepínač s aria-pressed, změní pořadí
  const fav = milestoneCard(page, "3").getByRole("button", { name: "Označit jako legendární: Object 140" });
  check("wot B: oblíbení = přepínač (aria-pressed)", (await fav.getAttribute("aria-pressed")) === "false");
  await fav.click();
  await page.waitForTimeout(500);
  check("wot B: oblíbení přepne značku a pořadí", (await milestoneCard(page, "3").getByTestId("favorite-marker").count()) === 1 && (await milestoneIds(page)).slice(0, 2).sort().join(",") === "2,3", (await milestoneIds(page)).join(","));
  await milestoneCard(page, "3").getByRole("button", { name: "Zrušit legendární: Object 140", pressed: true }).click();
  await page.waitForTimeout(500);

  // nový milník: jen tank je povinný, obrázek tanku se doplní sám, screenshot nahraný po uložení
  await page.getByRole("button", { name: "Přidat Mko" }).click();
  const form = page.getByTestId("milestone-form");
  await form.waitFor({ timeout: 2000 }).catch(() => undefined);
  check("wot B: formulář milníku v panelu", (await form.count()) === 1 && (await page.getByRole("dialog", { name: "Nové Mko / milník" }).count()) === 1);
  await form.getByRole("button", { name: "Uložit milník" }).click();
  check("wot B: prázdný tank = chyba u pole", (await form.getByText(/tank/i).filter({ hasText: /Vyplň|Zadej|povinn/i }).count()) >= 1);
  await form.getByLabel("Tank *").fill("Kranvagn");
  await page.waitForTimeout(400);
  const preview = await imageState(page, '[data-testid="milestone-form"] [data-game-image="tank"]');
  check("wot B: tank ve formuláři hned s obrázkem (Game Enrichment A)", preview[0]?.state === "image" && preview[0]?.src === "wot/tanks/2433.png", JSON.stringify(preview));
  await form.getByLabel("Mapa").fill("Prochorovka");
  await form.getByLabel("Poškození").fill("6100");
  await form.getByLabel("Zničení").fill("4");
  const fileInput = form.locator('input[type="file"]');
  await fileInput.setInputFiles({ name: "poznamky.txt", mimeType: "text/plain", buffer: Buffer.from("ne") });
  check("wot B: nepodporovaný soubor odmítnut v prohlížeči", (await form.getByRole("alert").filter({ hasText: /PNG|JPEG|WebP/ }).count()) === 1);
  await fileInput.setInputFiles({ name: "kranvagn-mko.png", mimeType: "image/png", buffer: stubPng(320, 180, [60, 80, 90]) });
  check("wot B: obrázek čeká na nahrání s popiskem", (await form.getByLabel("Popisek: kranvagn-mko.png").count()) === 1);
  await form.getByLabel("Popisek: kranvagn-mko.png").fill("Konec bitvy");
  await form.getByRole("button", { name: "Uložit milník" }).click();
  await form.waitFor({ state: "detached", timeout: 4000 }).catch(() => undefined);
  await page.waitForTimeout(500);
  const ids = await milestoneIds(page);
  const created = ids.find((id) => !["1", "2", "3", "4"].includes(id));
  check("wot B: nový milník v seznamu", ids.length === 5 && Boolean(created), ids.join(","));
  const newCard = milestoneCard(page, created);
  check("wot B: nový milník – screenshot nahraný", (await newCard.locator("[data-shot]").count()) === 1 && /Prochorovka/.test(await newCard.innerText()));
  await page.screenshot({ path: `${OUT}wot-milestones.png`, fullPage: true });

  // smazání: výslovné potvrzení
  await newCard.getByRole("button", { name: /Smazat/ }).click();
  const del = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Smazat milník" });
  check("wot B: smazání milníku chce potvrzení", (await del.count()) === 1 && /screenshoty/.test(await del.innerText()));
  await del.getByRole("button", { name: "Smazat milník" }).click();
  await page.waitForTimeout(600);
  check("wot B: milník smazán", (await milestoneIds(page)).length === 4);
  check("wot B: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  // omezený pohyb: žádná animace, grind rovnou v historii
  await wotReset();
  const { ctx, page, errors } = await open("/wot", { reducedMotion: "reduce", setup: (p) => withGameAssets(p) });
  await activeRow(page, "Object 279 (e)").getByRole("button", { name: /^Splněno/ }).click();
  await page.getByRole("button", { name: "Splněno", exact: true }).click();
  await page.waitForTimeout(700);
  check("wot B omezený pohyb: bez oslavné animace", (await page.getByTestId("grind-complete").count()) === 0);
  check("wot B omezený pohyb: grind hned v historii", (await activeRow(page, "Object 279 (e)").count()) === 0 && (await historyIds(page)).length === 3);
  check("wot B omezený pohyb: textové oznámení zůstává", (await page.getByTestId("grind-complete-notice").count()) === 1);
  const animations = await page.evaluate(() => [...document.querySelectorAll(".motion-completion, .motion-completion-label")].map((e) => getComputedStyle(e).animationName));
  check("wot B omezený pohyb: CSS animace vypnutá", animations.every((a) => a === "none"), animations.join(","));
  check("wot B omezený pohyb: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
for (const [width, label] of [[1366, "laptop"], [390, "mobile"]]) {
  await wotReset();
  const { ctx, page, errors } = await open("/wot", { width, height: width < 500 ? 844 : 900, setup: (p) => withGameAssets(p) });
  await page.waitForTimeout(600);
  check(`wot B @${label}: bez přetečení`, (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  const cards = await page.locator('[aria-label="Milníky"] > li').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
  check(`wot B @${label}: karty Mk se vejdou`, cards.length === 4 && cards.every((w) => w <= width - 24), JSON.stringify(cards));
  if (width < 500) {
    const t = milestoneCard(page, "1").locator("[data-shot]").first();
    const tb = await t.boundingBox();
    check("wot B mobil: náhled je dotykový cíl ≥ 44 px", Boolean(tb && tb.height >= 44), String(tb?.height));
    await t.tap();
    const box = page.getByTestId("shot-lightbox");
    await box.waitFor({ timeout: 2000 }).catch(() => undefined);
    const img = await box.locator("img").boundingBox();
    check("wot B mobil: zvětšení na šířku displeje", Boolean(img && img.width >= 340 && img.width <= 390), JSON.stringify(img));
    await page.waitForTimeout(350); // po náběhu dialogu
    await page.screenshot({ path: `${OUT}wot-lightbox-mobile.png` });
    await box.getByRole("button", { name: "Zavřít náhled" }).tap();
    await page.getByRole("button", { name: "Přidat Mko" }).tap();
    await page.waitForTimeout(400);
    check("wot B mobil: formulář milníku bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
    await page.screenshot({ path: `${OUT}wot-milestone-form-mobile.png` });
  }
  await page.screenshot({ path: `${OUT}wot-b-${label}.png`, fullPage: true });
  check(`wot B @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
  await ctx.close();
}
await wotReset();

// 23) Game Enrichment C – knihovna replayů (stavový mock, fixtures ze skutečného wot_replay_service; syntetické replaye).
const REPLAY_FILE = readFileSync(new URL("./fixtures/replay-upload.wotreplay", import.meta.url));
const replayIds = (page) => page.locator('[aria-label="Replaye"] > li').evaluateAll((els) => els.map((e) => e.getAttribute("data-search-target")));
const replayRow = (page, id) => page.locator(`[aria-label="Replaye"] > li[data-search-target="replay-${id}"]`);
const pickFilter = (page, label, value) => page.getByRole("search", { name: "Filtry replayů" }).getByLabel(label, { exact: true }).selectOption(value);
const settle = (page, ms = 500) => page.waitForTimeout(ms);
{
  await wotReset();
  const { ctx, page, errors } = await open("/wot", { setup: (p) => withGameAssets(p) });
  await page.locator('[data-section="wot-replays"]').getByRole("link", { name: "Otevřít knihovnu" }).click();
  await page.waitForURL("**/wot/replays", { timeout: 5000 }).catch(() => undefined);
  await settle(page, 800);
  check("replaye: /wot → knihovna", page.url().endsWith("/wot/replays") && (await page.getByRole("heading", { level: 1 }).innerText()) === "Knihovna replayů", page.url());
  check("replaye: nejnovější bitva první, bez data na konci", JSON.stringify(await replayIds(page)) === JSON.stringify(["replay-3", "replay-2", "replay-1", "replay-4", "replay-5"]), (await replayIds(page)).join(","));
  const tanks = await imageState(page, '[aria-label="Replaye"] [data-game-image="tank"]');
  check("replaye: tag z replaye → název a obrázek z manifestu (Leopard 1)", byAlt(tanks, "Tank Leopard 1")?.state === "image" && (await replayRow(page, 3).innerText()).includes("Leopard 1"), JSON.stringify(tanks.map((x) => [x.alt, x.state])));
  check("replaye: tank mimo manifest → monogram", byAlt(tanks, "Tank Progetto 65")?.state === "fallback" && byAlt(tanks, "Tank 20260930_novy_format.wotreplay")?.state === "fallback");
  check("replaye: stav parseru u částečného a nenačteného", (await replayRow(page, 4).locator('[data-parser-status="partial"]').count()) === 1 && (await replayRow(page, 5).locator('[data-parser-status="unsupported"]').innerText()).includes("Metadata nenačtena") && (await replayRow(page, 1).locator("[data-parser-status]").count()) === 0);
  check("replaye: oblíbený = značka ★ Oblíbený", (await replayRow(page, 1).getByTestId("replay-favorite").count()) === 1 && (await page.getByTestId("replay-favorite").count()) === 1);
  check("replaye: propojené Mko vidět v seznamu", (await replayRow(page, 1).getByTestId("replay-milestone-link").innerText()).includes("Progetto 65") && (await page.getByTestId("replay-milestone-link").count()) === 2);
  check("replaye: štítky jako čipy", JSON.stringify(await replayRow(page, 1).locator("[data-tag]").allInnerTexts()) === JSON.stringify(["Mko", "Carry", "Těsná bitva"]));

  // filtry
  await pickFilter(page, "Štítek", "mko");
  await settle(page);
  check("replaye filtr: štítek Mko", JSON.stringify(await replayIds(page)) === JSON.stringify(["replay-2", "replay-1"]));
  await page.getByRole("group", { name: "Oblíbené" }).getByRole("button", { name: "★ Jen oblíbené" }).click();
  await settle(page);
  check("replaye filtr: + jen oblíbené", JSON.stringify(await replayIds(page)) === JSON.stringify(["replay-1"]));
  check("replaye filtr: počet aktivních filtrů", (await page.getByRole("button", { name: "Zrušit filtry (2)" }).count()) === 1);
  await page.getByRole("button", { name: "Zrušit filtry (2)" }).click();
  await page.getByRole("searchbox", { name: "Hledat v replayích" }).fill("utesy");
  await settle(page, 700);
  check("replaye hledání: mapa bez diakritiky", JSON.stringify(await replayIds(page)) === JSON.stringify(["replay-1"]));
  await page.getByRole("searchbox", { name: "Hledat v replayích" }).fill("xyz-nic");
  await settle(page, 700);
  check("replaye hledání: nic nenalezeno = vlastní prázdný stav", (await page.getByTestId("replay-no-match").count()) === 1);
  await page.getByRole("searchbox", { name: "Hledat v replayích" }).fill("");
  const tankOptions = await page.getByRole("search", { name: "Filtry replayů" }).getByLabel("Tank", { exact: true }).locator("option").allInnerTexts();
  check("replaye filtr: tank – názvy z manifestu místo tagů", tankOptions.includes("Leopard 1") && tankOptions.includes("Kranvagn") && !tankOptions.some((t) => t.includes(":")), tankOptions.join("|"));
  await pickFilter(page, "Tank", "germany:G89_Leopard1");
  await settle(page, 700);
  check("replaye filtr: tank", JSON.stringify(await replayIds(page)) === JSON.stringify(["replay-3"]));
  await pickFilter(page, "Tank", "");
  await pickFilter(page, "Odznak", "none");
  await settle(page);
  check("replaye filtr: bez odznaku", JSON.stringify(await replayIds(page)) === JSON.stringify(["replay-3", "replay-4", "replay-5"]));
  await pickFilter(page, "Odznak", "");
  await pickFilter(page, "Řazení", "played_asc");
  await settle(page);
  check("replaye řazení: nejstarší bitva první", (await replayIds(page))[0] === "replay-4");
  await pickFilter(page, "Řazení", "played_desc");
  await settle(page);

  // detail (URL ?replay=ID)
  await replayRow(page, 1).getByRole("button", { name: "Detail replaye: Progetto 65" }).click();
  const detail = page.getByTestId("replay-detail");
  await detail.waitFor({ timeout: 3000 }).catch(() => undefined);
  const dText = await detail.innerText().catch(() => "");
  check("replaye detail: otevře se a má odkaz v URL", page.url().endsWith("/wot/replays?replay=1") && (await detail.count()) === 1);
  check("replaye detail: statistiky, mapa, datum, štítky, poznámka", /5\s?205/.test(dText) && /1\s?754/.test(dText) && /1\s?208/.test(dText) && /Útesy · 14\. 9\. 2026/.test(dText) && dText.includes("Těsná bitva") && dText.includes("1 vs 3"), dText.replace(/\s+/g, " ").slice(0, 200));
  check("replaye detail: soubor, velikost, stav parseru", dText.includes("20260914_2015_italy-It13_Progetto_M35_mod_46_18_cliff.wotreplay") && /kB/.test(dText) && (await detail.locator('[data-parser-status="parsed"]').innerText()).includes("Načteno z replaye"));
  check("replaye detail: Mko + jeho screenshoty (galerie B)", (await detail.getByTestId("replay-detail-milestone").innerText()).includes("Progetto 65") && (await detail.locator("[data-shot]").count()) === 3);
  const dl = detail.getByTestId("replay-download");
  check("replaye detail: stažení originálu", (await dl.getAttribute("href"))?.endsWith("/wot/replays/1/file") && (await dl.getAttribute("download")) !== null);
  await page.screenshot({ path: `${OUT}wot-replay-detail.png` });
  await page.keyboard.press("Escape");
  await settle(page, 400);
  check("replaye detail: Esc zavře a vyčistí URL", page.url().endsWith("/wot/replays") && (await detail.count()) === 0, page.url());

  // oblíbení
  await replayRow(page, 3).getByRole("button", { name: "Oblíbit replay: Leopard 1" }).click();
  await settle(page, 600);
  check("replaye: oblíbení přepne značku (aria-pressed)", (await replayRow(page, 3).getByTestId("replay-favorite").count()) === 1 && (await replayRow(page, 3).getByRole("button", { name: "Zrušit oblíbení: Leopard 1" }).getAttribute("aria-pressed")) === "true");

  // upload: neplatný soubor, pak replay → kontrola údajů → uložení
  const input = page.getByTestId("replay-file-input");
  await input.setInputFiles({ name: "bitva.zip", mimeType: "application/zip", buffer: Buffer.from("PK") });
  check("replaye upload: jiná přípona odmítnuta v prohlížeči", (await page.getByTestId("replay-notice").innerText()).includes(".wotreplay") && (await page.getByTestId("replay-notice").getAttribute("role")) === "alert");
  const uploadUrls = [];
  page.on("request", (rq) => { const u = new URL(rq.url()); if (u.port === "8000" && u.pathname === "/wot/replays" && rq.method() === "POST") uploadUrls.push(u.search); });
  await input.setInputFiles({ name: "20261005_2105_usa-A67_T57_58_08_ruinberg.wotreplay", mimeType: "application/octet-stream", buffer: REPLAY_FILE });
  const form = page.getByTestId("replay-form");
  await form.waitFor({ timeout: 4000 }).catch(() => undefined);
  check("replaye upload: hned kontrola údajů v panelu", (await page.getByRole("dialog", { name: "Zkontroluj údaje replaye" }).count()) === 1 && (await form.locator('[data-parser-status="parsed"]').innerText()).includes("Načteno z replaye"));
  await settle(page, 300);
  // Regrese z lokálního ověření: replay znal jen technický tag → hledání „T57 Heavy" a Aktivita s tagem
  check("replaye upload: lidský název z manifestu poslaný se souborem", uploadUrls.length === 1 && new URLSearchParams(uploadUrls[0]).get("tank_name") === "T57 Heavy", JSON.stringify(uploadUrls));
  check("replaye upload: tank předvyplněný z manifestu, statistiky z replaye", (await form.getByLabel("Tank").inputValue()) === "T57 Heavy" && (await form.getByLabel("Poškození").inputValue()) === "7410" && (await form.getByLabel("Odznak zvládnutí").inputValue()) === "ace" && (await form.getByLabel("Výsledek").inputValue()) === "win");
  const formTank = await imageState(page, '[data-testid="replay-form"] [data-game-image="tank"]');
  check("replaye upload: obrázek tanku ve formuláři (Game Enrichment A)", formTank[0]?.state === "image" && formTank[0]?.src === "wot/tanks/14881.png", JSON.stringify(formTank));
  await form.getByRole("group", { name: "Předvolené štítky" }).getByRole("button", { name: "Rekord" }).click();
  await form.getByLabel("Vlastní štítek").fill("<b>");
  await form.getByRole("button", { name: "Přidat", exact: true }).click();
  check("replaye upload: neplatný vlastní štítek", (await form.getByRole("alert").innerText()).includes("1–24 znaků"));
  await form.getByLabel("Vlastní štítek").fill("Ruinberg  Rush");
  await form.getByLabel("Vlastní štítek").press("Enter");
  check("replaye upload: vlastní štítek normalizovaný", (await form.getByRole("list", { name: "Vlastní štítky" }).innerText()).includes("ruinberg rush"));
  await form.getByLabel("Propojit s Mkem / milníkem").selectOption("3");
  await form.getByLabel("Poznámka").fill("Rush přes střed.");
  await page.screenshot({ path: `${OUT}wot-replay-review.png` });
  await form.getByRole("button", { name: "Uložit údaje" }).click();
  await form.waitFor({ state: "detached", timeout: 4000 }).catch(() => undefined);
  await settle(page, 600);
  const ids = await replayIds(page);
  const created = ids.find((x) => !["replay-1", "replay-2", "replay-3", "replay-4", "replay-5"].includes(x));
  const newRow = page.locator(`[aria-label="Replaye"] > li[data-search-target="${created}"]`);
  check("replaye upload: nový replay v knihovně (nejnovější bitva nahoře)", ids.length === 6 && ids[0] === created, ids.join(","));
  check("replaye upload: uložené štítky a propojené Mko", JSON.stringify(await newRow.locator("[data-tag]").allInnerTexts()) === JSON.stringify(["Rekord", "ruinberg rush"]) && (await newRow.getByTestId("replay-milestone-link").innerText()).includes("Object 140"));

  // duplicita: stejný obsah (jiný název) → nic nového, odkaz na existující
  await input.setInputFiles({ name: "kopie.wotreplay", mimeType: "application/octet-stream", buffer: REPLAY_FILE });
  await page.getByTestId("replay-notice").waitFor({ timeout: 4000 }).catch(() => undefined);
  check("replaye duplicita: oznámení, žádná druhá kopie", (await page.getByTestId("replay-notice").innerText()).includes("už v knihovně") && (await replayIds(page)).length === 6);
  await page.getByRole("button", { name: "Otevřít existující" }).click();
  await detail.waitFor({ timeout: 3000 }).catch(() => undefined);
  check("replaye duplicita: Otevřít existující → detail", page.url().endsWith(`?replay=${created.split("-")[1]}`) && (await detail.innerText()).includes("T57 Heavy"));

  // smazání s potvrzením
  await detail.getByRole("button", { name: /^Smazat replay/ }).click();
  const confirmDel = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Smazat replay?" });
  check("replaye smazání: výslovné potvrzení", (await confirmDel.count()) === 1 && (await confirmDel.innerText()).includes("Propojené Mko zůstane"));
  await confirmDel.getByRole("button", { name: "Smazat replay" }).click();
  await settle(page, 700);
  check("replaye smazání: replay zmizí, detail zavřený", (await replayIds(page)).length === 5 && !page.url().includes("replay=") && (await detail.count()) === 0);

  // ruční doplnění částečného replaye
  await replayRow(page, 4).getByRole("button", { name: "Detail replaye: Kranvagn" }).click();
  await detail.waitFor({ timeout: 3000 }).catch(() => undefined);
  check("replaye částečný: detail vysvětlí, co chybí", (await detail.innerText()).includes("doplň je ručně") && (await detail.innerText()).includes("Statistiky zatím nejsou vyplněné"));
  await detail.getByRole("button", { name: "Upravit údaje" }).click();
  await form.waitFor({ timeout: 3000 }).catch(() => undefined);
  check("replaye ruční úprava: tank z manifestu, stav Načteno částečně", (await form.getByLabel("Tank").inputValue()) === "Kranvagn" && (await form.locator('[data-parser-status="partial"]').count()) === 1);
  await form.getByLabel("Zničení").fill("30");
  await form.getByRole("button", { name: "Uložit údaje" }).click();
  check("replaye ruční úprava: validace mezí", (await form.getByText("Zničení: celé číslo 0–15.").count()) === 1);
  await form.getByLabel("Zničení").fill("3");
  await form.getByLabel("Poškození").fill("6120");
  await form.getByLabel("Odznak zvládnutí").selectOption("ace");
  await form.getByRole("button", { name: "Uložit údaje" }).click();
  await form.waitFor({ state: "detached", timeout: 4000 }).catch(() => undefined);
  await settle(page, 600);
  const kr = await detail.innerText().catch(() => "");
  check("replaye ruční úprava: uloženo, detail zpět s novými údaji", /6\s?120/.test(kr) && kr.includes("Mistr (Mko)"), kr.replace(/\s+/g, " ").slice(0, 160));
  await page.keyboard.press("Escape");
  await settle(page, 300);
  const krRow = await replayRow(page, 4).innerText();
  check("replaye ruční úprava: řádek v seznamu", /6\s?120 dmg/.test(krRow) && krRow.includes("Mistr (Mko)"), krRow.replace(/\s+/g, " ").slice(0, 160));
  check("replaye: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  // Mko → replay (odkaz na kartě milníku) a globální vyhledávání → detail replaye
  await wotReset();
  const { ctx, page, errors } = await open("/wot", { setup: (p) => withGameAssets(p) });
  const link = page.locator('[aria-label="Milníky"] > li[data-milestone="1"]').getByTestId("milestone-replay-link");
  check("replaye: karta Mka ukazuje propojený replay", (await link.count()) === 1 && (await page.getByTestId("milestone-replay-link").count()) === 2);
  await link.getByRole("link").click();
  await page.waitForURL("**/wot/replays?replay=1", { timeout: 5000 }).catch(() => undefined);
  await page.getByTestId("replay-detail").waitFor({ timeout: 4000 }).catch(() => undefined);
  check("replaye: Mko → detail replaye", page.url().endsWith("/wot/replays?replay=1") && (await page.getByTestId("replay-detail").count()) === 1);
  await page.keyboard.press("Escape");
  await settle(page, 300);
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Hledat v Standa Hubu" });
  await palette.getByRole("combobox", { name: "Hledat stránku nebo záznam" }).fill("progetto");
  await settle(page, 800);
  const opt = palette.getByRole("option", { name: /Progetto 65/ }).first();
  check("hledání: replay ve výsledcích", (await opt.count()) === 1 && (await opt.innerText()).includes("Replay"));
  await opt.click();
  await page.waitForURL("**/wot/replays?replay=1", { timeout: 5000 }).catch(() => undefined);
  await page.getByTestId("replay-detail").waitFor({ timeout: 4000 }).catch(() => undefined);
  check("hledání: replay → detail v knihovně", (await page.getByTestId("replay-detail").count()) === 1);
  check("replaye odkazy: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
{
  // prázdná knihovna
  await fetch(`${MOCK}/__mock/wot/replays-empty`, { method: "POST" });
  const { ctx, page, errors } = await open("/wot/replays", { setup: (p) => withGameAssets(p) });
  check("replaye prázdné: záměrný prázdný stav s nahráním", (await page.getByTestId("replay-empty").count()) === 1 && (await page.getByRole("button", { name: "Nahrát replay" }).count()) === 2 && (await page.getByRole("search").count()) === 0);
  await page.screenshot({ path: `${OUT}wot-replays-empty.png` });
  check("replaye prázdné: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
  await wotReset();
}
// Lokální ověření: bez jediného Mka nešel replay propojit a formulář neřekl proč → nápověda + „Vytvořit Mko z tohoto replaye"
{
  await wotReset();
  await fetch(`${MOCK}/__mock/wot/milestones-empty`, { method: "POST" });
  const { ctx, page, errors } = await open("/wot/replays?replay=1", { setup: (p) => withGameAssets(p) });
  await page.getByTestId("replay-detail").waitFor({ timeout: 4000 }).catch(() => undefined);
  await page.getByTestId("replay-detail").getByRole("button", { name: "Upravit údaje" }).click();
  const form = page.getByTestId("replay-form");
  await form.waitFor({ timeout: 3000 }).catch(() => undefined);
  const box = form.getByTestId("replay-create-milestone");
  check("replay → Mko: prázdný seznam Mk vysvětlený", (await box.innerText()).includes("Zatím nemáš žádné Mko"), await box.innerText().catch(() => ""));
  await box.getByRole("button", { name: "Vytvořit Mko z tohoto replaye" }).click();
  const done = form.getByTestId("replay-milestone-created");
  await done.waitFor({ timeout: 4000 }).catch(() => undefined);
  check("replay → Mko: vytvořené z replaye a propojené", (await done.count()) === 1 && (await done.getAttribute("role")) === "status" && (await done.innerText()).includes("je vytvořené a propojené"), await done.innerText().catch(() => ""));
  const selected = await form.getByLabel("Propojit s Mkem / milníkem").evaluate((sel) => sel.options[sel.selectedIndex]?.text ?? "");
  check("replay → Mko: nové Mko vybrané ve formuláři", selected.includes("Progetto 65"), selected);
  await page.keyboard.press("Escape");
  await settle(page, 500);
  const detailLink = await page.getByTestId("replay-detail").innerText().catch(() => "");
  check("replay → Mko: detail ukazuje propojení", detailLink.includes("Progetto 65") && !detailLink.includes("Bez propojení"), detailLink.replace(/\s+/g, " ").slice(0, 200));
  check("replay → Mko: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
  await wotReset();
}
for (const [width, label] of [[1366, "laptop"], [390, "mobile"]]) {
  await wotReset();
  const { ctx, page, errors } = await open("/wot/replays", { width, height: width < 500 ? 844 : 900, setup: (p) => withGameAssets(p) });
  await settle(page, 600);
  check(`replaye @${label}: bez přetečení`, (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  // celostránkový screenshot až na konci: v Chromiu po něm emulace přestane hlásit pointer: coarse
  if (width < 500) {
    // Regrese z lokálního ověření: hledání a filtry měly 40 px, hvězdička 36 px na šířku
    const targets = await page.evaluate(() => {
      const box = (el) => { const b = el.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; };
      const back = [...document.querySelectorAll("main a")].find((a) => a.textContent.includes("World of Tanks") && a.getAttribute("href") === "/wot");
      const bb = back.getBoundingClientRect();
      const hit = (dy) => { const el = document.elementFromPoint(bb.left + bb.width / 2, bb.top + bb.height / 2 + dy); return Boolean(el && back.contains(el)); };
      return {
        search: box(document.querySelector('main input[type="search"]')),
        selects: [...document.querySelectorAll("main select")].map(box),
        stars: [...document.querySelectorAll('main button[aria-label^="Oblíbit replay"], main button[aria-label^="Zrušit oblíbení"]')].map(box),
        backHit44: hit(-21) && hit(21),
      };
    });
    check("replaye mobil: hledání a filtry ≥ 44 px", targets.search[1] >= 44 && targets.selects.length >= 6 && targets.selects.every(([, h]) => h >= 44), JSON.stringify(targets));
    check("replaye mobil: hvězdička ≥ 44 × 44 px", targets.stars.length > 0 && targets.stars.every(([w, h]) => w >= 44 && h >= 44), JSON.stringify(targets.stars));
    check("replaye mobil: odkaz zpět má dotykovou plochu ≥ 44 px", targets.backHit44);
    await replayRow(page, 1).getByRole("button", { name: "Detail replaye: Progetto 65" }).tap();
    const d = page.getByTestId("replay-detail");
    await d.waitFor({ timeout: 3000 }).catch(() => undefined);
    await settle(page, 900); // po vjezdu panelu
    const dl = await d.getByTestId("replay-download").boundingBox();
    check("replaye mobil: detail přes celou šířku, stažení ≥ 40 px", Boolean(dl && dl.height >= 40) && (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0, JSON.stringify(dl));
    await page.screenshot({ path: `${OUT}wot-replay-detail-mobile.png` });
    await d.getByRole("button", { name: "Upravit údaje" }).tap();
    await page.getByTestId("replay-form").waitFor({ timeout: 3000 }).catch(() => undefined);
    await settle(page, 400);
    check("replaye mobil: formulář bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
    await page.screenshot({ path: `${OUT}wot-replay-form-mobile.png` });
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await settle(page, 400);
  }
  await page.screenshot({ path: `${OUT}wot-replays-${label}.png`, fullPage: true });
  check(`replaye @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
  await ctx.close();
}
await wotReset();

// 30) MRK-16 – Jarvis companion: volné kotvy (nezakrývá obsah), scroll, stavy, chůze, klik, bubliny,
//     reduced motion, vypnutí, mobil, záloha obrázku, jediný Jarvis na /ai.
{
  const companion = (page) => page.getByTestId("jarvis-companion");
  const cState = (page) => companion(page).getAttribute("data-companion-state");
  const cAnchor = (page) => companion(page).getAttribute("data-companion-anchor");
  const cShown = (page) => companion(page).getAttribute("data-companion-visible");
  const cBox = (page) => page.getByTestId("jarvis-companion-link").boundingBox();
  const overlap = (a, b) => Boolean(a && b) && a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
  const lanePadding = (page) => page.locator('[data-jarvis-lane="dock"]').evaluate((el) => getComputedStyle(el).paddingBottom);
  const toBottom = async (page) => {
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await settle(page, 600);
  };
  // Nezávislá kontrola: viditelná část companiona se nekříží s kartou, ovládacím prvkem ani textem stránky.
  const coveredContent = (page) =>
    page.evaluate(() => {
      const root = document.querySelector('[data-testid="jarvis-companion"]');
      if (!root || root.getAttribute("data-companion-visible") !== "true") return [];
      const r = root.querySelector('[data-testid="jarvis-companion-link"]').getBoundingClientRect();
      const vis = { left: Math.max(r.left, 0), right: Math.min(r.right, document.documentElement.clientWidth), top: r.top, bottom: r.bottom };
      const sel = ".rounded-card, a[href], button, input, textarea, select, [role='button'], [role='switch'], p, h1, h2, h3, li, img, table";
      return [...document.querySelectorAll(sel)]
        .filter((el) => !root.contains(el) && !el.closest("[data-desktop-sidebar]"))
        .map((el) => ({ el, b: el.getBoundingClientRect() }))
        .filter(({ b }) => b.width > 0 && b.height > 0 && b.left < vis.right && vis.left < b.right && b.top < vis.bottom && vis.top < b.bottom)
        // jen opravdu viditelné: prvek oříznutý scrollem (např. dlouhý seznam konverzací) pod Jarvisem není
        .filter(({ el, b }) => {
          const x = (Math.max(b.left, vis.left) + Math.min(b.right, vis.right)) / 2;
          const y = (Math.max(b.top, vis.top) + Math.min(b.bottom, vis.bottom)) / 2;
          return document.elementsFromPoint(x, y).includes(el);
        })
        .map(({ el }) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}`)
        .slice(0, 5);
    });

  for (const [label, width, height] of [["1366", 1366, 768], ["wide", 1920, 1080]]) {
    const { ctx, page, errors } = await open("/", { width, height });
    await companion(page).waitFor({ timeout: 4000 }).catch(() => undefined);
    await settle(page, 1500); // první měření + pozdější kontrola po načtení dat
    const top = { state: await cState(page), anchor: await cAnchor(page), shown: await cShown(page) };
    const coveredTop = await coveredContent(page);
    check(`companion @${label} nahoře: nezakrývá karty ani ovládání`, coveredTop.length === 0, `${JSON.stringify(top)} ${coveredTop.join(", ")}`);
    check(`companion @${label} nahoře: je vidět (volná kotva nebo vykouknutí od okraje)`, top.shown === "true" && ["left", "left-mid", "center", "right-mid", "right", "edge"].includes(top.anchor ?? ""), JSON.stringify(top));
    const sidebar = await page.locator("[data-desktop-sidebar]").boundingBox();
    check(`companion @${label}: nepřekrývá navigaci`, !overlap(await cBox(page), sidebar));
    await page.screenshot({ path: `${OUT}companion-top-${label}.png` });

    // během scrollu průhledný, po dosednutí znovu na volném místě
    await page.mouse.wheel(0, 500);
    await settle(page, 60);
    const mid = await cShown(page);
    check(`companion @${label}: během scrollu průhledný`, mid === "false", String(mid));
    await settle(page, 500);
    const coveredMid = await coveredContent(page);
    check(`companion @${label}: po scrollu zase vidět a nic nezakrývá`, (await cShown(page)) === "true" && coveredMid.length === 0, coveredMid.join(", "));
    await page.screenshot({ path: `${OUT}companion-scrolled-${label}.png` });

    await toBottom(page);
    const bottom = { anchor: await cAnchor(page), shown: await cShown(page) };
    check(`companion @${label} dole: v pruhu na běžné kotvě`, ["left", "left-mid", "center", "right-mid", "right"].includes(bottom.anchor ?? "") && bottom.shown === "true", JSON.stringify(bottom));
    check(`companion @${label} dole: nic nezakrývá`, (await coveredContent(page)).length === 0);
    const lane = await lanePadding(page);
    check(`companion @${label}: pruh dole jen 104 px (žádná velká mrtvá plocha)`, lane === "104px", lane);
    const fig = await page.getByTestId("jarvis-figure").getAttribute("data-jarvis-asset");
    check(`companion @${label}: postavička z jarvis-shell.svg`, fig === "asset", fig);
    await page.screenshot({ path: `${OUT}companion-bottom-${label}.png` });

    if (label === "1366") {
      // Rychlé přidání: dialog (z-50) companiona překryje
      await page.keyboard.press("Control+Shift+K");
      await qaDialog(page).waitFor({ timeout: 3000 }).catch(() => undefined);
      const covered = await page.evaluate(() => {
        const el = document.querySelector('[data-testid="jarvis-companion-link"]');
        const r = el.getBoundingClientRect();
        return !el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
      });
      check("companion: modální dialog ho překryje (neblokuje akce dialogu)", covered);
      await page.keyboard.press("Escape");
      await settle(page, 300);
      // fokus ovládacího prvku pod Jarvisem → ustoupí na jinou kotvu
      const before = await cAnchor(page);
      const at = await cBox(page);
      await page.evaluate((r) => {
        const input = document.createElement("input");
        input.id = "companion-probe";
        input.style.cssText = `position:fixed;left:${r.x - 10}px;top:${r.y + 20}px;width:90px;height:32px;z-index:1`;
        document.body.appendChild(input);
      }, at);
      await page.focus("#companion-probe");
      await settle(page, 100);
      const after = await cAnchor(page);
      check("companion: fokusované pole pod ním → ustoupí na jinou kotvu", after !== before && after !== `→${before}`, `${before} → ${after}`);
      await page.evaluate(() => document.getElementById("companion-probe")?.remove());
      await settle(page, 6500);
      // klik → AI asistent
      await page.getByTestId("jarvis-companion-link").click();
      await page.waitForURL("**/ai", { timeout: 5000 }).catch(() => undefined);
      check("companion: klik otevře AI asistenta", new URL(page.url()).pathname === "/ai", page.url());
      await settle(page, 800);
      const aiBox = await cBox(page);
      const composer = await page.getByPlaceholder("Napiš, co potřebuješ…").boundingBox();
      const aside = await page.locator("[data-jarvis-ai-dock]").boundingBox();
      const docked = (await cAnchor(page)) === "ai" && aiBox && aside && aiBox.x >= aside.x && aiBox.x + aiBox.width <= aside.x + aside.width;
      check("companion /ai: zaparkovaný ve sloupci konverzací", Boolean(docked), JSON.stringify({ aiBox, aside }));
      check("companion /ai: nepřekrývá pole zprávy ani konverzace", !overlap(aiBox, composer) && (await coveredContent(page)).length === 0);
    }
    check(`companion @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
    await ctx.close();
  }

  // /ai: jen jeden Jarvis – companion zapnutý → avatar v hlavičce skrytý; vypnutý / mobil → avatar zůstává
  const headerAvatar = (page) => page.locator('header [data-testid="jarvis-avatar"]');
  for (const [label, opts, expectCompanion] of [
    ["desktop", { width: 1366, height: 768 }, true],
    ["desktop reduced", { width: 1366, height: 768, reducedMotion: "reduce" }, true],
    ["vypnutý", { width: 1366, height: 768, setup: (p) => p.addInitScript(() => localStorage.setItem("standa-hub:jarvis-companion:v1", "off")) }, false],
    ["mobil 390", { width: 390, height: 844 }, false],
  ]) {
    const { ctx, page, errors } = await open("/ai", opts);
    await settle(page, 400);
    const avatarShown = await headerAvatar(page).isVisible();
    const companionShown = (await companion(page).count()) === 1 && (await cShown(page)) === "true";
    check(
      `companion /ai ${label}: právě jeden Jarvis (${expectCompanion ? "companion" : "avatar v hlavičce"})`,
      expectCompanion ? companionShown && !avatarShown : !companionShown && avatarShown,
      JSON.stringify({ avatarShown, companionShown }),
    );
    if (label === "desktop") await page.screenshot({ path: `${OUT}companion-ai-1366.png` });
    if (label === "vypnutý") await page.screenshot({ path: `${OUT}companion-ai-off.png` });
    check(`companion /ai ${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
    await ctx.close();
  }
  {
    // hlavička /ai se po hydrataci neposune: avatar je skrytý už v prvním vykreslení (skript v <head>)
    const { ctx, page } = await open("/ai", {
      width: 1366,
      height: 768,
      setup: (p) =>
        p.addInitScript(() => {
          document.addEventListener("DOMContentLoaded", () => {
            const el = document.querySelector("[data-jarvis-header-avatar]");
            window.__firstDisplay = el ? getComputedStyle(el).display : "missing";
          });
        }),
    });
    const first = await page.evaluate(() => window.__firstDisplay);
    const now = await page.locator("[data-jarvis-header-avatar]").evaluate((el) => getComputedStyle(el).display);
    check("companion /ai: avatar skrytý už při prvním vykreslení (bez skoku hlavičky)", first === "none" && now === "none", `${first} → ${now}`);
    await ctx.close();
  }

  // chůze mezi kotvami (řízený čas): vzácně (~40–50 s), krátký skok k sousední kotvě,
  // otočení → rozjezd/cesta/dojezd (linear() křivka) → doběhnutí na kotvě
  {
    const { ctx, page, errors } = await open("/", { width: 1366, height: 768, setup: (p) => p.clock.install() });
    const phase = () => companion(page).getAttribute("data-walk-phase");
    const tick = async (ms) => {
      await page.clock.fastForward(ms);
      await settle(page, 120);
    };
    await companion(page).waitFor({ timeout: 4000 }).catch(() => undefined);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await settle(page, 150); // scroll událost přijde až s dalším snímkem
    await tick(2_000);
    check("companion: dole stojí na pravé kotvě", (await cState(page)) === "idle" && (await cAnchor(page)) === "right", `${await cState(page)} ${await cAnchor(page)}`);
    await tick(30_000);
    check("companion: po 30 s pořád stojí (žádný neustálý pohyb)", (await cState(page)) === "idle");
    await tick(13_000);
    const depart = { state: await cState(page), anchor: await cAnchor(page), facing: await companion(page).getAttribute("data-companion-facing"), phase: await phase() };
    check("companion: po ~45 s vyrazí k sousední kotvě, nejdřív se otočí", depart.state === "walking" && depart.anchor === "→right-mid" && depart.facing === "left" && depart.phase === "depart", JSON.stringify(depart));
    const motion = await companion(page).evaluate((el) => ({ delay: el.style.transitionDelay, easing: el.style.transitionTimingFunction, step: el.style.getPropertyValue("--jarvis-step") }));
    check("companion: cesta s rozjezdem a dojezdem (linear() křivka, vykročení po otočení)", motion.delay === "280ms" && motion.easing.startsWith("linear(") && motion.step === "500ms", JSON.stringify(motion));
    await tick(300);
    const legs = await page.locator(".jarvis-leg-l").evaluate((el) => getComputedStyle(el).animationName);
    check("companion: při cestě kroky nohou synchronizované s rychlostí", (await phase()) === "travel" && legs === "jarvis-swing", `${await phase()} ${legs}`);
    await page.screenshot({ path: `${OUT}companion-walking.png` });
    // fáze arrive (doběhnutí 360 ms) je pokrytá deterministicky v lib/jarvisCompanion.test.mjs
    await tick(8_000);
    await tick(1_000);
    const arrived = { state: await cState(page), anchor: await cAnchor(page) };
    check("companion: dojde na sousední kotvu a zase stojí", arrived.state === "idle" && arrived.anchor === "right-mid", JSON.stringify(arrived));
    check("companion chůze: bez chyb JS", errors.length === 0, errors.join("; "));
    await ctx.close();
  }

  // obsazené kotvy: karta přes pravou kotvu → jiná volná; všechno obsazené → vykoukne od okraje
  {
    const { ctx, page, errors } = await open("/", { width: 1366, height: 768 });
    await toBottom(page);
    const block = async (css) => {
      await page.evaluate((style) => {
        const el = document.createElement("div");
        el.className = "companion-blocker rounded-card";
        el.style.cssText = `position:fixed;z-index:20;bottom:0;height:120px;${style}`;
        document.body.appendChild(el);
      }, css);
      await page.mouse.wheel(0, -1);
      await settle(page, 600);
    };
    await block("right:30px;width:170px");
    check("companion: obsazená pravá kotva → přesun na volnou", ["right-mid", "→right-mid"].includes(await cAnchor(page) ?? ""), await cAnchor(page));
    await settle(page, 6500);
    check("companion: po přesunu nic nezakrývá", (await coveredContent(page)).filter((c) => !c.includes("companion-blocker")).length === 0);
    await block("left:240px;width:1080px");
    const peek = { anchor: await cAnchor(page), state: await cState(page) };
    check("companion: všechny kotvy obsazené → vykoukne od pravého okraje", peek.anchor === "edge", JSON.stringify(peek));
    await page.screenshot({ path: `${OUT}companion-edge.png` });
    await block("right:0;width:60px");
    check("companion: ani okraj volný → dočasně schovaný", (await companion(page).count()) === 0);
    await page.evaluate(() => document.querySelectorAll(".companion-blocker").forEach((el) => el.remove()));
    await page.mouse.wheel(0, 1);
    await settle(page, 700);
    check("companion: po uvolnění se vrátí", (await companion(page).count()) === 1 && (await cShown(page)) === "true");
    check("companion obsazené kotvy: bez chyb JS", errors.length === 0, errors.join("; "));
    await ctx.close();
  }

  // všechny stavy a priority přes vývojovou ukázku
  const jarvisProbe = await fetch(`${BASE}/dev/jarvis`, { redirect: "manual" }).catch(() => null);
  if (!jarvisProbe || jarvisProbe.status === 404) {
    console.log("· /dev/jarvis není zapnutá (MOTION_PREVIEW=1) – kontroly stavů companiona přeskočeny");
  } else {
    for (const motion of ["no-preference", "reduce"]) {
      const tag = motion === "reduce" ? "companion stavy (reduced)" : "companion stavy";
      const { ctx, page, errors } = await open("/dev/jarvis", { width: 1366, height: 768, reducedMotion: motion });
      await settle(page, 400);
      const btn = (name) => page.getByRole("button", { name, exact: true });
      const bubble = async () => (await page.getByTestId("jarvis-bubble").innerText()).trim();
      const moods = [
        ["Poslouchá", "listening", "Poslouchám…"],
        ["Přemýšlí", "thinking", "Moment, přemýšlím…"],
        ["Čeká na potvrzení", "warning", "Čekám na tvoje potvrzení."],
      ];
      for (const [button, state, text] of moods) {
        await btn(button).click();
        await settle(page, 250);
        const got = { state: await cState(page), bubble: await bubble() };
        check(`${tag}: ${state} + bublina`, got.state === state && got.bubble === text, JSON.stringify(got));
        if (motion !== "reduce") await page.screenshot({ path: `${OUT}companion-${state}.png` });
      }
      await btn("Úspěch").click();
      await settle(page, 100);
      check(`${tag}: úspěch nepřebije čekající potvrzení (priorita)`, (await cState(page)) === "warning");
      await btn("Klid").click();
      await settle(page, 100);
      check(`${tag}: po vyřešení potvrzení se ukáže odložená oslava`, (await cState(page)) === "success");
      await settle(page, 2600);
      await btn("Úspěch").click();
      await settle(page, 250);
      check(`${tag}: success`, (await cState(page)) === "success");
      const cheer = await page.locator(".jarvis-body").evaluate((el) => getComputedStyle(el).animationName);
      check(`${tag}: oslava ${motion === "reduce" ? "bez poskakování" : "poskočí"}`, motion === "reduce" ? cheer === "none" : cheer === "jarvis-cheer", cheer);
      if (motion !== "reduce") await page.screenshot({ path: `${OUT}companion-success.png` });
      await settle(page, 2800);
      check(`${tag}: po oslavě zpět idle, bublina zmizí`, (await cState(page)) === "idle" && (await bubble()) === "");
      await btn("Chyba").click();
      await settle(page, 250);
      const err = { state: await cState(page), bubble: await bubble() };
      check(`${tag}: error + bublina`, err.state === "error" && err.bubble === "Tohle se nepovedlo.", JSON.stringify(err));
      if (motion !== "reduce") await page.screenshot({ path: `${OUT}companion-error.png` });
      await btn("Přemýšlí").click();
      await settle(page, 100);
      check(`${tag}: chyba má přednost před přemýšlením`, (await cState(page)) === "error");
      await settle(page, 3300);
      check(`${tag}: chyba odezní → zpět k přemýšlení`, (await cState(page)) === "thinking");
      if (motion === "reduce") {
        const anims = await page.evaluate(() => document.querySelector('[data-testid="jarvis-companion"]').getAnimations({ subtree: true }).length);
        check("companion reduced: žádné animace ani dýchání", anims === 0, String(anims));
        await page.screenshot({ path: `${OUT}companion-reduced.png` });
      }
      await btn("Klid").click();
      check(`${tag}: bez chyb JS`, errors.length === 0, errors.join("; "));
      await ctx.close();
    }
  }

  // reduced motion: žádné potulování; obsazená kotva → přestaví se (nechodí) a nic nezakrývá
  {
    const { ctx, page } = await open("/", { width: 1366, height: 768, reducedMotion: "reduce", setup: (p) => p.clock.install() });
    await companion(page).waitFor({ timeout: 4000 }).catch(() => undefined);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await settle(page, 150); // scroll událost přijde až s dalším snímkem
    await page.clock.fastForward(2_000);
    await page.clock.fastForward(200_000);
    await settle(page, 100);
    check("companion reduced: ani po 200 s nechodí, stojí vpravo", (await cState(page)) === "idle" && (await cAnchor(page)) === "right");
    await page.evaluate(() => window.scrollTo(0, 0));
    await settle(page, 150);
    await page.clock.fastForward(2_000);
    await settle(page, 100);
    const st = { state: await cState(page), anchor: await cAnchor(page), covered: await coveredContent(page) };
    check("companion reduced nahoře: nechodí a nic nezakrývá", st.state !== "walking" && !String(st.anchor).startsWith("→") && st.covered.length === 0, JSON.stringify(st));
    await ctx.close();
  }

  // vypnutí v postranním panelu (preference v localStorage, přežije reload)
  {
    const { ctx, page, errors } = await open("/", { width: 1366, height: 768 });
    const toggle = page.getByTestId("jarvis-companion-toggle");
    check("companion: přepínač je switch, zapnutý", (await toggle.getAttribute("role")) === "switch" && (await toggle.getAttribute("aria-checked")) === "true");
    await toggle.click();
    await settle(page, 200);
    const lane = await lanePadding(page);
    check("companion vypnutý: zmizí i vyhrazený pruh", (await companion(page).count()) === 0 && lane === "0px", lane);
    await page.screenshot({ path: `${OUT}companion-off.png` });
    await page.reload({ waitUntil: "networkidle" });
    await settle(page, 500);
    check("companion vypnutý: zůstane vypnutý po obnovení", (await companion(page).count()) === 0 && (await toggle.getAttribute("aria-checked")) === "false");
    await toggle.click();
    await settle(page, 300);
    check("companion: znovu zapnutý", (await companion(page).count()) === 1);
    check("companion přepínač: bez chyb JS", errors.length === 0, errors.join("; "));
    await ctx.close();
  }

  // mobil / tablet: žádný companion, žádné potulování
  for (const [label, width, height] of [["390", 390, 844], ["768", 768, 1024]]) {
    const { ctx, page, errors } = await open("/", { width, height });
    check(`companion @${label}: nezobrazuje se`, (await companion(page).count()) === 0);
    check(`companion @${label}: bez vodorovného přetečení`, (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
    if (label === "390") await page.screenshot({ path: `${OUT}companion-mobile-390.png` });
    check(`companion @${label}: bez chyb JS`, errors.length === 0, errors.join("; "));
    await ctx.close();
  }

  // obrázek se nenačte → CSS záloha hlavy
  {
    const { ctx, page, errors } = await open("/", {
      width: 1366,
      height: 768,
      setup: (p) => p.route(/jarvis-shell\.svg/, (route) => route.fulfill({ status: 404, body: "" })),
    });
    await toBottom(page);
    const figure = page.getByTestId("jarvis-figure");
    const mode = await figure.getAttribute("data-jarvis-asset");
    check("companion: když obrázek selže, ukáže zálohu", mode === "fallback" && (await figure.getByTestId("jarvis-fallback").count()) === 1, mode);
    await page.screenshot({ path: `${OUT}companion-fallback.png` });
    check("companion záloha: bez chyb JS", errors.length === 0, errors.join("; "));
    await ctx.close();
  }
}

// 25) MRK-15 – vizuální základ: jednotné čárové ikony místo emoji (Řídicí centrum, Dnes, Škola, WoT).
{
  const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}]/u;
  for (const [path, name] of [["/", "dashboard"], ["/today", "dnes"], ["/school", "škola"], ["/wot", "wot"]]) {
    const { ctx, page, errors } = await open(path);
    await page.waitForTimeout(500);
    const mainText = await page.locator("main").innerText();
    check(`ikony ${name}: žádná funkční emoji v obsahu`, !EMOJI.test(mainText), (mainText.match(EMOJI) || []).join(""));
    const svgs = await page.locator("main svg[data-icon]").evaluateAll((els) => els.map((e) => ({ w: e.getBoundingClientRect().width, sw: e.getAttribute("stroke-width"), hidden: e.getAttribute("aria-hidden") })));
    if (path === "/" || path === "/today") {
      const tiles = await page.locator("main [data-icon-tile]").count();
      check(`ikony ${name}: hlavičky karet s ikonou v rámečku`, tiles >= 3, String(tiles));
    }
    check(`ikony ${name}: jednotný tah a dekorativní (aria-hidden)`, svgs.length > 0 && svgs.every((x) => x.sw === "1.75" && x.hidden === "true"), JSON.stringify(svgs.slice(0, 3)));
    check(`ikony ${name}: bez chyb JS`, errors.length === 0, errors.join("; "));
    if (path === "/") {
      const bell = page.locator('button[aria-label^="Notifikace"] svg[data-icon="bell"]');
      check("ikony shell: zvonek = SVG ikona", (await bell.count()) >= 1);
      await page.screenshot({ path: `${OUT}icons-dashboard.png`, fullPage: true });
    }
    if (path === "/school") await page.screenshot({ path: `${OUT}icons-school.png`, fullPage: true });
    await ctx.close();
  }
}

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} kontrol prošlo. Screenshoty: ${OUT}`);
process.exit(failed.length ? 1 : 0);
