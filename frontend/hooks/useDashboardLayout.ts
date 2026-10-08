"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  availableWidgets,
  defaultLayout,
  LAYOUT_STORAGE_KEY,
  parseStoredLayout,
  preserveUnavailable,
  serializeLayout,
  type DashboardLayout,
} from "@/lib/dashboardLayout";
import { MODULE_ACCESS } from "@/lib/moduleConfig";

/**
 * Rozložení Řídicího centra (Roadmap 4F) v localStorage (verzovaný klíč, ověřený obsah, poškozená data → výchozí).
 * Server ani první hydratace localStorage nevidí → `layout = null`: stránka ukáže kostru a hned po hydrataci
 * vykreslí ULOŽENÉ rozložení – žádné bliknutí výchozího a žádný hydration mismatch.
 * Změny se ukládají hned (žádný koncept, nic se neztratí zavřením úprav); jiná záložka se srovná přes `storage`.
 * Roadmap 6C: rozložení obsahuje jen widgety dostupných modulů; uložené záznamy vypnutých zůstávají (viz
 * preserveUnavailable), takže vypnutí modulu nic nesmaže a zapnutí vrátí widget, jak byl.
 */
const AVAILABLE = availableWidgets(MODULE_ACCESS);
const availableDefault = () => defaultLayout(AVAILABLE);
const CHANGE_EVENT = "standa-hub:dashboard-layout";

let cache: { raw: string | null; layout: DashboardLayout } | null = null;
/** Když úložiště nejde použít, změny platí v paměti do obnovení stránky. */
let memoryRaw: string | null = null;

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  } catch {
    return memoryRaw; // soukromé okno / zakázané úložiště
  }
}

function getSnapshot(): DashboardLayout {
  const raw = readRaw();
  if (!cache || cache.raw !== raw) cache = { raw, layout: parseStoredLayout(raw, AVAILABLE) };
  return cache.layout;
}

function getServerSnapshot(): DashboardLayout | null {
  return null;
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key === LAYOUT_STORAGE_KEY) onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

function write(layout: DashboardLayout | null) {
  const raw = layout ? serializeLayout(preserveUnavailable(layout, readRaw(), AVAILABLE)) : null;
  try {
    if (raw) window.localStorage.setItem(LAYOUT_STORAGE_KEY, raw);
    else window.localStorage.removeItem(LAYOUT_STORAGE_KEY);
  } catch {
    memoryRaw = raw;
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function useDashboardLayout() {
  const layout = useSyncExternalStore<DashboardLayout | null>(subscribe, getSnapshot, getServerSnapshot);
  const update = useCallback((fn: (current: DashboardLayout) => DashboardLayout) => {
    const current = getSnapshot();
    const next = fn(current);
    if (next !== current) write(next);
  }, []);
  /** Výchozí rozložení = smazaný klíč (budoucí změny výchozího se tak projeví i u resetovaných uživatelů). */
  const reset = useCallback(() => write(null), []);
  return { layout, update, reset, defaults: availableDefault, available: AVAILABLE };
}
