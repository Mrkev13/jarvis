// Vizuální a přístupnostní kontrola migrovaných stránek (Roadmap 4A + 4B + 4B.1).
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
  // Roadmap 4C
  ["/ai", "ai"],
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
  check("hledání: prázdný dotaz ukáže navigaci", (await dialog.getByRole("group", { name: "Navigace" }).getByRole("option").count()) === 13);
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

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} kontrol prošlo. Screenshoty: ${OUT}`);
process.exit(failed.length ? 1 : 0);
