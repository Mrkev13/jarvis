/**
 * Moduly a jejich feature flagy (Roadmap 6C) – čistá logika bez Reactu a bez `process.env` (testy: modules.test.mjs).
 *
 * Zrcadlo `backend/module_registry.py` (paritu hlídá backend test test_module_registry.py): stejná id, výchozí
 * stav, implementace, schopnosti, typy záznamů a druhy Rychlého přidání. Hodnoty flagů čte JEDINĚ
 * `lib/moduleConfig.ts`; komponenty se ptají přes `ModuleAccess`, nikdy přímo na prostředí.
 *
 * Modul je DOSTUPNÝ = `implemented` && flag. Flag neimplementovaného modulu nic neodkryje.
 * Co nepatří žádnému modulu (Řídicí centrum, Dnes, Plánovač, Připomínky, Paměť, AI…), je jádro → vždy dostupné.
 * Flagy řídí dostupnost, ne oprávnění (auth řeší proxy.ts + backend).
 */

export const CAPABILITIES = ["nav", "search", "quick_add", "today", "dashboard", "ai_context"] as const;
export type Capability = (typeof CAPABILITIES)[number];

export interface ModuleDef {
  id: string;
  label: string;
  defaultEnabled: boolean;
  implemented: boolean;
  capabilities: Capability[];
  /** Typy záznamů (SearchResult.type, ref „<typ>:<id>"). */
  entityTypes: string[];
  /** Stránky modulu (přesná cesta nebo vše pod ní). */
  routes: string[];
  quickAddKinds: string[];
}

/** Budoucí modul: zatím bez stránek i schopností, výchozí vypnutý (nehotová stránka se nikdy neukáže). */
function planned(id: string, label: string): ModuleDef {
  return { id, label, defaultEnabled: false, implemented: false, capabilities: [], entityTypes: [], routes: [], quickAddKinds: [] };
}

// Jeden řádek = jeden modul (backend test parity čte tento tvar).
export const MODULES: ModuleDef[] = [
  { id: "school", label: "Škola", defaultEnabled: true, implemented: true, capabilities: ["nav", "search", "quick_add", "today", "dashboard", "ai_context"], entityTypes: ["subject", "assignment", "exam"], routes: ["/school"], quickAddKinds: ["exam", "assignment"] },
  { id: "work", label: "Práce", defaultEnabled: true, implemented: true, capabilities: ["nav", "search", "quick_add", "today", "dashboard", "ai_context"], entityTypes: ["work_session"], routes: ["/work"], quickAddKinds: ["work"] },
  { id: "finance", label: "Finance", defaultEnabled: true, implemented: true, capabilities: ["nav", "search", "quick_add", "today", "dashboard", "ai_context"], entityTypes: ["transaction"], routes: ["/finance"], quickAddKinds: ["finance"] },
  { id: "goals", label: "Cíle", defaultEnabled: true, implemented: true, capabilities: ["nav", "search", "today", "dashboard", "ai_context"], entityTypes: ["goal"], routes: ["/goals"], quickAddKinds: [] },
  { id: "wot", label: "World of Tanks", defaultEnabled: true, implemented: true, capabilities: ["nav", "search", "dashboard", "ai_context"], entityTypes: ["wot_grind", "wot_resource", "wot_replay"], routes: ["/wot"], quickAddKinds: [] },
  { id: "mff", label: "Marvel Future Fight", defaultEnabled: true, implemented: true, capabilities: ["nav", "search", "dashboard", "ai_context"], entityTypes: ["mff_character"], routes: ["/mff"], quickAddKinds: [] },
  planned("food", "Jídlo"),
  planned("fitness", "Fitness"),
  planned("habits", "Návyky"),
  planned("projects", "Projekty"),
  planned("knowledge", "Znalosti"),
  planned("car", "Auto"),
  planned("travel", "Cestování"),
  planned("entertainment", "Zábava"),
];

export type ModuleFlags = Record<string, boolean>;
export type FlagEnv = Record<string, string | undefined>;

/** Název proměnné prostředí frontendu (build-time, viditelná v prohlížeči – flagy nejsou tajemství). */
export function flagEnvName(id: string): string {
  return `NEXT_PUBLIC_MODULE_${id.toUpperCase()}_ENABLED`;
}

const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);
const FALSE_VALUES = new Set(["0", "false", "no", "off"]);

/** Stejná pravidla jako backend env_config.parse_flag: prázdné / nesmysl = výchozí hodnota. */
export function parseFlag(raw: string | undefined | null, fallback: boolean): boolean {
  const value = String(raw ?? "").trim().toLowerCase();
  if (TRUE_VALUES.has(value)) return true;
  if (FALSE_VALUES.has(value)) return false;
  return fallback;
}

export function resolveModuleFlags(env: FlagEnv, modules: ModuleDef[] = MODULES): ModuleFlags {
  return Object.fromEntries(modules.map((m) => [m.id, parseFlag(env[flagEnvName(m.id)], m.defaultEnabled)]));
}

function underRoute(pathname: string, route: string): boolean {
  return pathname === route || pathname.startsWith(`${route}/`);
}

/** Cokoli, co může patřit modulu (stránka navigace, widget, rychlá akce…). Bez `module` = jádro. */
export interface ModuleOwned {
  module?: string;
}

export interface ModuleAccess {
  isAvailable(id: string): boolean;
  /** Kanonická odpověď: smí modul `id` přispívat do `capability`? Neznámý modul = ne. */
  allows(id: string, capability: Capability): boolean;
  /** Položka bez modulu (jádro) = ano; jinak `allows(module, capability)`. */
  allowsOwned(item: ModuleOwned, capability: Capability): boolean;
  /** Widget / prvek, který patří více modulům: dostupný, když aspoň jeden z nich smí (prázdný seznam = jádro). */
  allowsAny(ids: readonly string[] | undefined, capability: Capability): boolean;
  allowsEntity(type: string | null | undefined, capability: Capability): boolean;
  allowsQuickAddKind(kind: string): boolean;
  moduleForPath(pathname: string): ModuleDef | null;
  /** Cesta stránky, kterou smí aplikace otevřít (cesta vypnutého modulu = ne). */
  allowsPath(pathname: string): boolean;
}

/**
 * Přístup k modulům pro jednu sadu flagů. Budoucí uživatelské preference: předat flagy už zúžené volbou
 * uživatele (`{...appFlags, food: appFlags.food && userPrefs.food}`) – uživatel smí modul jen vypnout.
 */
export function createModuleAccess(flags: ModuleFlags, modules: ModuleDef[] = MODULES): ModuleAccess {
  const byId = new Map(modules.map((m) => [m.id, m]));
  const byEntity = new Map(modules.flatMap((m) => m.entityTypes.map((t) => [t, m] as const)));
  const byKind = new Map(modules.flatMap((m) => m.quickAddKinds.map((k) => [k, m] as const)));

  const isAvailable = (id: string) => {
    const m = byId.get(id);
    return Boolean(m && m.implemented && (flags[m.id] ?? m.defaultEnabled));
  };
  const allows = (id: string, capability: Capability) => {
    const m = byId.get(id);
    return Boolean(m && m.capabilities.includes(capability) && isAvailable(m.id));
  };
  const moduleForPath = (pathname: string) => modules.find((m) => m.routes.some((r) => underRoute(pathname, r))) ?? null;

  return {
    isAvailable,
    allows,
    allowsOwned: (item, capability) => !item.module || allows(item.module, capability),
    allowsAny: (ids, capability) => !ids?.length || ids.some((id) => allows(id, capability)),
    allowsEntity: (type, capability) => {
      const owner = byEntity.get(type ?? "");
      return !owner || allows(owner.id, capability);
    },
    allowsQuickAddKind: (kind) => {
      const owner = byKind.get(kind);
      return !owner || allows(owner.id, "quick_add");
    },
    moduleForPath,
    allowsPath: (pathname) => {
      const owner = moduleForPath(pathname);
      return !owner || isAvailable(owner.id);
    },
  };
}

/** Odkaz (např. z „Nedávno otevřené") vede jen na dostupnou stránku; query/hash se ignoruje. */
export function allowsHref(access: ModuleAccess, href: string): boolean {
  return access.allowsPath(href.split(/[?#]/, 1)[0] || "/");
}
