/**
 * MRK-138: WoT „hangár" – čistá logika vzhledu (testy: wotHangar.test.mjs). Národ a tier tanku pocházejí z manifestu
 * obrázků (Tankopedie, docs/game-assets.md); bez manifestu se nic nevymýšlí – hangár je jen bez tónování a tieru.
 */
export type NationStyle = { label: string; rgb: string };

/** Tónování pozadí podle národa (tlumené barvy vlajek / kamufláží, ne oficiální grafika). */
export const NATIONS: Record<string, NationStyle> = {
  germany: { label: "Německo", rgb: "150 160 170" },
  ussr: { label: "SSSR", rgb: "200 64 56" },
  usa: { label: "USA", rgb: "70 120 200" },
  uk: { label: "Velká Británie", rgb: "120 140 90" },
  france: { label: "Francie", rgb: "90 130 210" },
  china: { label: "Čína", rgb: "210 70 60" },
  japan: { label: "Japonsko", rgb: "220 90 90" },
  czech: { label: "Československo", rgb: "70 110 190" },
  sweden: { label: "Švédsko", rgb: "230 190 60" },
  poland: { label: "Polsko", rgb: "220 80 90" },
  italy: { label: "Itálie", rgb: "80 160 100" },
  intunion: { label: "Mezinárodní", rgb: "150 120 200" },
};

export function nationStyle(nation: string | null | undefined): NationStyle | null {
  return nation ? NATIONS[nation.toLowerCase()] ?? null : null;
}

const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"];
/** Tier římsky (I–XI); mimo rozsah null. */
export function romanTier(tier: number | null | undefined): string | null {
  return typeof tier === "number" && Number.isInteger(tier) && tier >= 1 && tier <= 11 ? ROMAN[tier] : null;
}

/** Hodnost medaile podle počtu Mek na tanku (síň slávy): 1 = bronz, 2–4 = stříbro, 5+ = zlato. */
export function medalRank(count: number): "bronze" | "silver" | "gold" {
  return count >= 5 ? "gold" : count >= 2 ? "silver" : "bronze";
}

/** Pancéřové pláty XP lišty: 20 plátů, rozsvícené podle průběhu (null = neznámý základ → žádné). */
export function armorPlates(progress: number | null, total = 20): { total: number; lit: number } {
  if (progress === null || !Number.isFinite(progress)) return { total, lit: 0 };
  return { total, lit: Math.max(0, Math.min(total, Math.round((progress / 100) * total))) };
}
