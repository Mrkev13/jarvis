import { NextRequest, NextResponse } from "next/server";

import { isPublicPath } from "./lib/publicPaths";

const AUTH_COOKIE_NAME = process.env.AUTH_COOKIE_NAME || "standa_hub_session";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const cookie = req.cookies.get(AUTH_COOKIE_NAME);

  // Pokud vůbec není cookie, zkus ověření. Middleware volá BE /auth/session/validate.
  try {
    const validateRes = await fetch(
      `${API_URL.replace(/\/$/, "")}/auth/session/validate`,
      {
        method: "GET",
        headers: cookie
          ? { Cookie: `${AUTH_COOKIE_NAME}=${cookie.value}` }
          : {},
        // Next middleware fetch cache: DONT STORE:
        cache: "no-store",
      } as RequestInit
    );

    if (!validateRes.ok) {
      // Auth endpoint selhal. Snažíme se být lenient. Nechej projít (zobrazení stránky, API si dořeší).
      return NextResponse.next();
    }

    const body = (await validateRes.json()) as {
      valid?: boolean;
      auth_disabled?: boolean;
    };

    if (body.auth_disabled || body.valid) {
      return NextResponse.next();
    }

    // Invalid → redirect /login
    const target = new URL("/login", req.url);
    const nextParam = `${pathname}${search || ""}`;
    target.searchParams.set("next", nextParam);
    return NextResponse.redirect(target);
  } catch {
    // Fetch selhal: lenient, pusť dál (API si ověří samo).
    return NextResponse.next();
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
