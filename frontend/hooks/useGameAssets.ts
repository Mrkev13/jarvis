"use client";

import { useSyncExternalStore } from "react";
import { EMPTY_MANIFEST, MANIFEST_URL, parseManifest, resolveTankTag, type GameAssetManifest } from "@/lib/gameAssets";

/**
 * Manifest lokálních herních assetů (public/game-assets/manifest.json, vytváří ho scripts/fetch-game-assets.mjs).
 * Načte se jednou za načtení aplikace a sdílí se; chybí-li (čerstvý klon, žádné assety) → prázdný manifest
 * a všude záložní monogramy. `null` = ještě se načítá (komponenta drží rozměr, nic neskáče).
 */
let manifest: GameAssetManifest | null = null;
let started = false;
const listeners = new Set<() => void>();

function load() {
  if (started) return;
  started = true;
  fetch(MANIFEST_URL, { cache: "no-cache" })
    .then((res) => (res.ok ? res.json() : null))
    .then((raw) => parseManifest(raw))
    .catch(() => EMPTY_MANIFEST)
    .then((m) => {
      manifest = m;
      listeners.forEach((l) => l());
    });
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  load();
  return () => listeners.delete(onChange);
}

export function useGameAssetManifest(): GameAssetManifest | null {
  return useSyncExternalStore(subscribe, () => manifest, () => null);
}

/** Game Enrichment C: tag vozidla z replaye („sweden:S16_Kranvagn") → název z Tankopedie; neznámý / bez manifestu → null. */
export function useTankNameForTag(tag: string | null | undefined): string | null {
  const m = useGameAssetManifest();
  return m && tag ? resolveTankTag(m.tanks, tag)?.name ?? null : null;
}
