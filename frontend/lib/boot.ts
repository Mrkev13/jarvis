/**
 * MRK-131: úvodní „start systému" (components/jarvis/BootSequence.tsx) – čisté funkce kvůli testům.
 * Pozdrav podle pražského času; start jen jednou za relaci prohlížeče, nikdy při omezeném pohybu.
 */
export const BOOT_SESSION_KEY = "standa-hub-boot";
/** Jak dlouho je překryv v DOM (musí pokrýt CSS animace v app/hud.css – boot-overlay-out končí v 1700 ms). */
export const BOOT_MS = 1800;

/** Hodina 0–23 v Europe/Prague (ne v časové zóně prohlížeče). */
export function pragueHour(now: Date = new Date()): number {
  const h = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: "Europe/Prague" }).format(now);
  return Number(h) % 24;
}

export function bootGreeting(hour: number): string {
  if (hour >= 5 && hour < 10) return "Dobré ráno, Stando";
  if (hour >= 10 && hour < 18) return "Dobré odpoledne, Stando";
  if (hour >= 18 && hour < 23) return "Dobrý večer, Stando";
  return "Pořád vzhůru, Stando?";
}

/**
 * Má se start ukázat? `force` = ?boot=1 (ruční ukázka a UI kontrola). Automatizovaný prohlížeč (webdriver) ho
 * vynechá, aby screenshoty a kontroly neviděly překryv.
 */
export function shouldBoot(opts: { seen: boolean; reducedMotion: boolean; automated: boolean; force: boolean }): boolean {
  if (opts.reducedMotion) return false;
  if (opts.force) return true;
  return !opts.seen && !opts.automated;
}
