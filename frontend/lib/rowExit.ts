/**
 * MRK-126: čistá logika mizení řádků – kam přesunout fokus, když řádek po akci (Hotovo, Smazat…) zmizí.
 * Testy: rowExit.test.mjs. React část: components/motion/useRowExit.ts.
 */

/** Soused řádku `key` v pořadí `keys`: další, jinak předchozí; `null`, když jiný řádek není. */
export function neighborKey(keys: readonly string[], key: string): string | null {
  const i = keys.indexOf(key);
  if (i === -1) return null;
  return keys[i + 1] ?? keys[i - 1] ?? null;
}

/** Jak dlouho řádek mizí před obnovou dat (ms) – v omezeném pohybu nečeká vůbec. */
export function exitDelay(reducedMotion: boolean, normalMs: number): number {
  return reducedMotion ? 0 : normalMs;
}
