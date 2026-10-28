"use client";

import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { apiJson, jsonBody } from "@/lib/api";
import {
  availableWidgets,
  defaultLayout,
  LAYOUT_STORAGE_KEY,
  normalizeLayout,
  parseStoredLayout,
  preserveUnavailable,
  serializeLayout,
  WIDGETS,
  type DashboardLayout,
  type WidgetDef,
} from "@/lib/dashboardLayout";
import { useModuleAccess } from "@/hooks/useModules";

/**
 * Rozložení Řídicího centra (Roadmap 4F) v localStorage (verzovaný klíč, ověřený obsah, poškozená data → výchozí).
 * Server ani první hydratace localStorage nevidí → `layout = null`: stránka ukáže kostru a hned po hydrataci
 * vykreslí ULOŽENÉ rozložení – žádné bliknutí výchozího a žádný hydration mismatch.
 * Změny se ukládají hned (žádný koncept, nic se neztratí zavřením úprav); jiná záložka se srovná přes `storage`.
 * Roadmap 6C: rozložení obsahuje jen widgety dostupných modulů; uložené záznamy vypnutých zůstávají (viz
 * preserveUnavailable), takže vypnutí modulu nic nesmaže a zapnutí vrátí widget, jak byl.
 *
 * MRK-78: zdroj pravdy je server (GET/PUT/DELETE /preferences/dashboard_layout), localStorage je jen rychlá kopie
 * pro první vykreslení. Po načtení stránky se rozložení stáhne ze serveru (úprava na PC tak platí i v mobilu);
 * když server nic nemá a zařízení má starší uložené rozložení, převezme se (PUT). Bez lokální kopie se čeká na
 * server (kostra), aby nebliklo výchozí. Server nedostupný → platí lokální kopie a stránka ukáže hlášku.
 */
const CHANGE_EVENT = "standa-hub:dashboard-layout";

// MRK-18 A2: dostupné widgety závisí na runtime stavu modulů → cache i podle jejich sady (key).
let cache: { raw: string | null; key: string; layout: DashboardLayout } | null = null;
/** Když úložiště nejde použít, změny platí v paměti do obnovení stránky. */
let memoryRaw: string | null = null;

const PREFERENCE_PATH = "/preferences/dashboard_layout";
const PUSH_DELAY_MS = 300;

export type LayoutSync = { settled: boolean; error: string | null };
let sync: LayoutSync = { settled: false, error: null };
let pullState: "idle" | "running" | "done" | "failed" = "idle";
/** Lokální změna během stahování → serverová hodnota ji nepřepíše (pošle se naopak lokální). */
let dirtyDuringPull = false;
let pushTimer: ReturnType<typeof setTimeout> | null = null;

function setSync(next: Partial<LayoutSync>) {
  sync = { ...sync, ...next };
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  } catch {
    return memoryRaw; // soukromé okno / zakázané úložiště
  }
}

function snapshotFor(available: WidgetDef[], key: string): DashboardLayout | null {
  const raw = readRaw();
  if (raw === null && !sync.settled) return null; // nic lokálně → počkat na server (žádné bliknutí výchozího)
  if (!cache || cache.raw !== raw || cache.key !== key) cache = { raw, key, layout: parseStoredLayout(raw, available) };
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

function writeLocal(raw: string | null) {
  try {
    if (raw) window.localStorage.setItem(LAYOUT_STORAGE_KEY, raw);
    else window.localStorage.removeItem(LAYOUT_STORAGE_KEY);
  } catch {
    memoryRaw = raw;
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Uloží na server (rychlé změny za sebou = jeden požadavek s poslední hodnotou). */
function schedulePush() {
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(() => {
    pushTimer = null;
    void pushNow();
  }, PUSH_DELAY_MS);
}

async function pushNow() {
  const raw = readRaw();
  try {
    if (raw) await apiJson(PREFERENCE_PATH, jsonBody("PUT", { value: JSON.parse(raw) }));
    else await apiJson(PREFERENCE_PATH, { method: "DELETE" });
    if (sync.error) setSync({ error: null });
  } catch {
    setSync({ error: "push" });
  }
}

async function pull() {
  if (pullState === "running" || pullState === "done") return;
  pullState = "running";
  dirtyDuringPull = false;
  try {
    const res = await apiJson<{ value: unknown }>(PREFERENCE_PATH);
    pullState = "done";
    const local = readRaw();
    if (dirtyDuringPull) {
      schedulePush();
    } else if (res?.value) {
      // celý registr: uložené záznamy vypnutých modulů zůstanou
      const raw = serializeLayout(normalizeLayout(res.value, WIDGETS));
      if (raw !== local) writeLocal(raw);
    } else if (local) {
      writeLocal(serializeLayout(parseStoredLayout(local, WIDGETS))); // převod starší verze i lokálně
      schedulePush(); // první načtení: rozložení z tohoto zařízení se převezme na server
    }
    setSync({ settled: true, error: null });
  } catch {
    pullState = "failed";
    setSync({ settled: true, error: "pull" });
  }
}

function write(layout: DashboardLayout | null, available: WidgetDef[]) {
  writeLocal(layout ? serializeLayout(preserveUnavailable(layout, readRaw(), available)) : null);
  if (pullState === "running") dirtyDuringPull = true;
  else schedulePush();
}

/** Po chybě: znovu stáhnout (když se to ještě nepovedlo), jinak znovu uložit. */
function retrySync() {
  if (pullState === "failed") {
    pullState = "idle";
    void pull();
  } else void pushNow();
}

function getSync(): LayoutSync {
  return sync;
}

const SERVER_SYNC: LayoutSync = { settled: false, error: null };
function getServerSync(): LayoutSync {
  return SERVER_SYNC;
}

export function useDashboardLayout() {
  const { access } = useModuleAccess();
  const available = useMemo(() => availableWidgets(access), [access]);
  const key = available.map((d) => d.id).join(",");
  const getSnapshot = useCallback(() => snapshotFor(available, key), [available, key]);
  const layout = useSyncExternalStore<DashboardLayout | null>(subscribe, getSnapshot, getServerSnapshot);
  const syncState = useSyncExternalStore<LayoutSync>(subscribe, getSync, getServerSync);
  useEffect(() => {
    void pull();
  }, []);
  const update = useCallback((fn: (current: DashboardLayout) => DashboardLayout) => {
    const current = snapshotFor(available, key);
    if (!current) return;
    const next = fn(current);
    if (next !== current) write(next, available);
  }, [available, key]);
  /** Výchozí rozložení = smazaný klíč (budoucí změny výchozího se tak projeví i u resetovaných uživatelů). */
  const reset = useCallback(() => write(null, available), [available]);
  const defaults = useCallback(() => defaultLayout(available), [available]);
  return { layout, update, reset, defaults, available, syncError: syncState.error !== null, retrySync };
}
