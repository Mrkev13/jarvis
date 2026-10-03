// Regrese (Phase E live): manifest, service worker a ikony PWA chránil auth middleware → bez session cookie
// (prohlížeč manifest stahuje BEZ cookies) dostal prohlížeč 307 na /login místo souboru → instalace na plochu
// (iOS = jediná cesta k Web Push) a registrace SW bez platné session selhaly. Spuštění: `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { isPublicPath } from "./publicPaths.ts";

test("PWA assets needed for Web Push are public", () => {
  for (const path of ["/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png"]) {
    assert.equal(isPublicPath(path), true, path);
  }
});

test("existing public paths stay public", () => {
  for (const path of ["/login", "/_next/static/chunks/a.js", "/favicon.ico", "/api/x", "/robots.txt"]) {
    assert.equal(isPublicPath(path), true, path);
  }
});

test("app pages and look-alike paths still require a session", () => {
  for (const path of ["/", "/reminders", "/ai", "/finance", "/sw.js.map", "/sw.jsx", "/manifest.webmanifest/x", "/icon-192.png.html"]) {
    assert.equal(isPublicPath(path), false, path);
  }
});
