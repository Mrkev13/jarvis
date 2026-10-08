/**
 * MRK-18 A2: runtime stav modulů z GET /modules – čistá logika bez Reactu (testy: moduleRuntime.test.mjs).
 *
 * Zdroj pravdy je backend (prostředí > uložená volba > manifest). Frontend NEČTE žádné build-time flagy:
 * do `createModuleAccess` předává `enabled` z odpovědi; `implemented` a schopnosti hlídá dál `lib/modules.ts`.
 * Dokud stav neznáme (první načtení bez cache) nebo ho nejde načíst, je přístup KONZERVATIVNÍ: dostupné je jen
 * jádro (navigace bez modulů, stránky modulů ukážou načítání/chybu, nikdy obsah vypnutého modulu).
 */
import { createModuleAccess, MODULES, type ModuleAccess, type ModuleFlags } from "./modules.ts";

export type ModuleSource = "env" | "db" | "default";

export interface RuntimeModule {
  id: string;
  label: string;
  available: boolean;
  enabled: boolean;
  source: ModuleSource;
  /** Vynuceno prostředím serveru → Nastavení ho nesmí měnit (PUT vrací 409). */
  locked: boolean;
  implemented: boolean;
  default_enabled: boolean;
  depends_on: string[];
  capabilities: string[];
}

export type ModuleStatus = "unknown" | "ready" | "error";

export interface ModuleSnapshot {
  status: ModuleStatus;
  modules: RuntimeModule[] | null;
}

export const MODULES_CACHE_KEY = "standa-hub:modules:v1";
export const UNKNOWN_SNAPSHOT: ModuleSnapshot = Object.freeze({ status: "unknown", modules: null }) as ModuleSnapshot;

const SOURCES = new Set<ModuleSource>(["env", "db", "default"]);

function parseModule(raw: unknown): RuntimeModule | null {
  if (!raw || typeof raw !== "object") return null;
  const m = raw as Record<string, unknown>;
  const bools = ["available", "enabled", "locked", "implemented", "default_enabled"] as const;
  if (typeof m.id !== "string" || typeof m.label !== "string" || !bools.every((k) => typeof m[k] === "boolean")) return null;
  if (typeof m.source !== "string" || !SOURCES.has(m.source as ModuleSource)) return null;
  const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  return {
    id: m.id,
    label: m.label,
    available: m.available as boolean,
    enabled: m.enabled as boolean,
    source: m.source as ModuleSource,
    locked: m.locked as boolean,
    implemented: m.implemented as boolean,
    default_enabled: m.default_enabled as boolean,
    depends_on: strings(m.depends_on),
    capabilities: strings(m.capabilities),
  };
}

/** Odpověď GET /modules (nebo cache) → seznam modulů; cokoli neplatného = `null` (konzervativní režim). */
export function parseModules(body: unknown): RuntimeModule[] | null {
  const list = body && typeof body === "object" ? (body as { modules?: unknown }).modules : undefined;
  if (!Array.isArray(list)) return null;
  const parsed = list.map(parseModule);
  return parsed.every((m): m is RuntimeModule => m !== null) ? parsed : null;
}

export function parseCachedModules(raw: string | null): RuntimeModule[] | null {
  if (!raw) return null;
  try {
    return parseModules(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function serializeModules(modules: RuntimeModule[]): string {
  return JSON.stringify({ modules });
}

/**
 * Flagy pro `createModuleAccess`: JEN z runtime odpovědi. Modul, o kterém server nic neřekl (nebo stav neznáme),
 * je vypnutý – nikdy se nepoužije výchozí hodnota manifestu frontendu.
 */
export function flagsFromRuntime(modules: RuntimeModule[] | null): ModuleFlags {
  const enabled = new Map((modules ?? []).map((m) => [m.id, m.enabled]));
  return Object.fromEntries(MODULES.map((m) => [m.id, enabled.get(m.id) ?? false]));
}

export function accessFor(snapshot: ModuleSnapshot): ModuleAccess {
  return createModuleAccess(flagsFromRuntime(snapshot.modules));
}

export type RouteDecision = "allow" | "loading" | "unavailable" | "error";

/** Smí se stránka vykreslit? Cizí (jádro) ano vždy; stránka modulu jen se známým stavem. */
export function routeDecision(snapshot: ModuleSnapshot, access: ModuleAccess, pathname: string): RouteDecision {
  if (!access.moduleForPath(pathname)) return "allow";
  if (!snapshot.modules) return snapshot.status === "error" ? "error" : "loading";
  return access.allowsPath(pathname) ? "allow" : "unavailable";
}

/** Moduly, které má smysl ukázat v Nastavení (hotové; plánované nejdou zapnout). */
export function settingsModules(modules: RuntimeModule[] | null): RuntimeModule[] {
  return (modules ?? []).filter((m) => m.implemented);
}
