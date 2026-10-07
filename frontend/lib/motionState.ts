/**
 * Roadmap 6A: čistá logika motion primitiv (bez Reactu → testy přes `node --test`).
 * Komponenty v components/motion/* z ní odvozují, KDY se má co přehrát; JAK řeší CSS.
 */
import { clampPercent } from "./ui.ts";

/** Stav „signálu": čítač, který se zvýší, když přechod hodnoty splní podmínku. Použití jako React `key`. */
export interface SignalState<T> {
  prev: T;
  ready: boolean;
  signal: number;
}

export type SignalTrigger<T> = (prev: T, next: T) => boolean;

export const increased: SignalTrigger<number> = (prev, next) => next > prev;
export const becameTrue: SignalTrigger<boolean> = (prev, next) => !prev && next;

/**
 * Další stav signálu. Počítá se jen přechod mezi dvěma „ready" stavy – první načtení dat
 * (i když přijde ve stejném renderu jako ready=true) je výchozí hodnota, ne událost.
 * Beze změny vrací stejný objekt (React může render přeskočit).
 */
export function stepSignal<T>(state: SignalState<T>, value: T, ready: boolean, trigger: SignalTrigger<T>): SignalState<T> {
  if (Object.is(value, state.prev) && ready === state.ready) return state;
  const fired = state.ready && ready && trigger(state.prev, value);
  return { prev: value, ready, signal: fired ? state.signal + 1 : state.signal };
}

// ===== Streak =====

/** Hranice, při kterých je streak „milník" (připraveno pro budoucí Habits/Fitness). */
export const STREAK_MILESTONES = [7, 14, 30, 50, 100, 365] as const;

export type StreakState = "inactive" | "active" | "milestone";

function czechDays(days: number): string {
  if (days === 1) return "den";
  if (days >= 2 && days <= 4) return "dny";
  return "dní";
}

/** Vizuální stav plamene + přístupný popis (informace nikdy nezávisí na animaci). */
export function streakVisual(
  days: number,
  { broken = false, milestones = STREAK_MILESTONES }: { broken?: boolean; milestones?: readonly number[] } = {},
): { state: StreakState; label: string } {
  const safe = Number.isFinite(days) ? Math.max(0, Math.floor(days)) : 0;
  if (broken || safe === 0) return { state: "inactive", label: broken ? "Streak přerušen" : "Streak 0 dní" };
  const milestone = milestones.includes(safe);
  return {
    state: milestone ? "milestone" : "active",
    label: `Streak ${safe} ${czechDays(safe)}${milestone ? " – milník" : ""}`,
  };
}

// ===== Progress =====

/**
 * Posun výplně progress baru (hodnota CSS proměnné `--motion-progress-offset`): výplň má plnou šířku
 * stopy a posouvá se transformací → kompozitor, žádný přepočet layoutu při změně hodnoty.
 * Proměnná (ne inline transform), aby úvodní „narůstání" z @starting-style mohlo mít přednost.
 */
export function progressFillOffset(value: unknown): string {
  const rest = 100 - clampPercent(value);
  return rest === 0 ? "0%" : `-${rest}%`;
}
