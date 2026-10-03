import { NextRequest, NextResponse } from "next/server";

import { authDecision, type SessionCheck } from "./lib/authGate";
import { isPublicPath } from "./lib/publicPaths";

// Next.js 16: soubor `middleware` je přejmenovaný na `proxy` (běží v Node.js runtime). Chování beze změny –
// rozhodnutí je v lib/authGate.ts (testy authGate.test.mjs).
const AUTH_COOKIE_NAME = process.env.AUTH_COOKIE_NAME || "standa_hub_session";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function checkSession(req: NextRequest): Promise<SessionCheck> {
  const cookie = req.cookies.get(AUTH_COOKIE_NAME);
  try {
    const res = await fetch(`${API_URL.replace(/\/$/, "")}/auth/session/validate`, {
      method: "GET",
      headers: cookie ? { Cookie: `${AUTH_COOKIE_NAME}=${cookie.value}` } : {},
      cache: "no-store",
    });
    // Auth endpoint selhal → lenient (stránka se zobrazí, API si ověří samo).
    if (!res.ok) return { kind: "unavailable" };
    const body = (await res.json()) as { valid?: boolean; auth_disabled?: boolean };
    return { kind: "ok", valid: body.valid, authDisabled: body.auth_disabled };
  } catch {
    return { kind: "unavailable" };
  }
}

export async function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();
  const decision = authDecision(pathname, search, await checkSession(req));
  return decision.action === "redirect" ? NextResponse.redirect(new URL(decision.location, req.url)) : NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
