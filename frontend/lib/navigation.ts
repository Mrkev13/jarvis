/**
 * Stránky aplikace – jeden seznam pro postranní navigaci i globální vyhledávání (Roadmap 4D).
 * `keywords` = další slova, pod kterými stránku najde Ctrl+K (bez diakritiky stačí, normalizuje se).
 */
export type NavPage = { href: string; label: string; area: string | null; keywords: string[] };

export const NAV_PAGES: NavPage[] = [
  { href: "/", label: "Řídicí centrum", area: null, keywords: ["dashboard", "home", "domů", "přehled", "command center"] },
  { href: "/today", label: "Dnes", area: null, keywords: ["today", "dnešek", "dnešní den", "co dnes", "časová osa"] },
  { href: "/review", label: "Týdenní přehled", area: "review", keywords: ["weekly review", "týden", "review", "shrnutí"] },
  { href: "/planner", label: "Plánovač", area: null, keywords: ["planner", "plán", "priority", "denní plán"] },
  { href: "/reminders", label: "Připomínky", area: "reminders", keywords: ["reminders", "připomínka", "upozornění", "budík"] },
  { href: "/goals", label: "Cíle", area: "goals", keywords: ["goals", "goal", "cíl", "progres"] },
  { href: "/school", label: "Škola", area: "school", keywords: ["school", "úkol", "úkoly", "zkouška", "zkoušky", "předmět", "předměty", "termín", "termíny"] },
  { href: "/work", label: "Práce", area: "work", keywords: ["work", "hodiny", "výdělek", "projekty"] },
  { href: "/finance", label: "Finance", area: "finance", keywords: ["peníze", "transakce", "výdaj", "výdaje", "příjem", "příjmy", "bilance"] },
  { href: "/wot", label: "World of Tanks", area: "wot", keywords: ["wot", "tanky", "grind", "tank"] },
  { href: "/mff", label: "Marvel Future Fight", area: "mff", keywords: ["mff", "marvel", "future fight", "postava", "postavy"] },
  { href: "/activity", label: "Aktivita", area: null, keywords: ["activity", "audit", "historie změn", "log"] },
  { href: "/memory", label: "Paměť", area: "memory", keywords: ["memory", "poznámka", "poznámky", "preference"] },
  { href: "/ai", label: "AI asistent", area: "ai", keywords: ["ai", "asistent", "chat", "jarvis", "standa ai"] },
];
