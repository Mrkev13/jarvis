// MRK-121: herní obrázky z adresáře mimo build – povolené cesty, hranice kořene, hlavičky.
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";

import { assetHeaders, assetRelativePath, gameAssetsRoot, MAX_ASSET_BYTES, readGameAsset } from "./gameAssetFiles.ts";

let base, root;
before(() => {
  base = mkdtempSync(path.join(tmpdir(), "game-assets-"));
  root = path.join(base, "assets");
  mkdirSync(path.join(root, "wot", "tanks"), { recursive: true });
  mkdirSync(path.join(root, "wot", "resources"), { recursive: true });
  writeFileSync(path.join(root, "manifest.json"), '{"version":2}');
  writeFileSync(path.join(root, "wot", "tanks", "7169.png"), "PNG");
  writeFileSync(path.join(root, "wot", "resources", "gold.svg"), "<svg/>");
  writeFileSync(path.join(root, "wot", "tanks", "huge.png"), Buffer.alloc(MAX_ASSET_BYTES + 1));
  writeFileSync(path.join(base, "secret.png"), "SECRET");
  symlinkSync(path.join(base, "secret.png"), path.join(root, "wot", "tanks", "escape.png"));
  mkdirSync(path.join(root, "wot", "tanks", "dir.png"));
});
after(() => rmSync(base, { recursive: true, force: true }));

test("kořen: GAME_ASSETS_DIR jen jako absolutní cesta, jinak public/game-assets", () => {
  assert.equal(gameAssetsRoot({ GAME_ASSETS_DIR: "/data/game-assets" }, "/app"), "/data/game-assets");
  assert.equal(gameAssetsRoot({ GAME_ASSETS_DIR: "relative/dir" }, "/app"), path.join("/app", "public", "game-assets"));
  assert.equal(gameAssetsRoot({}, "/app"), path.join("/app", "public", "game-assets"));
});

test("povolené cesty: manifest a obrázky ve tvaru safeAssetFile", () => {
  assert.equal(assetRelativePath(["manifest.json"]), "manifest.json");
  assert.equal(assetRelativePath(["wot", "tanks", "7169.png"]), "wot/tanks/7169.png");
  for (const bad of [[], ["..", "secret.png"], ["wot", "..", "manifest.json"], ["wot", "tanks", "x.exe"], ["README.md"],
    ["wot", "Tanks", "1.png"], ["wot", "tanks/../../x.png"], ["wot", "tanks", "a\0.png"], ["wot", "", "1.png"]]) {
    assert.equal(assetRelativePath(bad), null, JSON.stringify(bad));
  }
});

test("čte soubor uvnitř kořene s typem a soukromou cache", async () => {
  const png = await readGameAsset(root, ["wot", "tanks", "7169.png"]);
  assert.equal(png.body.toString(), "PNG");
  assert.equal(png.headers["Content-Type"], "image/png");
  assert.equal(png.headers["X-Content-Type-Options"], "nosniff");
  assert.match(png.headers["Cache-Control"], /^private/);
  const manifest = await readGameAsset(root, ["manifest.json"]);
  assert.equal(manifest.headers["Content-Type"], "application/json; charset=utf-8");
  assert.equal(manifest.headers["Cache-Control"], "private, no-cache");
});

test("SVG jen se sandbox CSP", async () => {
  const svg = await readGameAsset(root, ["wot", "resources", "gold.svg"]);
  assert.equal(svg.headers["Content-Type"], "image/svg+xml");
  assert.match(svg.headers["Content-Security-Policy"], /sandbox/);
  assert.equal(assetHeaders("wot/tanks/1.png")["Content-Security-Policy"], undefined);
});

test("nic mimo kořen ani nečekaný soubor: symlink ven, adresář, moc velký, chybějící, chybějící kořen", async () => {
  assert.equal(await readGameAsset(root, ["wot", "tanks", "escape.png"]), null);
  assert.equal(await readGameAsset(root, ["wot", "tanks", "dir.png"]), null);
  assert.equal(await readGameAsset(root, ["wot", "tanks", "huge.png"]), null);
  assert.equal(await readGameAsset(root, ["wot", "tanks", "1.png"]), null);
  assert.equal(await readGameAsset(path.join(base, "missing"), ["manifest.json"]), null);
});
