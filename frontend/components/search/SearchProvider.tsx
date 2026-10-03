"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { isSearchShortcut } from "@/lib/search";
import { CommandPalette } from "./CommandPalette";

const SearchContext = createContext<{ open: () => void } | null>(null);

/** Otevření globálního vyhledávání odkudkoli (tlačítka v shellu). */
export function useOpenSearch(): () => void {
  return useContext(SearchContext)?.open ?? (() => undefined);
}


/**
 * Globální vyhledávání (Roadmap 4D): jediná paleta pro celou aplikaci. Jen v přihlášeném shellu
 * (AppShell) – na /login se nevykreslí, takže nevzniknou žádné neautorizované požadavky.
 */
export function SearchProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const openSearch = useCallback(() => setOpen(true), []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || !isSearchShortcut(e)) return;
      e.preventDefault();
      setOpen((o) => !o);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <SearchContext.Provider value={{ open: openSearch }}>
      {children}
      <CommandPalette open={open} onClose={() => setOpen(false)} />
    </SearchContext.Provider>
  );
}
