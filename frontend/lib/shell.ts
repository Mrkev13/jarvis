/**
 * Které stránky běží bez aplikačního rámu (Roadmap 4B). Login není „přihlášená" stránka:
 * žádná navigace, žádný zvonek notifikací (ten by se dotazoval na API a dostával 401).
 */
export const BARE_ROUTES = ["/login"];

export function isBareRoute(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return BARE_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`));
}

/** Id hlavního obsahu – cíl odkazu „Přeskočit na obsah" a fokusu po navigaci z mobilního menu. */
export const MAIN_CONTENT_ID = "main-content";
