/**
 * MRK-153: statistiky WoT po bitvách – typy odpovědi `GET /wot/stats?period=…` a čisté funkce pro grafy
 * (testy: wotStats.test.mjs). Data počítá backend (wot_stats_service.py); tady jen měřítka, cesty a popisky.
 */
export type WotStatsPeriod = "today" | "3d" | "week" | "month" | "half" | "all";
export type WotSummary = {
  battles: number; wins: number; win_rate: number | null; avg_damage: number | null; avg_frags: number | null;
  avg_xp: number | null; survival: number | null;
};
export type WotTankStat = WotSummary & { tank_id: number; name: string; tier: number | null; tag: string | null };
export type WotDaily = WotSummary & { date: string };
export type WotPoint = { at: string; value: number };
export type WotStats = {
  period: WotStatsPeriod; label: string; periods: { key: WotStatsPeriod; label: string }[];
  from: string | null; to: string; data_since: string | null; partial: boolean;
  summary: WotSummary; best_tank: WotTankStat | null; tanks: WotTankStat[]; daily: WotDaily[];
  rating: WotPoint[]; rating_now: number | null; rating_change: number | null;
  resources: Record<"credits" | "gold" | "free_xp" | "bonds", WotPoint[]>;
};

export const PERIOD_OPTIONS: { value: WotStatsPeriod; label: string }[] = [
  { value: "today", label: "Dnes" },
  { value: "3d", label: "3 dny" },
  { value: "week", label: "Týden" },
  { value: "month", label: "Měsíc" },
  { value: "half", label: "Půl roku" },
  { value: "all", label: "Celkově" },
];

/** Jedna řada = jedna barva (dataviz paleta, validováno na tmavém povrchu #050911). */
export const SERIES_COLOR = "#d28e05";

/** „Hezké“ dělení osy: 3–5 značek po 1 / 2 / 5 × 10^n. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const start = Math.floor(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) out.push(Math.round(v / step) * step);
  return out;
}

export type Plot = { w: number; h: number; l: number; r: number; t: number; b: number };

/** Body časové řady do souřadnic SVG. Jeden bod → vodorovná čára přes celou šířku (stav beze změny). */
export function linePoints(points: WotPoint[], plot: Plot, x0: number, x1: number, yTicks: number[]) {
  const yMin = yTicks[0];
  const yMax = yTicks[yTicks.length - 1];
  const sx = (t: number) => (x1 === x0 ? plot.l : plot.l + ((t - x0) / (x1 - x0)) * (plot.w - plot.l - plot.r));
  const sy = (v: number) => plot.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (plot.h - plot.t - plot.b);
  const pts = points.map((p) => ({ x: sx(Date.parse(p.at)), y: sy(p.value), at: p.at, value: p.value }));
  // stav platí až do teď → schod na konec osy, ať poslední hodnota není jen bod
  if (pts.length) pts.push({ ...pts[pts.length - 1], x: sx(x1) });
  return { pts, sy };
}

/** Schodovitá čára (stav se mění skokem při synchronizaci, mezi body je konstantní). */
export function stepPath(pts: { x: number; y: number }[]): string {
  return pts.map((p, i) => (i === 0 ? `M${p.x.toFixed(1)},${p.y.toFixed(1)}` : `H${p.x.toFixed(1)}V${p.y.toFixed(1)}`)).join("");
}

/** Index nejbližšího bodu k poměru 0–1 na ose x (najetí / dotyk). */
export function nearestIndex(xs: number[], x: number): number {
  let best = 0;
  xs.forEach((v, i) => {
    if (Math.abs(v - x) < Math.abs(xs[best] - x)) best = i;
  });
  return best;
}

export function compactNumber(v: number | null | undefined): string {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${(v / 1_000_000).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} M`;
  if (a >= 10_000) return `${Math.round(v / 1000).toLocaleString("cs-CZ")} k`;
  return Math.round(v).toLocaleString("cs-CZ");
}

/** Popisek značky osy podle kroku – sousední značky se nikdy neslijí do stejného textu („13 k, 13 k“). */
export function tickLabel(v: number, step: number): string {
  const a = Math.abs(v);
  if (a >= 1_000_000 && step >= 100_000) return `${(v / 1_000_000).toLocaleString("cs-CZ", { maximumFractionDigits: step >= 1_000_000 ? 0 : 1 })} M`;
  if (a >= 10_000 && step >= 1000) return `${(v / 1000).toLocaleString("cs-CZ", { maximumFractionDigits: 0 })} k`;
  return Math.round(v).toLocaleString("cs-CZ");
}

export function pct(v: number | null | undefined): string {
  return v == null ? "–" : `${v.toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} %`;
}

export function dayLabel(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${Number(d)}. ${Number(m)}.`;
}

/** Čas bodu pro tooltip v Europe/Prague: „27. 11. 14:05“. */
export function pointLabel(iso: string): string {
  return new Date(iso).toLocaleString("cs-CZ", { timeZone: "Europe/Prague", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Změna za období jako text se znaménkem („+80“, „−1,2 M“, „beze změny“). */
export function changeLabel(points: WotPoint[]): string | null {
  if (points.length < 2) return null;
  const d = points[points.length - 1].value - points[0].value;
  if (d === 0) return "beze změny";
  return `${d > 0 ? "+" : "−"}${compactNumber(Math.abs(d))}`;
}
