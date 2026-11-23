/**
 * MRK-81: návrhy otázek pro Jarvise – statické a deterministické (žádné LLM). Ukazují se v prázdném chatu (/ai) a jako
 * „Zeptej se Jarvise" na stránkách modulů. Návrh vypnutého modulu se neukáže; Finance nikdy (MRK-60 – finance do AI
 * nejde). Každý `prompt` musí routing backendu poslat do `area` (backend/tests/test_ai_suggestions.py čte tento soubor).
 */
import type { ModuleAccess } from "./modules.ts";

export type SuggestionSurface = "ai" | "school" | "goals" | "wot" | "habits";

export type AiSuggestion = {
  prompt: string;
  /** Modul, kterému návrh patří (null = jádro: připomínky, plán dne). */
  module: string | null;
  /** Oblast, kterou routing pro dotaz musí vybrat (context_service.classify_areas). */
  area: string;
  surfaces: SuggestionSurface[];
};

export const AI_SUGGESTIONS: AiSuggestion[] = [
  { prompt: "Co mám dnes dělat?", module: null, area: "reminders", surfaces: ["ai"] },
  { prompt: "Co mě tento týden čeká ve škole?", module: "school", area: "school", surfaces: ["ai", "school"] },
  { prompt: "Kdy mám nejbližší zkoušku?", module: "school", area: "school", surfaces: ["school"] },
  { prompt: "Jaké mám otevřené úkoly do školy?", module: "school", area: "school", surfaces: ["school"] },
  { prompt: "Najdi v materiálech k předmětu část o tématu", module: "school", area: "school_materials", surfaces: ["school"] },
  { prompt: "Jak jsem na tom s cíli?", module: "goals", area: "goals", surfaces: ["ai", "goals"] },
  { prompt: "Který cíl mi teď nejvíc zaostává?", module: "goals", area: "goals", surfaces: ["goals"] },
  { prompt: "Kolik mi chybí do dalšího Mka?", module: "wot", area: "wot", surfaces: ["ai", "wot"] },
  { prompt: "Co mám ve WoT rozjeté za grindy?", module: "wot", area: "wot", surfaces: ["wot"] },
  { prompt: "Jak mi jdou návyky tento týden?", module: "habits", area: "habits", surfaces: ["ai", "habits"] },
  { prompt: "Jaké mám dnes události v kalendáři?", module: "calendar", area: "calendar", surfaces: ["ai"] },
  { prompt: "Jaké připomínky mě dnes čekají?", module: null, area: "reminders", surfaces: ["ai"] },
];

/** Moduly, jejichž návrhy se nikdy neukážou (MRK-60: finance do AI nejde). */
const NEVER = new Set(["finance"]);

/** Návrhy pro plochu – jen moduly, které smí do AI (`ai_context`), nejvýš `limit`. */
export function suggestionsFor(surface: SuggestionSurface, access: ModuleAccess, limit = 6): AiSuggestion[] {
  return AI_SUGGESTIONS.filter(
    (s) => s.surfaces.includes(surface) && (s.module === null || (!NEVER.has(s.module) && access.allows(s.module, "ai_context"))),
  ).slice(0, limit);
}

/** Odkaz do chatu s předvyplněným dotazem (neodesílá se sám). */
export function askHref(prompt: string): string {
  return `/ai?ask=${encodeURIComponent(prompt)}`;
}

/** Předvyplněný dotaz z `?ask=` (ořez, max. 300 znaků; prázdný = null). */
export function askFromSearch(search: string): string | null {
  const raw = new URLSearchParams(search).get("ask");
  const text = raw?.trim().slice(0, 300) ?? "";
  return text ? text : null;
}
