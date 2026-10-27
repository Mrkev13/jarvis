/**
 * Cíle: české popisky stavů, sledování a zdrojů automatických cílů (Roadmap 4B –
 * sdílí stránka Cíle i karty Planneru). Čisté funkce, testy: goals.test.mjs.
 */
import type { Tone } from "./ui.ts";

export const GOAL_STATUSES = ["active", "in_progress", "completed", "paused", "cancelled"] as const;

const STATUS_META: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Aktivní", tone: "accent" },
  in_progress: { label: "Rozpracovaný", tone: "info" },
  completed: { label: "Splněný", tone: "success" },
  paused: { label: "Pozastavený", tone: "neutral" },
  cancelled: { label: "Zrušený", tone: "neutral" },
};

export function goalStatusMeta(status: string | null | undefined): { label: string; tone: Tone } {
  return STATUS_META[String(status ?? "").toLowerCase()] ?? { label: String(status || "–"), tone: "neutral" };
}

/** Zdroje automatických cílů (backend: goal_history_service). */
export const GOAL_SOURCES = [
  { value: "finance_balance", label: "Finance – stav účtu", unit: "Kč", placeholder: "150000" },
  { value: "work_month_hours", label: "Práce – hodiny tento měsíc", unit: "h", placeholder: "100" },
  { value: "work_month_earnings", label: "Práce – výdělek tento měsíc", unit: "Kč", placeholder: "80000" },
  { value: "finance_month_income", label: "Finance – příjmy tento měsíc", unit: "Kč", placeholder: "100000" },
  { value: "finance_month_expenses", label: "Finance – výdaje tento měsíc", unit: "Kč", placeholder: "50000" },
  { value: "school_completed_assignments", label: "Škola – dokončené úkoly", unit: "ks", placeholder: "20" },
  { value: "school_open_assignments", label: "Škola – otevřené úkoly", unit: "ks", placeholder: "10" },
  { value: "mff_t4_count", label: "MFF – postavy T4 celkem", unit: "ks", placeholder: "20" },
  { value: "mff_built_t4_count", label: "MFF – postavené T4", unit: "ks", placeholder: "15" },
  { value: "mff_high_priority_built_count", label: "MFF – postavené s vysokou prioritou", unit: "ks", placeholder: "5" },
  { value: "wot_ace_mastery_count", label: "WoT – počet M-ek (Mistr)", unit: "ks", placeholder: "50" },
] as const;

export function goalSourceMeta(source: string | null | undefined) {
  return GOAL_SOURCES.find((s) => s.value === source) ?? null;
}

/** „Ručně" / „Automaticky · Práce – hodiny tento měsíc". */
export function goalTrackingLabel(trackingType: string | null | undefined, source?: string | null): string {
  if (String(trackingType).toLowerCase() !== "automatic") return "Ručně";
  const meta = goalSourceMeta(source);
  return meta ? `Automaticky · ${meta.label}` : source ? `Automaticky · ${source}` : "Automaticky";
}

/** Stav z přehledu cílů v Planneru (stagnace / skluz / na cestě) → štítek; null = nic nehlásit. */
export function goalPaceMeta(stagnating: boolean, onTrack: string | null | undefined): { label: string; tone: Tone } | null {
  if (stagnating) return { label: "Stagnuje", tone: "danger" };
  if (onTrack === "behind") return { label: "Zaostává", tone: "warning" };
  if (onTrack === "on_track") return { label: "Na cestě", tone: "success" };
  return null;
}
