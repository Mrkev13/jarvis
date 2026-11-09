/**
 * MRK-86: zápočet, výsledky zkoušek a týdenní docházka u předmětu (GET /school/progress). Všechno spočítá backend
 * (modules/school/progress.py) – tady jen typy, popisky a tóny pro UI (testy: schoolProgress.test.mjs).
 */

export type CreditStatus = "pending" | "passed" | "failed";
export type AbsenceLevel = "ok" | "last" | "exhausted" | "exceeded" | null;

export interface SubjectProgress {
  id: number;
  name: string;
  code: string;
  semester: string;
  active: boolean;
  credit: { status: CreditStatus; label: string; date: string | null };
  exams: {
    open: number;
    closed: number;
    passed: number;
    failed: number;
    results: { id: number; title: string; date: string | null; outcome: string; outcome_label: string; result: string | null }[];
  };
  attendance: {
    present: number;
    absent: number;
    recorded: number;
    limit: number | null;
    remaining: number | null;
    level: AbsenceLevel;
    text: string;
    warning: string | null;
    this_week: boolean | null;
    weeks: { week_start: string; present: boolean }[];
  };
}

export interface ProgressPayload {
  week_start: string;
  previous_week_start: string;
  subjects: SubjectProgress[];
}

export const CREDIT_OPTIONS: { value: CreditStatus; label: string }[] = [
  { value: "pending", label: "Nesplněn" },
  { value: "passed", label: "Splněn" },
  { value: "failed", label: "Neuznán" },
];

export const MAX_ABSENCE_LIMIT = 52;

export function creditTone(status: CreditStatus): "success" | "danger" | "neutral" {
  return status === "passed" ? "success" : status === "failed" ? "danger" : "neutral";
}

/** Tón řádku docházky: varuje jen backend (`warning`), u splněného zápočtu nic. */
export function absenceTone(a: Pick<SubjectProgress["attendance"], "level" | "warning">): "danger" | "warning" | "neutral" {
  if (!a.warning) return "neutral";
  return a.level === "exceeded" ? "danger" : "warning";
}

/** „2026-11-09" → „9. 11." (datum bez časové zóny – žádný posun přes Date). */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${d}. ${m}.`;
}

export function weekLabel(iso: string): string {
  return `týden od ${shortDate(iso)}`;
}

/** Stav daného týdne z posledních zapsaných týdnů (null = nezapsáno). */
export function weekState(p: SubjectProgress, weekStart: string): boolean | null {
  return p.attendance.weeks.find((w) => w.week_start === weekStart)?.present ?? null;
}

/** „Zkoušky: 2 uzavřené (1 složeno, 1 nesloženo), 1 čeká" nebo null, když předmět žádné nemá. */
export function examsSummary(e: SubjectProgress["exams"]): string | null {
  if (!e.open && !e.closed) return null;
  const parts: string[] = [];
  if (e.closed) {
    const detail = [e.passed ? `${e.passed} složeno` : "", e.failed ? `${e.failed} nesloženo` : ""].filter(Boolean).join(", ");
    parts.push(`${e.closed} ${e.closed === 1 ? "uzavřená" : e.closed < 5 ? "uzavřené" : "uzavřených"}${detail ? ` (${detail})` : ""}`);
  }
  if (e.open) parts.push(`${e.open} čeká`);
  return `Zkoušky: ${parts.join(", ")}`;
}

/** Text pole limitu → číslo, null (bez limitu) nebo „invalid". */
export function parseAbsenceLimit(text: string): number | null | "invalid" {
  const t = text.trim();
  if (!t) return null;
  if (!/^\d{1,2}$/.test(t)) return "invalid";
  const n = Number(t);
  return n <= MAX_ABSENCE_LIMIT ? n : "invalid";
}
