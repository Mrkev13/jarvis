"use client";

import { useGameAssetManifest } from "@/hooks/useGameAssets";
import { resolveTank, type TankEntry } from "@/lib/gameAssets";

/** MRK-138: národ a tier tanku z manifestu obrázků (null = manifest chybí nebo tank nenalezen). */
export function useTankInfo(name: string | null | undefined): TankEntry | null {
  const manifest = useGameAssetManifest();
  return manifest && name ? resolveTank(manifest.tanks, name) : null;
}
