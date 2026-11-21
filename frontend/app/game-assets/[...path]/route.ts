// MRK-121: herní obrázky z GAME_ASSETS_DIR (Ubuntu: read-only volume) – logika a důvod v lib/gameAssetFiles.ts.
// Za přihlášením stejně jako zbytek aplikace (proxy.ts). Soubory z public/game-assets při buildu mají přednost.
import { gameAssetsRoot, readGameAsset } from "@/lib/gameAssetFiles";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const NOT_FOUND = () => new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });

async function serve(params: Promise<{ path: string[] }>, withBody: boolean): Promise<Response> {
  const asset = await readGameAsset(gameAssetsRoot(), (await params).path);
  if (!asset) return NOT_FOUND();
  return new Response(withBody ? new Uint8Array(asset.body) : null, {
    status: 200,
    headers: { ...asset.headers, "Content-Length": String(asset.body.length) },
  });
}

export async function GET(_request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return serve(params, true);
}

export async function HEAD(_request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return serve(params, false);
}
