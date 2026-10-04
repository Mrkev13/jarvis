// Game Enrichment A: odkud skript smí stahovat a jak bezpečně vytáhne ikony měn z oficiálního stylu portálu WoT.
import assert from "node:assert/strict";
import { test } from "node:test";

import { extractCssSvg, findPortalStylesheet, isOfficialUrl, isSafeSvg, MAX_SVG_BYTES, PORTAL_HOSTS } from "./gameAssetSources.ts";

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14"><path fill="#F5A623" d="M7 0l2 5h5l-4 3 2 6-5-4-5 4 2-6-4-3h5z"/></svg>';
const b64 = (s) => Buffer.from(s).toString("base64");

test("official hosts only: exact host, https", () => {
  assert.equal(isOfficialUrl("https://eu-wotp.wgcdn.co/static/x/main.css", PORTAL_HOSTS), true);
  assert.equal(isOfficialUrl("https://worldoftanks.eu/en/tankopedia/", PORTAL_HOSTS), true);
  assert.equal(isOfficialUrl("http://worldoftanks.eu/en/", PORTAL_HOSTS), false, "jen https");
  assert.equal(isOfficialUrl("https://worldoftanks.eu.evil.com/", PORTAL_HOSTS), false);
  assert.equal(isOfficialUrl("https://evil.wgcdn.co/x.css", PORTAL_HOSTS), false, "jen přesný host");
  assert.equal(isOfficialUrl("nesmysl", PORTAL_HOSTS), false);
  assert.equal(isOfficialUrl(undefined, PORTAL_HOSTS), false);
});

test("current portal stylesheet is discovered from the Tankopedia page", () => {
  const html = '<link rel="stylesheet" href="//eu-wotp.wgcdn.co/static/6.16.0_bbf399/wotp_static/css/main.css">';
  assert.equal(findPortalStylesheet(html), "https://eu-wotp.wgcdn.co/static/6.16.0_bbf399/wotp_static/css/main.css");
  assert.equal(findPortalStylesheet(html.replace("//", "https://")), "https://eu-wotp.wgcdn.co/static/6.16.0_bbf399/wotp_static/css/main.css");
  assert.equal(findPortalStylesheet('<link href="//evil.example/static/1/wotp_static/css/main.css">'), null);
  assert.equal(findPortalStylesheet("<html></html>"), null);
});

test("icon is extracted only for the exact selector", () => {
  const css = `.a{color:red}.currency__gold-x::after{background:url(data:image/svg+xml;base64,${b64("<svg>wrong</svg>")})}`
    + `@media (min-width:1px){.x,.currency__gold::after{background-image:url("data:image/svg+xml;base64,${b64(SVG)}")}}`;
  assert.equal(extractCssSvg(css, ".currency__gold::after"), SVG);
  assert.equal(extractCssSvg(css, ".currency__silver::after"), null);
  assert.equal(extractCssSvg(".currency__gold::after{width:1px}", ".currency__gold::after"), null, "pravidlo bez ikony");
});

test("svg safety: static graphics only", () => {
  assert.equal(isSafeSvg(SVG), true);
  assert.equal(isSafeSvg(`<?xml version="1.0"?>${SVG}`), true);
  assert.equal(isSafeSvg('<svg><use href="#a"/><path fill="url(#g)" d="M0 0"/></svg>'), true, "interní odkazy jsou v pořádku");
  for (const bad of [
    '<svg><script>alert(1)</script></svg>',
    '<svg onload="alert(1)"><path d="M0 0"/></svg>',
    '<svg><image href="https://evil.example/x.png"/></svg>',
    '<svg><use xlink:href="https://evil.example/s.svg#a"/></svg>',
    '<svg><foreignObject><div>x</div></foreignObject></svg>',
    '<svg><path style="fill:url(https://evil.example/x)" d="M0 0"/></svg>',
    '<!DOCTYPE svg [<!ENTITY x "y">]><svg></svg>',
    '<svg><a href="javascript:alert(1)">x</a></svg>',
    '<html><body></body></html>',
    `<svg>${"x".repeat(MAX_SVG_BYTES)}</svg>`,
    "",
    null,
  ]) assert.equal(isSafeSvg(bad), false, String(bad).slice(0, 40));
});
