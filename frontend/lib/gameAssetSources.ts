/**
 * Game Enrichment A – pomocné funkce pro stahovací skript (scripts/fetch-game-assets.mjs): odkud se smí stahovat
 * a jak z oficiálního stylu portálu WoT vytáhnout ikony měn. Čisté funkce bez I/O (testy: gameAssetSources.test.mjs).
 * Aplikace je za běhu nepoužívá – čte jen lokální manifest a soubory.
 */

/** Oficiální portál World of Tanks: stránka (hledání aktuálního stylu) a CDN se stylem. Nic jiného. */
export const PORTAL_HOSTS = ["worldoftanks.eu", "eu-wotp.wgcdn.co"];

/** https URL na přesně povoleném hostu (žádné subdomény navíc, žádné http). */
export function isOfficialUrl(raw: string | null | undefined, hosts: readonly string[]): boolean {
  try {
    const url = new URL(String(raw ?? ""));
    return url.protocol === "https:" && hosts.includes(url.hostname);
  } catch {
    return false;
  }
}

/**
 * Aktuální hlavní styl portálu z HTML stránky Tankopedie (verze v cestě se mění s každou aktualizací portálu).
 * Odkaz je bez protokolu („//eu-wotp.wgcdn.co/static/<verze>/wotp_static/css/main.css") → doplní se https.
 */
export function findPortalStylesheet(html: string): string | null {
  const m = /(?:https:)?\/\/eu-wotp\.wgcdn\.co\/static\/[A-Za-z0-9._-]+\/wotp_static\/css\/main\.css/.exec(html);
  return m ? `https:${m[0].replace(/^https:/, "")}` : null;
}

/**
 * SVG ikona vložená do CSS jako data URI u daného selektoru (portál má ikony měn přímo ve stylu, ne jako soubory).
 * Selektor musí v seznamu selektorů pravidla stát přesně; vrací dekódovaný text SVG, nebo null.
 */
export function extractCssSvg(css: string, selector: string): string | null {
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = rule.exec(css); m; m = rule.exec(css)) {
    const selectors = m[1].split(",").map((s) => s.trim());
    if (!selectors.includes(selector)) continue;
    const data = /url\(\s*["']?data:image\/svg\+xml;base64,([A-Za-z0-9+/=]+)["']?\s*\)/.exec(m[2]);
    if (data) return Buffer.from(data[1], "base64").toString("utf8");
  }
  return null;
}

export const MAX_SVG_BYTES = 64 * 1024;

/**
 * Jen statická, samostatná SVG grafika: žádné skripty, obsluhy událostí, externí odkazy (href / url() mimo „#id"),
 * vložené HTML, DOCTYPE / entity. Ikony z portálu jsou čisté cesty – cokoli jiného se odmítne.
 */
export function isSafeSvg(svg: unknown): boolean {
  if (typeof svg !== "string" || svg.length === 0 || Buffer.byteLength(svg) > MAX_SVG_BYTES) return false;
  const s = svg.trim();
  if (!/^(<\?xml[^>]*\?>\s*)?<svg[\s>]/i.test(s) || !/<\/svg>$/i.test(s)) return false;
  const forbidden = [
    /<script/i,
    /<foreignObject/i,
    /<!DOCTYPE|<!ENTITY/i,
    /\son[a-z]+\s*=/i,
    // odkaz mimo „#id" (uvozovky explicitně – volitelná uvozovka by jinak „#" obešla)
    /(?:xlink:)?href\s*=\s*(?:"\s*(?!#)|'\s*(?!#)|(?!["'#\s]))/i,
    /url\(\s*(?:"\s*(?!#)|'\s*(?!#)|(?!["'#\s]))/i,
    /javascript:/i,
    /<(iframe|object|embed)\b/i,
  ];
  return !forbidden.some((re) => re.test(s));
}
