/**
 * Globální vyhledávání (Roadmap 4D) – deterministické, bez LLM. Stejná pravidla jako backend search_service.py:
 * normalizace (malá písmena, bez diakritiky), skóre přesná shoda > začátek > začátek slova > podřetězec >
 * všechna slova dotazu > ostatní pole. Navigace se hledá lokálně (hned), záznamy přes GET /search.
 * Čisté funkce, testy: search.test.mjs.
 */
import { areaMeta } from "./areas.ts";
import { allowsHref, type ModuleAccess } from "./modules.ts";
import { NAV_PAGES, type NavPage } from "./navigation.ts";

export type SearchResult = {
  id: string;
  type: string;
  title: string;
  subtitle: string;
  area: string | null;
  href: string;
  score: number;
};

export type SearchGroup = { key: string; label: string; results: SearchResult[] };

export const MIN_REMOTE_QUERY = 2;
/** Navigace dostane malý bonus – při stejné shodě je stránka nad záznamem. */
const NAV_BOOST = 5;

/** „Zkouška FYZIKA" → „zkouska fyzika" (zobrazený text se nemění). */
export function normalize(text: string | null | undefined): string {
  return String(text ?? "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

/** Skóre shody (0 = žádná); `query` už normalizovaný. Stejné stupně jako backend. */
export function scoreText(query: string, title: string, extra = ""): number {
  if (!query) return 0;
  const t = normalize(title);
  if (t === query) return 100;
  if (t.startsWith(query)) return 85;
  const words = t.split(" ");
  if (words.some((w) => w.startsWith(query))) return 70;
  if (t.includes(query)) return 55;
  const tokens = query.split(" ");
  const hay = `${t} ${normalize(extra)}`;
  const hayWords = hay.split(" ");
  if (tokens.length > 1 && tokens.every((tok) => hayWords.some((w) => w.startsWith(tok)))) return 45;
  if (hay.includes(query)) return 30;
  return 0;
}

const navResult = (p: NavPage, score: number): SearchResult => ({
  id: `nav:${p.href}`,
  type: "page",
  title: p.label,
  subtitle: "",
  area: p.area,
  href: p.href,
  score,
});

/** Stránky podle dotazu (prázdný dotaz = všechny v pořadí navigace). `pages` = jen dostupné (navPagesFor). */
export function searchNavigation(raw: string, pages: NavPage[] = NAV_PAGES): SearchResult[] {
  const q = normalize(raw);
  if (!q) return pages.map((p) => navResult(p, 0));
  return pages.map((p) => {
    // klíčová slova se hodnotí jako titulek (např. „dashboard"), ale o stupeň níž než skutečný název
    const best = Math.max(scoreText(q, p.label), ...p.keywords.map((k) => Math.max(0, scoreText(q, k) - 10)));
    return best ? navResult(p, best + NAV_BOOST) : null;
  })
    .filter((r): r is SearchResult => r !== null)
    .sort((a, b) => b.score - a.score);
}

const GROUP_ORDER = ["page", "school", "reminders", "work", "finance", "goals", "memory", "wot", "mff"];

function groupKey(r: SearchResult): string {
  return r.type === "page" ? "page" : r.area ?? "other";
}

export function groupLabel(key: string): string {
  return key === "page" ? "Navigace" : key === "recent" ? "Nedávno otevřené" : areaMeta(key).label;
}

/**
 * Skupiny podle oblasti; skupina s nejlepší shodou je první (Enter otevře nejlepší výsledek),
 * při shodě pevné pořadí. Jen neprázdné skupiny, max. `perGroup` řádků.
 */
export function groupResults(results: SearchResult[], perGroup = 6): SearchGroup[] {
  const map = new Map<string, SearchResult[]>();
  for (const r of results) {
    const k = groupKey(r);
    const list = map.get(k) ?? [];
    if (list.length < perGroup) list.push(r);
    map.set(k, list);
  }
  return [...map.entries()]
    .map(([key, list]) => ({ key, label: groupLabel(key), results: list.sort((a, b) => b.score - a.score) }))
    .sort((a, b) => b.results[0].score - a.results[0].score || GROUP_ORDER.indexOf(a.key) - GROUP_ORDER.indexOf(b.key));
}

/**
 * Roadmap 6C: dostupnost modulů jako vstupní filtr (řazení beze změny). Záznamy vypnutého modulu (podle typu)
 * a odkazy na jeho stránky (i ze starších „Nedávno otevřené") se nezobrazí. Backend filtruje stejně –
 * tohle je pojistka pro rozjeté flagy frontendu a backendu.
 */
export function filterAvailable(results: SearchResult[], access: ModuleAccess): SearchResult[] {
  return results.filter((r) => (r.type === "page" || access.allowsEntity(r.type, "search")) && allowsHref(access, r.href));
}

/** Řádky v pořadí zobrazení (pro šipky a Enter). */
export function flatten(groups: SearchGroup[]): SearchResult[] {
  return groups.flatMap((g) => g.results);
}

/** Další index při ↑/↓ (cyklicky; -1 = nic vybráno). */
export function moveSelection(current: number, count: number, direction: 1 | -1): number {
  if (count <= 0) return -1;
  if (current < 0) return direction === 1 ? 0 : count - 1;
  return (current + direction + count) % count;
}

// ---------- nedávno otevřené (jen v prohlížeči, jen stránky a záznamy, ne dotazy) ----------

export const RECENT_KEY = "standa-hub:search-recent";
export const RECENT_LIMIT = 5;

/** Přidá cíl na začátek, bez duplicit (podle href), max. RECENT_LIMIT. */
export function pushRecent(list: SearchResult[], item: SearchResult): SearchResult[] {
  const slim = { ...item, score: 0 };
  return [slim, ...list.filter((r) => r.href !== item.href)].slice(0, RECENT_LIMIT);
}

export function parseRecent(raw: string | null): SearchResult[] {
  try {
    const data = raw ? JSON.parse(raw) : [];
    return Array.isArray(data)
      ? data
          .filter((r) => r && typeof r.href === "string" && r.href.startsWith("/") && typeof r.title === "string")
          .slice(0, RECENT_LIMIT)
      : [];
  } catch {
    return [];
  }
}

/** Ctrl+K / Cmd+K (bez Alt/Shift) – vědomá zkratka aplikace, funguje i ve formulářích. */
export function isSearchShortcut(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }): boolean {
  return (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K");
}

/** Parametry odkazů z vyhledávání (backend search_service: href) → cíl `data-search-target` na stránce. */
export const SEARCH_TARGET_PARAMS = ["subject", "assignment", "exam", "reminder", "session", "transaction", "goal", "memory", "grind", "character", "replay"] as const;

export function searchTargetFromParams(params: { get(name: string): string | null }): string | null {
  for (const key of SEARCH_TARGET_PARAMS) {
    const v = params.get(key);
    if (v && /^\d{1,10}$/.test(v)) return `${key}-${v}`;
  }
  return null;
}
