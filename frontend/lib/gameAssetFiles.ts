/**
 * MRK-121: herní obrázky z adresáře mimo build (Ubuntu: read-only volume, GAME_ASSETS_DIR).
 *
 * Proč route handler a ne public/: `next start` (Next 16) servíruje jen soubory, které byly v public/ při buildu –
 * soubor přidaný později (i do připojeného volume, i před startem serveru) vrací 404. Ověřeno na 16.3.4.
 * Soubory, které v public/game-assets při buildu jsou (lokální vývoj se scripts/fetch-game-assets.mjs), mají dál
 * přednost; tenhle handler obslouží jen ty ostatní.
 *
 * Bezpečnost: jen manifest.json a cesty, které projdou safeAssetFile (malá písmena, číslice, podtržítka, žádné „..",
 * jen obrázkové přípony); skutečná cesta (po symlinkách) musí zůstat uvnitř kořene; jen běžné soubory do 5 MB.
 * SVG s CSP sandboxem a nosniff. Cokoli jiného = 404 (UI pak ukáže záložní monogram, jako dnes).
 */
import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";

import { safeAssetFile } from "./gameAssets.ts";

export const MAX_ASSET_BYTES = 5 * 1024 * 1024;

const CONTENT_TYPES: Record<string, string> = {
  ".png": "image/png",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
};

/** Kořen obrázků: GAME_ASSETS_DIR (absolutní cesta), jinak public/game-assets v pracovním adresáři aplikace. */
export function gameAssetsRoot(env: Record<string, string | undefined> = process.env, cwd = process.cwd()): string {
  const configured = env.GAME_ASSETS_DIR?.trim();
  if (configured && path.isAbsolute(configured)) return configured;
  return path.join(/*turbopackIgnore: true*/ cwd, "public", "game-assets");
}

/** Relativní cesta z URL segmentů, nebo null pro cokoli mimo povolené tvary. */
export function assetRelativePath(segments: readonly string[]): string | null {
  if (!segments.length || segments.some((s) => !s || s.includes("/") || s.includes("\\") || s.includes("\0"))) return null;
  const rel = segments.join("/");
  if (rel === "manifest.json") return rel;
  return safeAssetFile(rel);
}

export type AssetFile = { body: Buffer; headers: Record<string, string> };

export function assetHeaders(rel: string): Record<string, string> {
  const ext = path.extname(rel).toLowerCase();
  const headers: Record<string, string> = {
    "Content-Type": CONTENT_TYPES[ext] ?? "application/octet-stream",
    "X-Content-Type-Options": "nosniff",
    // za přihlášením (proxy.ts) → jen soukromá cache; manifest se po stažení nových obrázků mění
    "Cache-Control": rel === "manifest.json" ? "private, no-cache" : "private, max-age=86400",
  };
  if (ext === ".svg") headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox";
  return headers;
}

/** Načte povolený soubor uvnitř kořene, jinak null (neexistuje, mimo kořen, symlink ven, adresář, moc velký). */
export async function readGameAsset(root: string, segments: readonly string[]): Promise<AssetFile | null> {
  const rel = assetRelativePath(segments);
  if (!rel) return null;
  try {
    // runtime adresář mimo build (volume) – Turbopack ho nemá trasovat do výstupu
    const realRoot = await realpath(/*turbopackIgnore: true*/ root);
    const real = await realpath(path.join(/*turbopackIgnore: true*/ realRoot, rel));
    if (!real.startsWith(realRoot + path.sep)) return null;
    const info = await stat(/*turbopackIgnore: true*/ real);
    if (!info.isFile() || info.size > MAX_ASSET_BYTES) return null;
    return { body: await readFile(/*turbopackIgnore: true*/ real), headers: assetHeaders(rel) };
  } catch {
    return null;
  }
}
