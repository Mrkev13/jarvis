"use client";

import { useMemo } from "react";
import { useApiResource } from "@/hooks/useApiResource";
import { MODULE_ACCESS } from "@/lib/moduleConfig";
import { navPagesFor } from "@/lib/navigation";
import {
  filterAvailable,
  groupResults,
  MIN_REMOTE_QUERY,
  normalize,
  searchNavigation,
  type SearchGroup,
  type SearchResult,
} from "@/lib/search";

/** Prodleva před dotazem na backend (psaní nespouští požadavek na každý znak). */
export const SEARCH_DEBOUNCE_MS = 180;

type RemoteResponse = { query: string; results: SearchResult[]; total: number };

/** Roadmap 6C: Ctrl+K hledá jen stránky dostupných modulů (stejný seznam jako navigace). */
const PAGES = navPagesFor(MODULE_ACCESS);

/**
 * Výsledky globálního vyhledávání: navigace hned (lokálně), záznamy z GET /search s debounce.
 * Starší požadavky ruší useApiResource (AbortController + pořadové číslo) a odpověď pro jiný dotaz
 * se nezobrazí (kontrola `query`), takže výsledky nikdy „neskočí" na předchozí dotaz.
 */
export function useGlobalSearch(query: string, { enabled, recent }: { enabled: boolean; recent: SearchResult[] }) {
  const q = query.trim();
  const nq = normalize(q).slice(0, 100);
  const remotePath = enabled && nq.length >= MIN_REMOTE_QUERY ? `/search?q=${encodeURIComponent(q)}&limit=30` : null;
  const remote = useApiResource<RemoteResponse>(remotePath, { debounceMs: SEARCH_DEBOUNCE_MS });

  const fresh = remote.data && remote.data.query === nq ? remote.data : null;
  const searching = remotePath !== null && !fresh && !remote.error;

  const groups: SearchGroup[] = useMemo(() => {
    if (!nq) {
      const nav = searchNavigation("", PAGES);
      const recentAvailable = filterAvailable(recent, MODULE_ACCESS);
      return [
        ...(recentAvailable.length ? [{ key: "recent", label: "Nedávno otevřené", results: recentAvailable }] : []),
        { key: "page", label: "Navigace", results: nav },
      ];
    }
    return groupResults([...searchNavigation(q, PAGES), ...filterAvailable(fresh?.results ?? [], MODULE_ACCESS)]);
  }, [nq, q, fresh, recent]);

  return {
    groups,
    searching,
    error: remotePath !== null && !fresh ? remote.error : null,
    retry: remote.reload,
    /** Prázdný výsledek až po odpovědi (žádné „Nic nenalezeno" během hledání). */
    empty: Boolean(nq) && groups.length === 0 && !searching && !(remotePath !== null && remote.error),
    remoteTotal: fresh?.total ?? 0,
  };
}
