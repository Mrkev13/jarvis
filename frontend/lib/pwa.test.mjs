// MRK-24: installable PWA + Web Push foundation guarantees (manifest, service worker scope/caching, opt-in only).
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import ts from "typescript";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

function loadManifest() {
  const compiled = ts.transpileModule(read("app/manifest.ts"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const mod = { exports: {} };
  new Function("module", "exports", compiled)(mod, mod.exports);
  return mod.exports.default();
}

function pngSize(path) {
  const data = readFileSync(new URL(path, root));
  assert.equal(data.subarray(1, 4).toString("latin1"), "PNG", `${path} is a PNG`);
  return [data.readUInt32BE(16), data.readUInt32BE(20)];
}

test("manifest is installable: standalone app rooted at / with 192 and 512 px icons", () => {
  const manifest = loadManifest();
  assert.equal(manifest.name, "Standa Hub");
  assert.ok(manifest.short_name && manifest.short_name.length <= 12, "short name fits under a home-screen icon");
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.id, "/");
  assert.match(manifest.theme_color, /^#[0-9a-f]{6}$/i);
  assert.match(manifest.background_color, /^#[0-9a-f]{6}$/i);
  const sizes = Object.fromEntries(manifest.icons.map((icon) => [icon.sizes, icon]));
  for (const size of ["192x192", "512x512"]) {
    const icon = sizes[size];
    assert.ok(icon, `icon ${size} declared`);
    assert.equal(icon.type, "image/png");
    assert.ok(icon.src.startsWith("/") && !icon.src.startsWith("//"), "same-origin icon");
    assert.deepEqual(pngSize(`public${icon.src}`).join("x"), size, `${icon.src} really is ${size}`);
  }
});

test("service worker never caches or intercepts requests, so private data is never served stale", () => {
  const sw = read("public/sw.js");
  assert.doesNotMatch(sw, /addEventListener\(\s*["']fetch["']/, "no fetch handler");
  assert.doesNotMatch(sw, /\bcaches\b|CacheStorage|importScripts/, "no Cache API, no imported code");
  assert.match(sw, /addEventListener\(\s*["']push["']/);
  assert.match(sw, /addEventListener\(\s*["']notificationclick["']/);
  // Notification clicks only navigate inside the app's own origin.
  assert.match(sw, /raw\.startsWith\("\/"\) && !raw\.startsWith\("\/\/"\)/);
  assert.match(sw, /new URL\(path, self\.location\.origin\)/);
});

// MRK-80: připomínky jsou všimnutelné a jdou vyřídit z oznámení – jen přes origin API z registrace.
test("reminder notifications stay, vibrate, renotify and offer done / snooze actions", () => {
  const sw = read("public/sw.js");
  for (const flag of ["requireInteraction: true", "renotify: Boolean(tag)", "vibrate: REMINDER_VIBRATE"]) {
    assert.ok(sw.includes(flag), flag);
  }
  assert.match(sw, /action: "done", title: "Hotovo"/);
  assert.match(sw, /action: "snooze"/);
  // the only network call is to the API origin from the registration URL, with the session cookie
  // MRK-149: druhý fetch = docházka z oznámení (stejný origin API, stejná cookie relace)
  assert.equal((sw.match(/\bfetch\(/g) || []).length, 2, "reminder + attendance fetch only");
  assert.match(sw, /fetch\(`\$\{api\}\$\{path\}\?source=push`/);
  assert.match(sw, /url\.protocol === "https:" \|\| url\.protocol === "http:" \? url\.origin : null/);
  // a failed action opens the app instead of failing silently
  assert.match(sw, /ok \? undefined : openApp\(`\/reminders\?reminder=\$\{reminderId\}`\)/);
});

function sourceFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...sourceFiles(path));
    else if (/\.(tsx?|mjs)$/.test(name) && !name.endsWith(".test.mjs")) out.push(path);
  }
  return out;
}

test("permission is requested and the worker registered only from the explicit opt-in click", () => {
  const app = fileURLToPath(root);  // decodes spaces/diacritics in the checkout path
  const callers = ["app", "components", "lib", "hooks", "modules"]
    .flatMap((dir) => sourceFiles(join(app, dir)))
    .filter((file) => /requestPermission|serviceWorker\.register/.test(readFileSync(file, "utf8")))
    .map((file) => file.replace(/\\/g, "/").split("/frontend/").pop());
  assert.deepEqual(callers, ["components/PushSettings.tsx"], "a single opt-in surface");

  const settings = read("components/PushSettings.tsx");
  const enable = settings.slice(settings.indexOf("async function enable()"), settings.indexOf("async function sendTest()"));
  assert.ok(enable.includes("Notification.requestPermission()"), "prompt lives in enable()");
  assert.ok(enable.includes('navigator.serviceWorker.register(serviceWorkerUrl(API_URL), { scope: "/"'), "worker scope is the whole app");
  const outside = settings.replace(enable, "");
  assert.doesNotMatch(outside, /requestPermission|serviceWorker\.register/, "nothing prompts or registers on load");
  assert.match(settings, /onClick=\{\(\) => void enable\(\)\}/, "enable() runs only from a click");
});


// MRK-149: docházka z oznámení – service worker spuštěný ve vm s falešným self / fetch / clients.
test("attendance notification offers Byl / Nebyl and writes attendance through the API origin", async () => {
  const { runInNewContext } = await import("node:vm");
  const listeners = {};
  const shown = [];
  const calls = [];
  const opened = [];
  let ok = true;
  const self = {
    location: { href: "https://hub.test/sw.js?api=https%3A%2F%2Fapi.test", origin: "https://hub.test" },
    addEventListener: (name, fn) => { listeners[name] = fn; },
    registration: { showNotification: (title, options) => { shown.push({ title, options }); return Promise.resolve(); } },
    clients: { matchAll: async () => [], openWindow: async (url) => { opened.push(url); } },
    skipWaiting: () => {},
  };
  const fetch = async (url, init) => { calls.push({ url, init }); return { ok }; };
  runInNewContext(read("public/sw.js"), { self, fetch, URL, JSON, Promise, Number, console });
  const push = (data) => new Promise((resolve) => listeners.push({ data: { json: () => data }, waitUntil: resolve }));
  await push({ title: "Byl jsi na hodině?", body: "Fyzika", url: "/school?subject=3", kind: "attendance",
    subject_id: 3, week_start: "2026-11-09" });
  const { options } = shown.at(-1);
  assert.deepEqual(JSON.parse(JSON.stringify(options.actions.map((a) => a.title))), ["Byl", "Nebyl"]);
  const click = (action, data = options.data) => new Promise((resolve) =>
    listeners.notificationclick({ action, notification: { data, close: () => {} }, waitUntil: resolve }));
  await click("absent");
  assert.equal(calls.at(-1).url, "https://api.test/school/subject/3/attendance");
  assert.equal(calls.at(-1).init.method, "PUT");
  assert.equal(calls.at(-1).init.credentials, "include");
  assert.deepEqual(JSON.parse(calls.at(-1).init.body), { week_start: "2026-11-09", present: false });
  ok = false;  // zápis selhal (offline / týden bez výuky) → otevře Školu
  await click("present");
  assert.equal(opened.at(-1), "https://hub.test/school?subject=3");
  // podvržená data ze zprávy nic neodešlou
  const before = calls.length;
  await push({ kind: "attendance", subject_id: "3; rm", week_start: "../x" });
  assert.equal(shown.at(-1).options.actions, undefined);
  await click("present", shown.at(-1).options.data);
  assert.equal(calls.length, before);
});
