"use client";

import { useTransitionSignal } from "@/lib/motion";
import { becameTrue } from "@/lib/motionState";
import { cx } from "@/lib/ui";

interface CompletionStateProps {
  /** Je hotovo? Záře se přehraje jen při přechodu nehotovo → hotovo, ne při načtení už hotového. */
  complete: boolean;
  /** Data jsou načtená (dokud ne, přechod se nepočítá). Výchozí true. */
  ready?: boolean;
  /** Viditelný sémantický štítek při dokončení („Splněno", „Hotovo"…). Volitelné. */
  label?: React.ReactNode;
  /** Zpráva pro čtečku při dokončení (role=status). Výchozí = `label`, pokud je text. */
  announce?: string;
  children: React.ReactNode;
  as?: "div" | "span" | "li";
  className?: string;
}

/**
 * Sémantické primitivum „dokončeno" (Roadmap 6A, kategorie completion): WoT grind, milník projektu,
 * školní úkol, trénink… Při dokončení krátká zelená záře kolem obsahu (≤ 1,2 s, CSS ::after, nic neblokuje)
 * a volitelný štítek. Stav je vidět i bez animace (štítek, barvy volajícího); čtečka dostane zprávu
 * přes role=status jen při skutečném dokončení. Žádný konkrétní text modulu – ten dodává volající.
 */
export function CompletionState({ complete, ready = true, label, announce, children, as: Tag = "div", className }: CompletionStateProps) {
  const signal = useTransitionSignal(complete, ready, becameTrue);
  const celebrating = complete && signal > 0;
  const message = announce ?? (typeof label === "string" ? label : undefined);
  return (
    // Třída se připojí jen při dokončení (a odebere při návratu do nehotovo) → záře se přehraje znovu
    // při dalším dokončení. Žádné přemontování obsahu (progress ani čísla se neresetují).
    <Tag
      data-complete={complete ? "true" : "false"}
      className={cx(celebrating && "motion-completion", className)}
    >
      {children}
      {complete && label ? <span className={cx("inline-flex", celebrating && "motion-completion-label")}>{label}</span> : null}
      <span role="status" className="sr-only">
        {celebrating && message ? message : ""}
      </span>
    </Tag>
  );
}
