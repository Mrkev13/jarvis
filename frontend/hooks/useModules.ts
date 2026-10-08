"use client";

import { useMemo, useSyncExternalStore } from "react";
import { apiFetch, apiJson, jsonBody, readErrorDetail } from "@/lib/api";
import type { ModuleAccess } from "@/lib/modules";
import {
  accessFor,
  MODULES_CACHE_KEY,
  parseCachedModules,
  parseModules,
  serializeModules,
  UNKNOWN_SNAPSHOT,
  type ModuleSnapshot,
  type RuntimeModule,
} from "@/lib/moduleRuntime";

/**
 * MRK-18 A2: runtime stav modulů pro celou aplikaci (jeden sdílený obchod, ne kontext).
 * - server / první hydratace: `unknown` (žádný mismatch), hned potom poslední známý stav z localStorage
 *   → po návratu do aplikace žádné probliknutí vypnutého modulu,
 * - AppShell volá `refreshModules()` při startu a při návratu do okna; Nastavení po změně,
 * - jiná záložka se srovná přes `storage` událost.
 */
let snapshot: ModuleSnapshot = UNKNOWN_SNAPSHOT;
let hydrated = false;
const listeners = new Set<() => void>();

function emit(next: ModuleSnapshot) {
  snapshot = next;
  for (const l of listeners) l();
}

function readCache(): RuntimeModule[] | null {
  try {
    return parseCachedModules(window.localStorage.getItem(MODULES_CACHE_KEY));
  } catch {
    return null; // soukromé okno / zakázané úložiště
  }
}

function writeCache(modules: RuntimeModule[]) {
  try {
    window.localStorage.setItem(MODULES_CACHE_KEY, serializeModules(modules));
  } catch {
    /* bez cache se jen příště ukáže načítání */
  }
}

function getSnapshot(): ModuleSnapshot {
  if (!hydrated) {
    hydrated = true;
    const cached = readCache();
    if (cached) snapshot = { status: "ready", modules: cached };
  }
  return snapshot;
}

function getServerSnapshot(): ModuleSnapshot {
  return UNKNOWN_SNAPSHOT;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  const onStorage = (e: StorageEvent) => {
    if (e.key !== MODULES_CACHE_KEY) return;
    const cached = parseCachedModules(e.newValue);
    if (cached) emit({ status: "ready", modules: cached });
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onStorage);
  };
}

let inflight: Promise<void> | null = null;

/** Načte GET /modules. Chyba se známým stavem nechá poslední stav; bez něj → `error` (konzervativně jen jádro). */
export function refreshModules(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const modules = parseModules(await apiJson<unknown>("/modules"));
      if (!modules) throw new Error("Neplatná odpověď /modules");
      writeCache(modules);
      emit({ status: "ready", modules });
    } catch {
      const current = getSnapshot();
      if (!current.modules) emit({ status: "error", modules: null });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Nastavení: zapnout/vypnout (true/false) nebo vrátit na výchozí (null). Chyba (409 vynuceno…) se vyhodí. */
export async function setModuleEnabled(id: string, enabled: boolean | null): Promise<void> {
  const res = await apiFetch(`/modules/${encodeURIComponent(id)}`, jsonBody("PUT", { enabled }));
  if (!res.ok) throw new Error(await readErrorDetail(res));
  await refreshModules();
}

export function useModules(): ModuleSnapshot {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/** Přístup k modulům pro komponenty – jediná cesta, jak se ptát „smí modul X do Y?". */
export function useModuleAccess(): { access: ModuleAccess; snapshot: ModuleSnapshot } {
  const current = useModules();
  const access = useMemo(() => accessFor(current), [current]);
  return { access, snapshot: current };
}
