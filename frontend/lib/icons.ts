/**
 * Ikony Standa Hubu (MRK-15) – jedna sada čárových ikon místo emoji. Čistá data bez Reactu (testy: icons.test.mjs),
 * vykresluje je `components/ui/Icon`. Mřížka 24 × 24, obrys `currentColor`, tah 1,75, kulaté konce – barvu dává text
 * okolí (tón), velikost token. Vlastní jednoduchá geometrie (žádná knihovna, žádná závislost).
 *
 * Pravidlo: ikona jen tam, kde nese informaci (typ sekce, stav, akce bez místa na text). Text zůstává hlavní.
 */
export type IconShape =
  | { t: "path"; d: string }
  | { t: "circle"; cx: number; cy: number; r: number }
  | { t: "rect"; x: number; y: number; w: number; h: number; rx?: number }
  | { t: "poly"; points: string };

const p = (d: string): IconShape => ({ t: "path", d });
const c = (cx: number, cy: number, r: number): IconShape => ({ t: "circle", cx, cy, r });
const r = (x: number, y: number, w: number, h: number, rx = 0): IconShape => ({ t: "rect", x, y, w, h, rx });

export const ICONS = {
  // sekce / moduly
  calendar: [r(3, 5, 18, 16, 2), p("M3 10h18"), p("M8 3v4"), p("M16 3v4")],
  target: [c(12, 12, 9), c(12, 12, 5), c(12, 12, 1.25)],
  briefcase: [r(3, 7, 18, 13, 2), p("M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"), p("M3 13h18")],
  wallet: [p("M4 7h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Zm0 0V6a2 2 0 0 1 2-2h10"), c(16, 13.5, 1)],
  bell: [p("M6 9a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9Z"), p("M10 20a2 2 0 0 0 4 0")],
  bot: [r(5, 8, 14, 11, 3), p("M12 4v4"), c(9.5, 13, 1), c(14.5, 13, 1), p("M9.5 16.5h5")],
  clipboard: [r(5, 4, 14, 17, 2), r(9, 2.5, 6, 3, 1), p("M9 11h6"), p("M9 15h4")],
  sun: [c(12, 12, 4), p("M12 2v2"), p("M12 20v2"), p("M4.9 4.9l1.4 1.4"), p("M17.7 17.7l1.4 1.4"), p("M2 12h2"), p("M20 12h2"), p("M4.9 19.1l1.4-1.4"), p("M17.7 6.3l1.4-1.4")],
  gamepad: [p("M7 8h10a4 4 0 0 1 4 4v2a3 3 0 0 1-5.4 1.8L14.5 14h-5l-1.1 1.8A3 3 0 0 1 3 14v-2a4 4 0 0 1 4-4Z"), p("M7.5 10.5v3"), p("M6 12h3"), p("M15.5 11h.01"), p("M17.5 13h.01")],
  zap: [{ t: "poly", points: "13 2 4 14 12 14 11 22 20 10 12 10 13 2" }],
  school: [p("M2 9l10-5 10 5-10 5-10-5Z"), p("M6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5")],
  folder: [p("M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z")],
  // stavy
  check: [p("M5 12.5l4.5 4.5L19 7.5")],
  alert: [p("M12 3.5L2.5 20h19L12 3.5Z"), p("M12 10v4"), p("M12 17h.01")],
  info: [c(12, 12, 9), p("M12 11v5"), p("M12 8h.01")],
  error: [c(12, 12, 9), p("M9 9l6 6"), p("M15 9l-6 6")],
  clock: [c(12, 12, 9), p("M12 7v5l3 2")],
  star: [{ t: "poly", points: "12 3 14.8 8.8 21 9.6 16.5 14 17.6 20.3 12 17.3 6.4 20.3 7.5 14 3 9.6 9.2 8.8" }],
  // akce
  plus: [p("M12 5v14"), p("M5 12h14")],
  x: [p("M6 6l12 12"), p("M18 6L6 18")],
  trash: [p("M4 7h16"), p("M9 7V4h6v3"), p("M6 7l1 13h10l1-13")],
  pencil: [p("M4 20h4L19 9l-4-4L4 16v4Z")],
  search: [c(11, 11, 7), p("M20 20l-4-4")],
  menu: [p("M4 7h16"), p("M4 12h16"), p("M4 17h16")],
  "chevron-right": [p("M9 6l6 6-6 6")],
  refresh: [p("M20 11a8 8 0 1 0-2.3 5.7"), p("M20 4v7h-7")],
  mic: [r(9, 3, 6, 11, 3), p("M5 11a7 7 0 0 0 14 0"), p("M12 18v3")],
  volume: [p("M4 9v6h4l5 4V5L8 9H4Z"), p("M16.5 9a4 4 0 0 1 0 6"), p("M19 6.5a7.5 7.5 0 0 1 0 11")],
  paw: [c(7, 7, 2), c(12, 5.5, 2), c(17, 7, 2), c(19, 12, 1.75), p("M7.5 17.5c0-3 2-5.5 4.5-5.5s4.5 2.5 4.5 5.5c0 2-1.5 3-4.5 3s-4.5-1-4.5-3Z")],
} satisfies Record<string, IconShape[]>;

export type IconName = keyof typeof ICONS;
export const ICON_NAMES = Object.keys(ICONS) as IconName[];

export function isIconName(value: unknown): value is IconName {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(ICONS, value);
}

/** Velikosti (px): xs = v odznaku, sm = v tlačítku / řádku, md = hlavička karty, lg = samostatně. */
export const ICON_SIZES = { xs: 12, sm: 16, md: 20, lg: 24 } as const;
export type IconSize = keyof typeof ICON_SIZES;
export const ICON_STROKE = 1.75;

/** Ikony, které se při `filled` vyplní (stav „zapnuto" – např. oblíbené); ostatní zůstávají čárové. */
export const FILLABLE: ReadonlySet<IconName> = new Set<IconName>(["star", "bell"]);
