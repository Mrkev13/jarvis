"use client";

import { cx } from "@/lib/ui";

interface SuccessPulseProps {
  /**
   * Čítač úspěchů (např. z `useTransitionSignal` / `useIncreaseSignal`). 0 = nic se nestalo (žádný puls
   * při načtení); každé zvýšení přehraje krátký „pop" (≈ 240 ms).
   */
  signal: number;
  children: React.ReactNode;
  className?: string;
}

/**
 * Sémantické primitivum „úspěch" (Roadmap 6A): uloženo, potvrzeno, přidáno. Krátký pop obsahu, nic víc.
 * Obsah sám musí úspěch říct textem / ikonou s popiskem – puls je jen zvýraznění.
 * Přemontuje se jen tenký inline obal (key = signal), ne data uvnitř.
 */
export function SuccessPulse({ signal, children, className }: SuccessPulseProps) {
  return (
    <span key={signal} className={cx("inline-block", signal > 0 && "motion-success", className)}>
      {children}
    </span>
  );
}
