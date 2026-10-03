/**
 * Rozhodnutí auth brány (proxy.ts, dříve middleware.ts) – čistá funkce, aby šla otestovat (authGate.test.mjs).
 * Chování beze změny: veřejné cesty projdou; když ověření session selže (síť, 5xx), propustí se (API si ověří
 * samo); platná session nebo vypnutá auth projde; jinak přesměrování na /login?next=<původní cesta>.
 */
import { isPublicPath } from "./publicPaths.ts";

export type SessionCheck =
  | { kind: "ok"; valid?: boolean; authDisabled?: boolean }
  | { kind: "unavailable" };

export type GateDecision = { action: "next" } | { action: "redirect"; location: string };

export function authDecision(pathname: string, search: string, check: SessionCheck | null): GateDecision {
  if (isPublicPath(pathname)) return { action: "next" };
  if (!check || check.kind === "unavailable") return { action: "next" };
  if (check.authDisabled || check.valid) return { action: "next" };
  const next = `${pathname}${search || ""}`;
  return { action: "redirect", location: `/login?next=${encodeURIComponent(next)}` };
}
