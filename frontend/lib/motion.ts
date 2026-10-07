"use client";

import { useEffect, useRef, useState } from "react";
import { becameTrue, increased, stepSignal, type SignalState, type SignalTrigger } from "./motionState.ts";
import { MOTION_DURATION } from "./motionTokens.ts";

/**
 * JS zrcadlo motion tokenů z app/motion.css (časovače a tween čísel).
 * Sémantické tokeny žijí v lib/motionTokens.ts; tady zůstávají původní názvy.
 */
export const MOTION = {
  fastMs: MOTION_DURATION.fast,
  normalMs: MOTION_DURATION.normal,
  slowMs: MOTION_DURATION.deliberate,
  highlightMs: 1600,
} as const;

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Max. index postupného vstupu – dlouhé seznamy nečekají sekundy na poslední kartu. */
export const MAX_STAGGER = 8;

/** Inline styl pro postupný vstup karet (`motion-card`). */
export function staggerStyle(index: number): React.CSSProperties {
  return { ["--motion-i" as string]: index } as React.CSSProperties;
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * Plynulý přechod čísla při ZMĚNĚ hodnoty (první vykreslení ukáže rovnou cílovou hodnotu –
 * žádné „počítání od nuly" při načtení stránky). Při reduced-motion vrací cíl okamžitě.
 */
export function useAnimatedNumber(target: number, durationMs: number = MOTION.slowMs): number {
  const [display, setDisplay] = useState(target);
  const fromRef = useRef(target);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;
    if (prefersReducedMotion() || !Number.isFinite(from) || !Number.isFinite(target)) {
      fromRef.current = target;
      frameRef.current = requestAnimationFrame(() => setDisplay(target));
      return () => {
        if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      };
    }
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const value = from + (target - from) * easeOutCubic(t);
      fromRef.current = value;
      setDisplay(value);
      if (t < 1) {
        frameRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = target;
      }
    };
    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [target, durationMs]);

  return display;
}

/**
 * Čítač, který se zvýší, když přechod `value` splní `trigger` (např. nárůst, dosažení stavu).
 * Dokud `ready` není true (data se teprve načítají), se přechody nepočítají – načtení stránky
 * tedy nic nespustí. Použití jako `key` elementu s jednorázovou animací → přehraje se jen při události.
 */
export function useTransitionSignal<T>(value: T, ready: boolean, trigger: SignalTrigger<T>): number {
  const [state, setState] = useState<SignalState<T>>({ prev: value, ready, signal: 0 });
  const next = stepSignal(state, value, ready, trigger);
  if (next !== state) setState(next);
  return next.signal;
}

/** Čítač nárůstů `value` (např. počet upozornění) – viz useTransitionSignal. */
export function useIncreaseSignal(value: number, ready: boolean): number {
  return useTransitionSignal(value, ready, increased);
}

/**
 * Čítač, který se zvýší, když progress přejde z < 100 na >= 100 (ne při načtení už dokončeného).
 */
export function useCompletionSignal(progress: number): number {
  return useTransitionSignal(progress >= 100, true, becameTrue);
}

const NO_IDS: ReadonlySet<string> = new Set();

/**
 * ID, která přibyla od minulého seznamu → řádky dostanou `motion-highlight`
 * (animace běží jednou při připojení třídy). `ready` = data jsou načtená; první načtený
 * seznam se nezvýrazňuje (ani prázdný), zvýrazní se až položky přidané potom.
 */
export function useNewIds(ids: Array<string | number>, ready: boolean): ReadonlySet<string> {
  const key = ids.map(String).join("|");
  const [state, setState] = useState<{ key: string | null; known: ReadonlySet<string> | null; fresh: ReadonlySet<string> }>({
    key: null,
    known: null,
    fresh: NO_IDS,
  });
  if (ready && state.key !== key) {
    const current = new Set(ids.map(String));
    const known = state.known;
    const fresh = known === null ? NO_IDS : new Set([...current].filter((id) => !known.has(id)));
    setState({ key, known: current, fresh });
  }
  return state.fresh;
}
