/**
 * Cíl přesměrování po přihlášení z ?next= – jen interní cesta aplikace.
 * Cokoliv jiného (absolutní URL, protocol-relative "//host", "/\host", prázdné) → "/".
 */
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) {
    return "/";
  }
  return raw;
}
