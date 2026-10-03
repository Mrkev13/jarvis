// World of Tanks modul: české popisky, payloady pro backend a odvozená čísla grindů (čistá logika, bez Reactu).
import type { Tone } from "./ui.ts";

export type WotResources = {
  credits?: number;
  gold?: number;
  bonds?: number;
  free_xp?: number;
};

export type WotGrind = {
  id?: number;
  tank: string;
  xp_remaining: number;
  priority: string;
  status: string;
};

export type GrindDraft = {
  tank: string;
  xp_remaining: string;
  priority: string;
  status: string;
};

export const RESOURCE_KEYS = ["credits", "gold", "bonds", "free_xp"] as const;
export type ResourceKey = (typeof RESOURCE_KEYS)[number];

/** Herní měny zůstávají pod herními názvy (Credits, Gold, Bonds, Free XP). */
export const RESOURCE_LABELS: Record<ResourceKey, string> = {
  credits: "Credits",
  gold: "Gold",
  bonds: "Bonds",
  free_xp: "Free XP",
};

export const GRIND_PRIORITIES = [
  { value: "low", label: "Nízká" },
  { value: "medium", label: "Střední" },
  { value: "high", label: "Vysoká" },
] as const;

export const GRIND_STATUSES = [
  { value: "active", label: "Aktivní" },
  { value: "paused", label: "Pozastaveno" },
  { value: "completed", label: "Dokončeno" },
] as const;

export function emptyGrindDraft(): GrindDraft {
  return { tank: "", xp_remaining: "", priority: "medium", status: "active" };
}

export function grindStatusMeta(status: string | null | undefined): { tone: Tone; label: string } {
  const s = String(status || "active").toLowerCase();
  if (s === "completed") return { tone: "success", label: "Dokončeno" };
  if (s === "paused") return { tone: "neutral", label: "Pozastaveno" };
  if (s === "active") return { tone: "accent", label: "Aktivní" };
  return { tone: "neutral", label: String(status) };
}

/** Jeden POST /wot/resource na každou vyplněnou měnu: { resource, amount }. */
export function resourceEntries(draft: WotResources): { resource: ResourceKey; amount: number }[] {
  return RESOURCE_KEYS.filter((k) => draft[k] !== undefined && draft[k] !== null).map((k) => ({
    resource: k,
    amount: Number(draft[k]),
  }));
}

/** Validace + tělo POST /wot/grind. Vrací chyby polí (česky), nebo hotové tělo. */
export function grindBody(
  draft: GrindDraft,
):
  | { ok: true; body: { tank: string; xp_remaining: number; priority: string; status: string } }
  | { ok: false; errors: { tank?: string; xp_remaining?: string } } {
  const errors: { tank?: string; xp_remaining?: string } = {};
  if (!draft.tank.trim()) errors.tank = "Vyplň název tanku.";
  if (draft.xp_remaining === "") errors.xp_remaining = "Vyplň zbývající XP.";
  if (errors.tank || errors.xp_remaining) return { ok: false, errors };
  return {
    ok: true,
    body: {
      tank: draft.tank.trim(),
      xp_remaining: Number(draft.xp_remaining),
      priority: draft.priority,
      status: draft.status,
    },
  };
}


/** Součet zbývajícího XP aktivních grindů. */
export function activeXpRemaining(grinds: WotGrind[]): number {
  return grinds
    .filter((g) => String(g.status).toLowerCase() === "active")
    .reduce((sum, g) => sum + (Number.isFinite(g.xp_remaining) ? g.xp_remaining : 0), 0);
}
