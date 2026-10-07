/**
 * Roadmap 6A: sémantické motion tokeny (zdroj pravdy pro JS; CSS zrcadlo v app/motion.css `:root`).
 *
 * Volající neříká „jak" animovat, ale „co se stalo" (kategorie). Časování a easing vlastní tento modul
 * a motion CSS – při změně hodnot upravit obě místa (test `motionTokens.test.mjs` hlídá shodu).
 * Čistý modul bez Reactu → testovatelný přes `node --test`.
 */

/** Pět délek – žádné libovolné hodnoty mimo tuto sadu. */
export const MOTION_DURATION = {
  /** Okamžitá změna stavu (i cíl pro omezený pohyb). */
  instant: 0,
  /** Odezva na interakci: stisk, hover, malé zvýraznění. */
  fast: 140,
  /** Vstup/výstup prvku, úspěch. */
  normal: 240,
  /** Přechod hodnoty (progress), důrazná zpětná vazba. */
  deliberate: 700,
  /** Dokončení / milník – horní hranice „oslavy" (≤ 1,5 s). */
  celebration: 1200,
} as const;

export type MotionDuration = keyof typeof MOTION_DURATION;

/** Čtyři křivky. */
export const MOTION_EASING = {
  /** Symetrická – změny hodnot, pulzy. */
  standard: "cubic-bezier(0.4, 0, 0.2, 1)",
  /** Vstup – rychlý start, měkké dosednutí. */
  enter: "cubic-bezier(0.2, 0.8, 0.2, 1)",
  /** Výstup – pozvolný start, rychlý konec. */
  exit: "cubic-bezier(0.4, 0, 1, 1)",
  /** Důraz – úspěch, dokončení, milník. */
  emphasized: "cubic-bezier(0.2, 0, 0, 1)",
} as const;

export type MotionEasing = keyof typeof MOTION_EASING;

/** Sémantické kategorie pohybu (co se stalo). */
export const MOTION_CATEGORIES = [
  "entrance",
  "exit",
  "success",
  "completion",
  "progress",
  "streak",
  "milestone",
  "warning",
  "error",
  "attention",
] as const;

export type MotionCategory = (typeof MOTION_CATEGORIES)[number];

/**
 * Co zůstane při `prefers-reduced-motion: reduce`:
 *  - `static`  – žádný pohyb, výsledný stav (barva/obrys/štítek) je vidět hned,
 *  - `instant` – hodnota se změní okamžitě (bez přechodu).
 * Žádná kategorie informaci neschovává – vždy existuje text / role=status.
 */
export type ReducedMotionBehavior = "static" | "instant";

export interface MotionSpec {
  /** CSS třída z app/motion.css nebo app/motion-semantic.css. */
  className: string;
  duration: MotionDuration;
  easing: MotionEasing;
  /** Počet přehrání; `once` = jednou při připojení/změně stavu. Nekonečné smyčky jen u `streak` idle (volitelné). */
  iterations: "once" | number;
  reduced: ReducedMotionBehavior;
}

export const MOTION_SPEC: Readonly<Record<MotionCategory, MotionSpec>> = {
  entrance: { className: "motion-card", duration: "normal", easing: "enter", iterations: "once", reduced: "static" },
  exit: { className: "motion-exit", duration: "fast", easing: "exit", iterations: "once", reduced: "instant" },
  success: { className: "motion-success", duration: "normal", easing: "enter", iterations: "once", reduced: "static" },
  completion: { className: "motion-completion", duration: "celebration", easing: "emphasized", iterations: "once", reduced: "static" },
  progress: { className: "motion-progress-fill", duration: "deliberate", easing: "enter", iterations: "once", reduced: "instant" },
  streak: { className: "motion-streak-bump", duration: "deliberate", easing: "emphasized", iterations: "once", reduced: "static" },
  milestone: { className: "motion-milestone", duration: "celebration", easing: "emphasized", iterations: "once", reduced: "static" },
  warning: { className: "motion-warning", duration: "deliberate", easing: "standard", iterations: "once", reduced: "static" },
  error: { className: "motion-error", duration: "deliberate", easing: "standard", iterations: "once", reduced: "static" },
  attention: { className: "motion-attention", duration: "celebration", easing: "standard", iterations: 3, reduced: "static" },
};

/** Třída pro sémantickou kategorii: `className={motionClass("error")}`. */
export function motionClass(category: MotionCategory): string {
  return MOTION_SPEC[category].className;
}

/** Délka kategorie v ms (pro případné časovače – např. kdy uklidit dočasný stav). */
export function motionDurationMs(category: MotionCategory): number {
  return MOTION_DURATION[MOTION_SPEC[category].duration];
}
