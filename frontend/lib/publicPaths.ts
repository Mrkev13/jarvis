// Cesty, které auth brána (proxy.ts) pouští bez session (sdílené s testy – proxy.ts je jen importuje).

// Prefixy (cesta i vše pod ní) – dosavadní chování middleware.
const PUBLIC_PREFIXES = ["/login", "/_next", "/favicon.ico", "/api", "/robots.txt", "/sitemap.xml"];

// Phase E: statické soubory PWA bez dat uživatele. Prohlížeč manifest stahuje bez cookies a service worker
// se musí dát načíst i bez platné session – jinak 307 na /login (instalace na plochu / registrace SW selže).
// Jen přesná shoda (žádné /sw.js.map ani /manifest.webmanifest/…).
const PUBLIC_FILES = new Set(["/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png"]);

export function isPublicPath(pathname: string): boolean {
  if (PUBLIC_FILES.has(pathname)) return true;
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}
