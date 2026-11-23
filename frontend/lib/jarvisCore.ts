/**
 * MRK-132: Jarvis jádro dne na dashboardu – čistá logika (testy: jarvisCore.test.mjs).
 * Vše deterministicky z GET /today (summary), žádné AI: segmenty reaktoru (hotovo / zbývá) a jedna věta stavu.
 */
import type { TodayPayload } from "./today.ts";

export const MAX_SEGMENTS = 12;

/** Segmenty prstence: celkem = hotovo + zbývá (max 12, pak úměrně), rozsvícené = hotovo. Prázdný den = 0 / 0. */
export function coreSegments(done: number, remaining: number, max: number = MAX_SEGMENTS): { total: number; lit: number } {
  const d = Math.max(0, Math.floor(done || 0));
  const r = Math.max(0, Math.floor(remaining || 0));
  const all = d + r;
  if (all === 0) return { total: 0, lit: 0 };
  if (all <= max) return { total: all, lit: d };
  const lit = r === 0 ? max : Math.min(max - 1, Math.round((d / all) * max));
  return { total: max, lit };
}

/** 1 věc / 2–4 věci / 5+ věcí. */
export function things(n: number): string {
  if (n === 1) return "věc";
  if (n >= 2 && n <= 4) return "věci";
  return "věcí";
}

function nextPart(next: TodayPayload["summary"]["next"]): string | null {
  if (!next) return null;
  const when = next.time ? ` v ${next.time}` : "";
  const soon = next.minutes_until != null && next.minutes_until >= 0 && next.minutes_until <= 90 ? ` (za ${next.minutes_until} min)` : "";
  return `Další je ${next.title}${when}${soon}.`;
}

/** Jedna věta od Jarvise o dnešku – co hoří, co je další, nebo že je hotovo. */
export function coreLine(summary: TodayPayload["summary"]): string {
  const { attention, remaining, done } = summary;
  const parts: string[] = [];
  if (attention > 0) parts.push(`${attention} ${things(attention)} hoří.`);
  const next = nextPart(summary.next);
  if (next) parts.push(next);
  else if (remaining > 0) parts.push(`Zbývá ${remaining} ${things(remaining)}.`);
  if (parts.length) return parts.join(" ");
  if (done > 0) return "Na dnešek je všechno hotovo. Dobrá práce.";
  return "Dnes nic naplánovaného – volno.";
}

/** Stav pro barvu jádra: hoří = varování, hotovo = úspěch, jinak klid. */
export function coreMood(summary: TodayPayload["summary"]): "alert" | "done" | "calm" {
  if (summary.attention > 0) return "alert";
  if (summary.remaining === 0 && summary.done > 0) return "done";
  return "calm";
}
