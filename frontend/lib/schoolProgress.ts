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
    /** MRK-112: týdny s výukou, které jde zapsat (nejnovější první; tento týden jen když v něm výuka je). */
    class_weeks: string[];
    class_this_week: boolean;
  };
  /** MRK-112: rytmus výuky – každý týden (1) nebo ob týden (2) od pondělí `anchor`. */
  schedule: { every: 1 | 2; anchor: string | null };
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

/** MRK-112: volba rytmu ve formuláři – každý týden / ob týden s výukou tento týden / ob týden s výukou minulý týden. */
export type ScheduleChoice = "weekly" | "this" | "prev";

export const SCHEDULE_OPTIONS: { value: ScheduleChoice; label: string }[] = [
  { value: "weekly", label: "Každý týden" },
  { value: "this", label: "Ob týden – výuka tento týden" },
  { value: "prev", label: "Ob týden – výuka minulý týden" },
];

export function scheduleChoice(p: SubjectProgress): ScheduleChoice {
  if (p.schedule.every !== 2) return "weekly";
  return p.attendance.class_this_week ? "this" : "prev";
}

/** Tělo PATCH /school/subject/{id} pro zvolený rytmus (kotva = pondělí týdne s výukou). */
export function schedulePatch(choice: ScheduleChoice, weekStart: string, previousWeekStart: string) {
  if (choice === "weekly") return { attendance_every: 1, attendance_anchor: null };
  return { attendance_every: 2, attendance_anchor: choice === "this" ? weekStart : previousWeekStart };
}

/**
 * MRK-112: rozdělení týdnů s výukou pro kartu – tento týden (jen když v něm výuka je), poslední výuka před ním
 * a starší týdny k doplnění (nejnovější první).
 */
export function attendanceWeeks(p: SubjectProgress, weekStart: string): { current: string | null; previous: string | null; older: string[] } {
  const weeks = p.attendance.class_weeks;
  const current = weeks[0] === weekStart ? weekStart : null;
  const rest = current ? weeks.slice(1) : weeks;
  return { current, previous: rest[0] ?? null, older: rest.slice(1) };
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
