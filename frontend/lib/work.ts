/**
 * Práce (Roadmap 4B): čisté pomocné funkce pro stránku /work – seskupení session po dnech,
 * stav zápisu do Financí a odhad výdělku ve formuláři. Bez závislostí (testy: work.test.mjs).
 */
import type { Tone } from "./ui.ts";

export type WorkSessionItem = {
  id: number;
  date: string;
  hours: number;
  project: string;
  description: string;
  hourly_rate: number;
  earnings: number;
  finance_transaction_id?: number | null;
  sync_to_finance?: boolean | null;
};

export type WorkSummary = {
  total_hours: number;
  total_earnings: number;
  this_month_hours: number;
  this_month_earnings: number;
};

export type WorkDay = {
  /** YYYY-MM-DD */
  date: string;
  sessions: WorkSessionItem[];
  hours: number;
  earnings: number;
};

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/**
 * Session seskupené po dnech, nejnovější den první. Uvnitř dne zůstává pořadí z API
 * (backend řadí date desc, id desc). Součty hodin/výdělku za den zaokrouhlené na setiny.
 */
export function groupSessionsByDay(sessions: readonly WorkSessionItem[]): WorkDay[] {
  const byDate = new Map<string, WorkDay>();
  for (const s of sessions) {
    let day = byDate.get(s.date);
    if (!day) {
      day = { date: s.date, sessions: [], hours: 0, earnings: 0 };
      byDate.set(s.date, day);
    }
    day.sessions.push(s);
    day.hours = Math.round((day.hours + num(s.hours)) * 100) / 100;
    day.earnings = Math.round((day.earnings + num(s.earnings)) * 100) / 100;
  }
  // ISO data (YYYY-MM-DD) jdou řadit řetězcově.
  return [...byDate.values()].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

/** Štítek historického zápisu do Financí (MRK-60: nové záznamy práce Finance nezapisují, starší vazby zůstávají). */
export function financeSyncMeta(s: Pick<WorkSessionItem, "finance_transaction_id">): { label: string; tone: Tone } | null {
  return s.finance_transaction_id ? { label: "Zapsáno ve Financích", tone: "success" } : null;
}

/** Odhad výdělku z textových polí formuláře; null, když jedno z polí chybí nebo není číslo. */
export function estimateEarnings(hours: string, hourlyRate: string): number | null {
  if (!hours || !hourlyRate) return null;
  const h = parseFloat(hours);
  const r = parseFloat(hourlyRate);
  if (Number.isNaN(h) || Number.isNaN(r)) return null;
  return h * r;
}
