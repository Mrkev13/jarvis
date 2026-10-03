"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { apiJson, errorMessage, isAbortError } from "@/lib/api";
import { initialResource, resourceReducer, type ResourceState } from "@/lib/resource";

export type ApiResourceOptions = {
  /** Zpoždění před načtením po změně cesty (vyhledávání / filtry). */
  debounceMs?: number;
  /** Periodické obnovení (např. připomínky, zvonek). Obnovení nemaže data ani neukazuje skeleton. */
  refreshMs?: number;
};

export type ApiResource<T> = {
  data: T | null;
  error: string | null;
  /** Jen první načtení (pro skeleton). */
  loading: boolean;
  /** Obnovení s už zobrazenými daty. */
  refreshing: boolean;
  status: ResourceState<T>["status"];
  reload: () => Promise<void>;
  /** Lokální úprava dat (např. odpověď POST/PATCH vrací nový stav). */
  setData: (data: T) => void;
};

/**
 * Načtení JSON z backendu se stavem loading/error/data (Roadmap 4A).
 * `path = null` → nic nenačítá (status idle). Starší požadavky se ruší (AbortController) a jejich odpovědi
 * se ignorují. 401 řeší apiFetch (přesměrování na /login). Bez knihoven pro správu stavu.
 */
export function useApiResource<T>(path: string | null, options: ApiResourceOptions = {}): ApiResource<T> {
  const { debounceMs = 0, refreshMs } = options;
  const [state, dispatch] = useReducer(resourceReducer<T>, path !== null, (enabled) => initialResource<T>(enabled));
  const seq = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback(async (p: string) => {
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    const id = ++seq.current;
    dispatch({ type: "start", id });
    try {
      const data = await apiJson<T>(p, { signal: ctrl.signal });
      dispatch({ type: "success", id, data });
    } catch (error) {
      if (isAbortError(error)) return;
      dispatch({ type: "error", id, error: errorMessage(error) });
    }
  }, []);

  useEffect(() => {
    // Načtení až v časovači: žádný synchronní setState v efektu a zároveň debounce.
    const timer = window.setTimeout(() => {
      if (path === null) dispatch({ type: "idle" });
      else void run(path);
    }, path === null ? 0 : debounceMs);
    return () => {
      window.clearTimeout(timer);
      controller.current?.abort();
    };
  }, [path, debounceMs, run]);

  useEffect(() => {
    if (path === null || !refreshMs) return;
    const timer = window.setInterval(() => void run(path), refreshMs);
    return () => window.clearInterval(timer);
  }, [path, refreshMs, run]);

  const reload = useCallback(async () => {
    if (path !== null) await run(path);
  }, [path, run]);

  const setData = useCallback((data: T) => dispatch({ type: "set", data }), []);

  return {
    data: state.data,
    error: state.error,
    loading: state.status === "loading",
    refreshing: state.refreshing,
    status: state.status,
    reload,
    setData,
  };
}
