/**
 * Stránky aplikace – jeden seznam pro postranní navigaci i globální vyhledávání (Roadmap 4D).
 * `keywords` = další slova, pod kterými stránku najde Ctrl+K (bez diakritiky stačí, normalizuje se).
 * `module` = stránka patří modulu s feature flagem (Roadmap 6C, lib/modules.ts); bez něj = jádro, vždy vidět.
 */
import type { ModuleAccess } from "./modules.ts";

export type NavPage = { href: string; label: string; area: string | null; keywords: string[]; module?: string };

export const NAV_PAGES: NavPage[] = [
  { href: "/", label: "Řídicí centrum", area: null, keywords: ["dashboard", "home", "domů", "přehled", "command center"] },
  { href: "/today", label: "Dnes", area: null, keywords: ["today", "dnešek", "dnešní den", "co dnes", "časová osa"] },
  { href: "/review", label: "Týdenní přehled", area: "review", keywords: ["weekly review", "týden", "review", "shrnutí"] },
  { href: "/planner", label: "Plánovač", area: null, keywords: ["planner", "plán", "priority", "denní plán"] },
  { href: "/reminders", label: "Připomínky", area: "reminders", keywords: ["reminders", "připomínka", "upozornění", "budík"] },
  { href: "/goals", label: "Cíle", area: "goals", keywords: ["goals", "goal", "cíl", "progres"], module: "goals" },
  { href: "/school", label: "Škola", area: "school", keywords: ["school", "úkol", "úkoly", "zkouška", "zkoušky", "předmět", "předměty", "termín", "termíny"], module: "school" },
  { href: "/work", label: "Práce", area: "work", keywords: ["work", "hodiny", "výdělek", "projekty"], module: "work" },
  { href: "/finance", label: "Finance", area: "finance", keywords: ["peníze", "transakce", "výdaj", "výdaje", "příjem", "příjmy", "bilance"], module: "finance" },
  { href: "/wot", label: "World of Tanks", area: "wot", keywords: ["wot", "tanky", "grind", "tank"], module: "wot" },
  { href: "/mff", label: "Marvel Future Fight", area: "mff", keywords: ["mff", "marvel", "future fight", "postava", "postavy"], module: "mff" },
  { href: "/activity", label: "Aktivita", area: null, keywords: ["activity", "audit", "historie změn", "log"] },
  { href: "/memory", label: "Paměť", area: "memory", keywords: ["memory", "poznámka", "poznámky", "preference"] },
  { href: "/ai", label: "AI asistent", area: "ai", keywords: ["ai", "asistent", "chat", "jarvis", "standa ai"] },
];

/** Stránky dostupných modulů (navigace, mobilní menu i Ctrl+K) – vypnutý modul nemá žádný odkaz. */
export function navPagesFor(access: ModuleAccess, pages: NavPage[] = NAV_PAGES): NavPage[] {
  return pages.filter((p) => access.allowsOwned(p, "nav"));
}
