"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { dialogKeyAction, FOCUSABLE_SELECTOR, lockScroll, nextFocusIndex } from "@/lib/dialog";

/**
 * Společné chování modálních ploch (ConfirmDialog, Drawer – Roadmap 4A/4B):
 * zámek scrollu, počáteční fokus, past na fokus (Tab / Shift+Tab), Escape (ne během busy)
 * a návrat fokusu na prvek, který plochu otevřel.
 */
export function useModal({
  open,
  panelRef,
  initialFocus,
  onClose,
  busy = false,
  restoreFocus = true,
}: {
  open: boolean;
  panelRef: React.RefObject<HTMLElement | null>;
  /** Prvek, který dostane fokus po otevření (výchozí: první fokusovatelný v panelu). */
  initialFocus?: () => HTMLElement | null | undefined;
  onClose: () => void;
  busy?: boolean;
  /** false = po zavření fokus nevracet (např. po navigaci z menu – stránka si fokus řeší sama). */
  restoreFocus?: boolean;
}) {
  // aktuální hodnoty pro listener bez jeho znovuregistrace; layout efekt proběhne dřív než úklid
  // pasivního efektu níže, takže zavření vidí aktuální restoreFocus (např. po navigaci z menu).
  const latest = useRef({ busy, onClose, restoreFocus, initialFocus });
  useLayoutEffect(() => {
    latest.current = { busy, onClose, restoreFocus, initialFocus };
  });

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const release = lockScroll();
    const timer = window.setTimeout(() => {
      const target =
        latest.current.initialFocus?.() ?? panelRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR) ?? panelRef.current;
      target?.focus();
    }, 0);

    function onKey(e: KeyboardEvent) {
      const action = dialogKeyAction(e.key, latest.current.busy);
      if (action === "close") {
        e.preventDefault();
        latest.current.onClose();
      } else if (action === "trap" && panelRef.current) {
        const items = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
        if (!items.length) {
          e.preventDefault();
          return;
        }
        const current = items.indexOf(document.activeElement as HTMLElement);
        const next = nextFocusIndex(current, items.length, e.shiftKey);
        // Necháme prohlížeč, pokud fokus zůstává uvnitř; jinak ho vrátíme na druhý konec.
        if (current === -1 || (e.shiftKey && current === 0) || (!e.shiftKey && current === items.length - 1)) {
          e.preventDefault();
          items[next]?.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      release();
      if (latest.current.restoreFocus) previous?.focus?.();
    };
  }, [open, panelRef]);
}
