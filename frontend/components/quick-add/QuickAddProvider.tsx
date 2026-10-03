"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { isQuickAddShortcut } from "@/lib/quickAdd";
import { QuickAddDialog } from "./QuickAddDialog";

const QuickAddContext = createContext<{ open: () => void } | null>(null);

/** Otevření Rychlého přidání odkudkoli (tlačítko „+" v shellu). */
export function useOpenQuickAdd(): () => void {
  return useContext(QuickAddContext)?.open ?? (() => undefined);
}

/**
 * Rychlé přidání (Roadmap 4E): jeden globální vstup (Ctrl/⌘+Shift+K a „+" v shellu). Jen v přihlášeném
 * shellu (AppShell) – na /login se nevykreslí. Ctrl+K (bez Shiftu) zůstává vyhledávání.
 */
export function QuickAddProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const openQuickAdd = useCallback(() => setOpen(true), []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || !isQuickAddShortcut(e)) return;
      e.preventDefault();
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <QuickAddContext.Provider value={{ open: openQuickAdd }}>
      {children}
      <QuickAddDialog open={open} onClose={() => setOpen(false)} />
    </QuickAddContext.Provider>
  );
}
