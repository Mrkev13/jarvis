"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { MOTION, prefersReducedMotion } from "@/lib/motion";
import { exitDelay, neighborKey } from "@/lib/rowExit";

const FOCUSABLE = "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])";

type Pending = { key: string; node: HTMLElement | null; neighbor: string | null };

/**
 * MRK-126: řádek, který po akci (Hotovo, Smazat…) ze seznamu zmizí, nejdřív krátce vybledne (`.motion-row-exit`,
 * jen opacity/transform), teprve pak se obnoví data. Když řádek opravdu zmizí, fokus přejde na sousední řádek
 * (jinak na `fallback`), takže se neztratí do `body`. Řádek, který zůstal (opakovaná připomínka), se vrátí bez skoku
 * fokusu; při chybě akce se vrátí taky. Řádky označ `data-row-key` (EntityRow `rowKey`).
 *
 * Použití: `const ok = await rowExit.run(key, async () => { …API…; return true }, reload)`.
 */
export function useRowExit(fallback?: () => HTMLElement | null) {
  const [exiting, setExiting] = useState<ReadonlySet<string>>(() => new Set());
  const pending = useRef<Pending | null>(null);
  const fallbackRef = useRef(fallback);
  useEffect(() => {
    fallbackRef.current = fallback;
  });

  const setKey = (key: string, on: boolean) =>
    setExiting((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const run = useCallback(async (key: string, action: () => Promise<boolean>, reload: () => Promise<unknown>) => {
    // jen viditelné řádky – soused ve sbalené skupině (<details>) by fokus nedostal
    const rows = Array.from(document.querySelectorAll<HTMLElement>("[data-row-key]")).filter((el) => !el.closest("details:not([open])"));
    const node = rows.find((el) => el.dataset.rowKey === key) ?? null;
    const neighbor = neighborKey(rows.map((el) => el.dataset.rowKey ?? ""), key);
    setKey(key, true);
    const wait = new Promise((r) => setTimeout(r, exitDelay(prefersReducedMotion(), MOTION.normalMs)));
    let ok = false;
    try {
      [ok] = await Promise.all([action(), wait]);
      if (ok) {
        pending.current = { key, node, neighbor };
        await reload();
      }
    } finally {
      setKey(key, false);
    }
    return ok;
  }, []);

  // Po obnovení dat: zmizel-li řádek (jeho DOM uzel už není v dokumentu), fokus na souseda / náhradní prvek.
  useEffect(() => {
    const p = pending.current;
    if (!p || exiting.has(p.key)) return;
    pending.current = null;
    if (p.node?.isConnected) return; // řádek zůstal (např. opakovaná připomínka) – fokus se nehýbe
    const row = p.neighbor ? document.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(p.neighbor)}"]`) : null;
    let target = row?.querySelector<HTMLElement>(FOCUSABLE) ?? null;
    if (!target) {
      target = fallbackRef.current?.() ?? null;
      // náhradní prvek (nadpis, panel) musí jít zaměřit programově
      if (target && !target.matches(FOCUSABLE) && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    }
    // až po zavření potvrzovacího dialogu (ten vrací fokus na své tlačítko) – proto další snímek
    requestAnimationFrame(() => target?.focus());
  }, [exiting]);

  return { exiting, run };
}
