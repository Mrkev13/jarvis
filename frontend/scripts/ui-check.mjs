// Vizuální a přístupnostní kontrola migrovaných stránek (Roadmap 4A–4H).
//
// Předpoklady: `npm run build`, pak v jiných terminálech
//   node scripts/mock-api.mjs            (fixtures, žádný Groq)
//   npx next start -p 3000 -H 127.0.0.1
// Spuštění: node scripts/ui-check.mjs   (Playwright: PLAYWRIGHT_MODULE=/cesta/k/playwright/index.mjs,
//           jinak `import("playwright")`; prohlížeč: PLAYWRIGHT_CHROMIUM=/cesta/k/chromium volitelně)
// Výstup: screenshoty do scripts/.ui-check/ (gitignore) a seznam kontrol; exit 1 při selhání.
import { mkdirSync, readFileSync } from "node:fs";
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
  const { ctx, page, errors } = await open("/ai", { width: 1366, height: 900 });
  const box = page.getByLabel("Zpráva pro Standa AI");
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
  await failedCard.getByRole("button", { name: "Zkusit znovu" }).click();
  await page.waitForTimeout(1200);
  check("ai: druhý pokus projde", (await page.getByRole("list", { name: "Akce čekající na potvrzení" }).count()) === 0);

  // chyby: rate limit (zkusit znovu), denní limit (bez zkusit znovu), 500
  await aiSend(page, "test limit");
  await page.waitForTimeout(1300);
  check("ai: rate limit – upozornění se Zkusit znovu", (await page.getByRole("alert").filter({ hasText: "vytížená" }).getByRole("button", { name: "Zkusit znovu" }).count()) === 1);
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
  const toggle = rowOf(page, "reminder:1").getByRole("button", { name: "Odložit připomínku: Fyzioterapie" });
  await toggle.click();
  const group = page.getByRole("group", { name: "Odložit „Fyzioterapie“ – na kdy?" });
  check("dnes odložit: nabídka s pevnými volbami", JSON.stringify(await group.getByRole("button").allInnerTexts()) === JSON.stringify(["+15 min", "+1 h", "+3 h", "Zítra 8:00", "Zrušit"]) && (await toggle.getAttribute("aria-expanded")) === "true");
  check("dnes odložit: fokus na první volbu", (await focusedLabel(page)) === "+15 min: Fyzioterapie");
  await page.screenshot({ path: `${OUT}today-snooze.png` });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(80);
  check("dnes odložit: Esc zavře a vrátí fokus", (await group.count()) === 0 && (await focusedLabel(page)) === "Odložit připomínku: Fyzioterapie");
  check("dnes odložit: Esc nespustí globální zkratky", (await page.getByRole("dialog").count()) === 0);
  await toggle.click();
  await group.getByRole("button", { name: "Zítra 8:00: Fyzioterapie" }).click();
  await page.getByText(/^Odloženo: Fyzioterapie/).waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes odložit: zítra 8:00 (pražské datum ze serveru)", (await todayCalls()).includes("snooze:reminder:1:2026-10-12T08:00"));
  check("dnes odložit: obnoveno", (await page.locator('[data-today-notice]').innerText()).includes("Odloženo: Fyzioterapie (Zítra 8:00)"));

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
  await page.keyboard.press("Tab");
  check("klávesnice dnes: Tab na Odložit", (await focusedLabel(page)) === "Odložit připomínku: Fyzioterapie");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(80);
  await page.keyboard.press("Tab");
  check("klávesnice dnes: Tab na volbu +1 h", (await focusedLabel(page)) === "+1 h: Fyzioterapie");
  await page.keyboard.press("Enter");
  await page.getByText(/^Odloženo: Fyzioterapie \(\+1 h\)/).waitFor({ timeout: 5000 }).catch(() => undefined);
  check("klávesnice dnes: odloženo o hodinu", (await todayCalls()).includes("snooze:reminder:1:+60"));
  check("klávesnice dnes: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
}
// mobil 390 px: akce ≥ 44 px, odložení se vejde, žádné přetečení
{
  await todayMock("/__mock/today/reset");
  const { ctx, page, errors } = await open("/today", { width: 390, height: 844 });
  const row = rowOf(page, "reminder:1");
  const done = await row.getByRole("button", { name: "Dokončit připomínku: Fyzioterapie" }).boundingBox();
  check("dnes mobil: Hotovo ≥ 44 px", Boolean(done && done.height >= 44), JSON.stringify(done));
  await row.getByRole("button", { name: "Odložit připomínku: Fyzioterapie" }).tap();
  const opts = await row.getByRole("group").getByRole("button").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), Math.round(r.height)]; }));
  check("dnes mobil: volby odložení se vejdou a jsou ≥ 44 px", opts.every(([l, r, h]) => l >= 0 && r <= 390 && h >= 44), JSON.stringify(opts));
  check("dnes mobil: bez přetečení", (await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 0);
  const title = await row.getByText(/Fyzioterapie$/).first().boundingBox();
  const rowBox = await row.boundingBox();
  check("dnes mobil: název nahoře v řádku", Boolean(title && rowBox && title.y - rowBox.y < 80), JSON.stringify({ t: title?.y, r: rowBox?.y }));
  await row.screenshot({ path: `${OUT}today-mobile-actions.png` });
  await row.getByRole("button", { name: "+15 min: Fyzioterapie" }).tap();
  await page.getByText(/^Odloženo: Fyzioterapie/).waitFor({ timeout: 5000 }).catch(() => undefined);
  check("dnes mobil: odložení ťuknutím", (await todayCalls()).includes("snooze:reminder:1:+15"));
  check("dnes mobil: bez chyb JS", errors.length === 0, errors.join("; "));
  await ctx.close();
  await todayMock("/__mock/today/reset");
}

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} kontrol prošlo. Screenshoty: ${OUT}`);
process.exit(failed.length ? 1 : 0);
