"use client";

import { useSyncExternalStore } from "react";

/**
 * matchMedia jako React stav. Na serveru / před hydratací `null` (neznámé) – komponenty, které se mají
 * vykreslit jen v jednom rozložení (např. zvonek notifikací), tak nevzniknou dvakrát.
 */
export function useMediaQuery(query: string): boolean | null {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => null,
  );
}

export const DESKTOP_QUERY = "(min-width: 768px)";
