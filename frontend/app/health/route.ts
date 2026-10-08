import { productionHealth } from "@/lib/productionHealth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const result = await productionHealth(process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000");
  return Response.json(result.body, { status: result.code, headers: { "Cache-Control": "no-store" } });
}
