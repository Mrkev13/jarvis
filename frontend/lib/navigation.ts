/**
 * Stránky aplikace – jeden seznam pro postranní navigaci i globální vyhledávání (Roadmap 4D).
 * `keywords` = další slova, pod kterými stránku najde Ctrl+K (bez diakritiky stačí, normalizuje se).
 * `module` = stránka patří modulu s feature flagem (Roadmap 6C, lib/modules.ts); bez něj = jádro, vždy vidět.
 * `menu: false` = stránka není v hlavní navigaci, ale najde ji Ctrl+K a vedou na ni odkazy (MRK-78: Dnes a Týdenní
 * přehled jsou za kartami Řídicího centra).
 */
import { MODULE_UI, MODULES, type ModuleAccess, type ModuleDef, type ModuleUi } from "./modules.ts";

export type NavPage = { href: string; label: string; area: string | null; keywords: string[]; module?: string; menu?: false };

/** Stránky jádra před stránkami modulů (pořadí v menu). */
const CORE_BEFORE: NavPage[] = [
  { href: "/", label: "Řídicí centrum", area: null, keywords: ["dashboard", "home", "domů", "přehled", "command center"] },
  { href: "/today", label: "Dnes", area: null, keywords: ["today", "dnešek", "dnešní den", "co dnes", "časová osa"], menu: false },
  { href: "/review", label: "Týdenní přehled", area: "review", keywords: ["weekly review", "týden", "review", "shrnutí"], menu: false },
  { href: "/planner", label: "Plánovač", area: null, keywords: ["planner", "plán", "priority", "denní plán"] },
  { href: "/reminders", label: "Připomínky", area: "reminders", keywords: ["reminders", "připomínka", "upozornění", "budík"] },
];

/** Stránky jádra za stránkami modulů. */
const CORE_AFTER: NavPage[] = [
  { href: "/changes", label: "Co se změnilo", area: null, keywords: ["what changed", "změny", "novinky", "od minule", "přehled změn"] },
  { href: "/activity", label: "Aktivita", area: null, keywords: ["activity", "audit", "historie změn", "log"] },
  { href: "/memory", label: "Paměť", area: "memory", keywords: ["memory", "poznámka", "poznámky", "preference"] },
  { href: "/ai", label: "AI asistent", area: "ai", keywords: ["ai", "asistent", "chat", "jarvis", "standa ai"] },
  { href: "/settings", label: "Nastavení", area: null, keywords: ["settings", "nastavení", "moduly", "modul", "zapnout", "vypnout"] },
];

/** MRK-20: stránky modulů z jejich manifestu (lib/modules.ts `MODULE_UI.nav`) – nový modul sem nic nepřidává. */
export function modulePages(modules: ModuleDef[] = MODULES, ui: Record<string, ModuleUi> = MODULE_UI): NavPage[] {
  return modules
    .filter((m) => m.implemented && ui[m.id]?.nav)
    .map((m) => ({ ...ui[m.id].nav!, module: m.id }))
    .sort((a, b) => a.order - b.order)
    .map(({ href, label, keywords, module }) => ({ href, label, area: module, keywords, module }));
}

export const NAV_PAGES: NavPage[] = [...CORE_BEFORE, ...modulePages(), ...CORE_AFTER];

/** Stránky dostupných modulů (navigace, mobilní menu i Ctrl+K) – vypnutý modul nemá žádný odkaz. */
export function navPagesFor(access: ModuleAccess, pages: NavPage[] = NAV_PAGES): NavPage[] {
  return pages.filter((p) => access.allowsOwned(p, "nav"));
}

/** MRK-78: položky hlavní navigace (postranní panel, mobilní menu) – bez stránek s `menu: false`. */
export function menuPagesFor(access: ModuleAccess, pages: NavPage[] = NAV_PAGES): NavPage[] {
  return navPagesFor(access, pages).filter((p) => p.menu !== false);
}
