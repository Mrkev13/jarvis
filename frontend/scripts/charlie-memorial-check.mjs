// Focused MRK-58 browser check. Run against a local frontend + fixture API; no real data or Groq.
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.UI_BASE_URL || "http://127.0.0.1:3035";
const visualOut = process.env.VISUAL_OUT || null;
if (visualOut) mkdirSync(visualOut, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM });

async function open(width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: "dark", hasTouch: width < 500 });
  const page = await context.newPage();
  const errors = [];
  const imageRequests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("charlie-memorial")) imageRequests.push(request.url());
  });
  await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(700);
  return { context, page, errors, imageRequests };
}

async function assertDialogFits(page) {
  const dialog = page.getByRole("dialog", { name: "Charlie" });
  await dialog.waitFor();
  assert.equal(await dialog.getByText("Pořád součást Hubu.", { exact: true }).count(), 1);
  const image = dialog.getByRole("img", { name: "Charlie" });
  await image.evaluate((element) => new Promise((resolve, reject) => {
    const img = element;
    if (img.complete && img.naturalWidth > 0) return resolve();
    img.addEventListener("load", () => resolve(), { once: true });
    img.addEventListener("error", () => reject(new Error("Charlie image failed to load")), { once: true });
  }));
  assert.ok(await image.evaluate((element) => element.naturalWidth > 0), "the local memorial image must decode");
  const imageBox = await image.boundingBox();
  const viewport = page.viewportSize();
  assert.ok(imageBox && viewport && imageBox.width <= viewport.width && imageBox.height <= viewport.height);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  return dialog;
}

try {
  {
    const { context, page, errors, imageRequests } = await open(1366);
    const paw = page.getByRole("button", { name: "Charlie" });
    await paw.waitFor();
    const pawBox = await paw.boundingBox();
    assert.ok(pawBox && pawBox.width <= 40 && pawBox.height <= 40, "the paw stays a small, low-attention control");
    await page.waitForTimeout(500);
    const beforeWidth = await page.locator("main").evaluate((element) => element.getBoundingClientRect().width);
    await paw.click();
    await assertDialogFits(page);
    if (visualOut) await page.screenshot({ path: join(visualOut, "charlie-desktop.png"), fullPage: false });
    const afterWidth = await page.locator("main").evaluate((element) => element.getBoundingClientRect().width);
    assert.equal(afterWidth, beforeWidth, "opening the fixed overlay must not shift app width");
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog", { name: "Charlie" }).count(), 0);
    assert.equal(await paw.evaluate((element) => element === document.activeElement), true, "focus returns to the paw");

    await paw.click();
    await page.getByRole("dialog", { name: "Charlie" }).getByRole("button", { name: "Zavřít" }).click();
    assert.equal(await page.getByRole("dialog", { name: "Charlie" }).count(), 0);

    await paw.click();
    const backdrop = page.getByRole("dialog", { name: "Charlie" }).locator("..");
    await backdrop.click({ position: { x: 4, y: 4 } });
    assert.equal(await page.getByRole("dialog", { name: "Charlie" }).count(), 0);
    assert.deepEqual(errors, []);
    assert.ok(imageRequests.length >= 1 && imageRequests.every((url) => new URL(url).origin === new URL(base).origin));
    console.log("desktop: subtle trigger, dialog fit, Escape/X/backdrop and focus restoration passed");
    await context.close();
  }

  {
    const { context, page, errors, imageRequests } = await open(390);
    await page.getByRole("button", { name: "Otevřít menu" }).click();
    const menu = page.getByRole("dialog", { name: "Menu" });
    const paw = menu.getByRole("button", { name: "Charlie" });
    await paw.click();
    assert.equal(await page.getByRole("dialog", { name: "Menu" }).count(), 0, "the mobile menu must not remain as a nested modal");
    await assertDialogFits(page);
    if (visualOut) await page.screenshot({ path: join(visualOut, "charlie-mobile.png"), fullPage: false });
    await page.keyboard.press("Escape");
    const returnedPaw = page.getByRole("dialog", { name: "Menu" }).getByRole("button", { name: "Charlie" });
    await returnedPaw.waitFor();
    assert.equal(await returnedPaw.evaluate((element) => element === document.activeElement), true, "mobile focus returns to the paw");
    assert.deepEqual(errors, []);
    assert.ok(imageRequests.every((url) => new URL(url).origin === new URL(base).origin));
    console.log("mobile: paw in menu, dialog fit, no overflow or external image request passed");
    await context.close();
  }
} finally {
  await browser.close();
}
