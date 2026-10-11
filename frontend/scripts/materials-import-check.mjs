// Prohlížečová kontrola importu ZIPu z Moodle na /school/materials (MRK-56) – doplněk ui-check.mjs.
// Předpoklady jako ui-check: node scripts/mock-api.mjs + npx next start -p 3000 -H 127.0.0.1 (žádný Groq).
//   node scripts/materials-import-check.mjs
// Syntetické soubory vytvořené v paměti – žádný reálný export z Moodle.
const BASE = process.env.UI_BASE_URL || "http://127.0.0.1:3000";
const MOCK_API = process.env.MOCK_API_URL || "http://127.0.0.1:8000";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {});
const results = [];
function check(name, ok, detail = "") {
  results.push(ok);
  console.log(`${ok ? "✓" : "✗"} [materials-import] ${name}${detail ? ` – ${detail}` : ""}`);
}
const imports = async () => (await (await fetch(`${MOCK_API}/__mock/materials/imports`)).json());

const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
let listLoads = 0;
page.on("request", (r) => { if (new URL(r.url()).pathname === "/school/materials" && r.method() === "GET") listLoads += 1; });
await page.goto(`${BASE}/school/materials`, { waitUntil: "networkidle" });
await page.waitForTimeout(500);

const button = page.getByRole("button", { name: "Importovat ZIP z Moodle" });
check("tlačítko „Importovat ZIP z Moodle“ je vidět", await button.isVisible());
const input = page.getByLabel("Soubor ZIP s obsahem kurzu z Moodle");
check("souborový vstup má popisek a přijímá jen .zip", (await input.count()) === 1 && (await input.getAttribute("accept"))?.includes(".zip"));

// nepodporovaný soubor: server se vůbec nevolá
const before = (await imports()).length;
await input.setInputFiles({ name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic") });
await page.waitForTimeout(500);
check("ne-ZIP soubor: bezpečná hláška a žádný požadavek", (await page.getByText(/Vyber soubor \.zip/).count()) === 1 && (await imports()).length === before);

// úspěch: syrový ZIP na endpoint, souhrn, znovunačtení seznamu
const loadsBefore = listLoads;
const zip = Buffer.concat([Buffer.from("PK"), Buffer.from([3, 4]), Buffer.from("synthetic export")]);
await input.setInputFiles({ name: "kurz.zip", mimeType: "application/zip", buffer: zip });
await page.getByText(/Import hotový/).waitFor({ timeout: 5000 }).catch(() => undefined);
const sent = await imports();
check("ZIP odeslán na POST /school/materials/import-zip jako syrové tělo", sent.length === before + 1 && sent.at(-1) === zip.length, JSON.stringify(sent));
check("souhrn importu zobrazen", (await page.getByText("Import hotový: nové 3, změněné 0, beze změny 1 (nepodporované soubory 1).").count()) === 1);
check("materiály a kurzy se po importu znovu načetly", listLoads > loadsBefore, `${listLoads - loadsBefore}×`);

// chyba z backendu: jen bezpečný český text
await input.setInputFiles({ name: "jiny.zip", mimeType: "application/zip", buffer: Buffer.from("not a course export") });
await page.getByText(/nevypadá jako export kurzu/).waitFor({ timeout: 5000 }).catch(() => undefined);
check("chyba backendu: bezpečná hláška (kategorie, ne tělo odpovědi)", (await page.getByText(/nevypadá jako export kurzu/).count()) === 1);
check("žádné chyby JS", errors.length === 0, errors.join(" | "));
await ctx.close();
await browser.close();
const failed = results.filter((r) => !r).length;
console.log(`\n[materials-import] ${results.length - failed}/${results.length} kontrol prošlo.`);
process.exit(failed ? 1 : 0);
