"use client";

import { useAnimatedNumber } from "@/lib/motion";

interface AnimatedNumberProps {
  value: number | null | undefined;
  format: (value: number) => string;
  /** Zobrazí se, když hodnota chybí (stejně jako dosavadní formátovače). */
  fallback?: string;
  className?: string;
}

const MAX_DECIMALS = 2;

function decimalsOf(value: number): number {
  const fraction = String(value).split(".")[1] ?? "";
  return Math.min(MAX_DECIMALS, fraction.length);
}

/**
 * Číslo, které se při změně plynule „dopočítá" na novou hodnotu (první zobrazení bez animace).
 * Mezihodnoty se zaokrouhlují na přesnost cílové hodnoty (žádné blikající desetiny),
 * tabular-nums brání poskakování šířky během přechodu.
 */
export function AnimatedNumber({ value, format, fallback = "-", className = "" }: AnimatedNumberProps) {
  const missing = value === null || value === undefined || !Number.isFinite(Number(value));
  const target = missing ? 0 : Number(value);
  const display = useAnimatedNumber(target);
  const shown = Number(display.toFixed(decimalsOf(target)));
  return <span className={`tabular-nums ${className}`}>{missing ? fallback : format(shown)}</span>;
}
