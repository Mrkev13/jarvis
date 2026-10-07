/**
 * Jarvis signály (MRK-16): malý sdílený obchod mezi stránkami a companionem – žádný velký eventový framework.
 * - Zdroj (AI stránka, Denní briefing…) publikuje svůj JarvisState (`publishJarvisSource`).
 *   Trvající nálady (listening/thinking/warning) se slučují podle priority do jedné `mood`.
 *   Vstup zdroje do success/error vyšle jeden `pulse` (krátká reakce), setrvání v něm už ne.
 * - Jednorázové události bez stavu (uložení v Rychlém přidání, splněný grind) volají `pulseJarvis`.
 */
import type { JarvisState } from "./jarvisAvatar.ts";

export type JarvisPulse = "success" | "error";
export type JarvisSignal = { type: "mood"; mood: JarvisState } | { type: "pulse"; kind: JarvisPulse } | { type: "stroll" };

const MOOD_RANK: Partial<Record<JarvisState, number>> = { listening: 1, thinking: 1, warning: 2 };

export function combineJarvisMood(states: Iterable<JarvisState>): JarvisState {
  let best: JarvisState = "idle";
  for (const s of states) {
    if ((MOOD_RANK[s] ?? 0) > (MOOD_RANK[best] ?? 0)) best = s;
  }
  return best;
}

export function jarvisSourceEdge(previous: JarvisState | undefined, next: JarvisState): JarvisPulse | null {
  if (next === previous) return null;
  return next === "success" || next === "error" ? next : null;
}

const sources = new Map<string, JarvisState>();
const listeners = new Set<(signal: JarvisSignal) => void>();
let mood: JarvisState = "idle";

function emit(signal: JarvisSignal) {
  for (const listener of listeners) listener(signal);
}

function refreshMood() {
  const next = combineJarvisMood(sources.values());
  if (next === mood) return;
  mood = next;
  emit({ type: "mood", mood });
}

export function publishJarvisSource(id: string, state: JarvisState) {
  const previous = sources.get(id);
  if (previous === state) return;
  sources.set(id, state);
  refreshMood();
  const edge = jarvisSourceEdge(previous, state);
  if (edge) emit({ type: "pulse", kind: edge });
}

export function clearJarvisSource(id: string) {
  if (!sources.delete(id)) return;
  refreshMood();
}

export function pulseJarvis(kind: JarvisPulse) {
  emit({ type: "pulse", kind });
}

/** Ať se hned projde k sousední kotvě (vývojová ukázka pohybu). */
export function strollJarvis() {
  emit({ type: "stroll" });
}

export function currentJarvisMood(): JarvisState {
  return mood;
}

export function subscribeJarvisSignals(listener: (signal: JarvisSignal) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
