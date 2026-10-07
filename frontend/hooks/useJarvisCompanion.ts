"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { JarvisState } from "@/lib/jarvisAvatar";
import { COMPANION_PREF_KEY, parseCompanionPref, serializeCompanionPref } from "@/lib/jarvisCompanion";
import { clearJarvisSource, publishJarvisSource } from "@/lib/jarvisSignals";

/**
 * Preference „Jarvis companion zapnutý" – stejný vzor jako rozložení Řídicího centra:
 * verzovaný klíč v localStorage, vlastní událost pro tuto záložku, `storage` pro ostatní,
 * paměťová záloha při zakázaném úložišti a `null` na serveru (žádný hydration mismatch).
 */
const CHANGE_EVENT = "standa-hub:jarvis-companion";
let memoryRaw: string | null = null;

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(COMPANION_PREF_KEY);
  } catch {
    return memoryRaw;
  }
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key === COMPANION_PREF_KEY) onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

export function useCompanionPref() {
  const enabled = useSyncExternalStore<boolean | null>(
    subscribe,
    () => parseCompanionPref(readRaw()),
    () => null,
  );
  const setEnabled = useCallback((value: boolean) => {
    const raw = serializeCompanionPref(value);
    try {
      window.localStorage.setItem(COMPANION_PREF_KEY, raw);
    } catch {
      memoryRaw = raw;
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return { enabled, setEnabled };
}

/** Stránka hlásí companionovi svůj stav (AI chat, Denní briefing…); při odchodu ze stránky se zdroj smaže. */
export function useJarvisSource(id: string, state: JarvisState) {
  useEffect(() => {
    publishJarvisSource(id, state);
  }, [id, state]);
  useEffect(() => () => clearJarvisSource(id), [id]);
}
