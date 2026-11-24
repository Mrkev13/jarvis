/**
 * Frontendový manifest WoW (MRK-127) – čistá data, žádný React (registr lib/modules.ts ho importuje, testy přes
 * node --test). Stránka je modules/wow/WowPage.tsx, data z backendu `/wow` (snapshot Blizzard API).
 */
import type { ModuleUi } from "../../lib/modules.ts";

export const WOW_UI: ModuleUi = {
  nav: { href: "/wow", label: "World of Warcraft", keywords: ["wow", "warcraft", "alt", "alty", "postava", "level", "mount", "sbírka", "achievement"], order: 52, group: "more" },
  searchParams: ["wowchar", "wowwish"],
  searchGroupOrder: 92,
  area: { bg: "bg-yellow-500/10", border: "border-yellow-400/30", text: "text-yellow-200" },
  typeLabels: { wow_character: "WoW postava", wow_wish: "WoW sbírka", wow_collection: "WoW sbírka" },
};
