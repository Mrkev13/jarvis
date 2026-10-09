/**
 * Návyky (MRK-21) – čistá logika bez Reactu (testy: lib.test.mjs). Data skládá backend (GET /habits,
 * modules/habits/service.py): stav dne, odvozené „vynecháno" i týdenní souhrn se počítají tam.
 */

export type HabitKind = "check" | "count" | "duration";
export type HabitState = "done" | "skipped" | "missed" | "open";

export interface HabitEntry {
  id: number;
  date: string;
  state: HabitState;
  value: number | null;
  duration_minutes: number | null;
  note: string | null;
}

export interface Habit {
  id: number;
  name: string;
  kind: HabitKind;
  target_value: number | null;
  unit: string | null;
  target_label: string;
  active: boolean;
  archived_at: string | null;
  created_on: string;
  today: { state: HabitState | null; entry: HabitEntry | null };
  history: { date: string; state: HabitState | null }[];
}

export interface HabitsSummary {
  total: number;
  done: number;
  skipped: number;
  open: number;
  week_done: number;
  week_expected: number;
}

export interface HabitsPayload {
  date: string;
  active: Habit[];
  archived: Habit[];
  summary: HabitsSummary;
}

export const KIND_OPTIONS: { value: HabitKind; label: string; hint: string }[] = [
  { value: "check", label: "Splnit", hint: "Jen splněno / přeskočeno (rehab, skincare, rutina)" },
  { value: "count", label: "Počet", hint: "S hodnotou, např. 2 l vody" },
  { value: "duration", label: "Doba", hint: "S minutami, např. 20 min čtení" },
];

/** Stav slovem i tónem (nikdy jen barvou). */
export const STATE_META: Record<HabitState, { label: string; tone: "success" | "neutral" | "danger" | "info" }> = {
  done: { label: "splněno", tone: "success" },
  skipped: { label: "přeskočeno", tone: "neutral" },
  missed: { label: "vynecháno", tone: "danger" },
  open: { label: "čeká", tone: "info" },
};

export interface HabitForm {
  name: string;
  kind: HabitKind;
  target: string;
  unit: string;
}

export const emptyHabitForm = (): HabitForm => ({ name: "", kind: "check", target: "", unit: "" });

function parseNumber(raw: string): number | null {
  const t = raw.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

/** Formulář → tělo POST /habits; chyba = Error s českou zprávou (server ověřuje znovu). */
export function createBody(form: HabitForm): Record<string, unknown> {
  const name = form.name.trim().replace(/\s+/g, " ");
  if (!name) throw new Error("Doplň název návyku.");
  const body: Record<string, unknown> = { name, kind: form.kind };
  if (form.kind !== "check") {
    const target = parseNumber(form.target);
    if (target !== null) {
      if (Number.isNaN(target) || target <= 0) throw new Error("Cíl musí být kladné číslo.");
      body.target_value = target;
    }
    const unit = form.unit.trim() || (form.kind === "duration" ? "min" : "");
    if (unit) body.unit = unit;
  }
  return body;
}

/** Zápis dne: splněno (s hodnotou / minutami podle druhu) nebo přeskočeno. */
export function entryBody(kind: HabitKind, state: "done" | "skipped", rawValue = ""): Record<string, unknown> {
  const body: Record<string, unknown> = { state };
  if (state !== "done" || kind === "check") return body;
  const n = parseNumber(rawValue);
  if (n === null) return body;
  if (Number.isNaN(n) || n < 0) throw new Error(kind === "duration" ? "Minuty musí být číslo." : "Hodnota musí být číslo.");
  if (kind === "duration") body.duration_minutes = Math.round(n);
  else body.value = n;
  return body;
}

/** Krátký popis hodnoty dne („2,5 l", „25 min"). */
export function entryMeasure(habit: Pick<Habit, "unit">, entry: HabitEntry | null): string {
  if (!entry) return "";
  if (entry.duration_minutes !== null && entry.duration_minutes !== undefined) return `${entry.duration_minutes} min`;
  if (entry.value !== null && entry.value !== undefined) return `${String(entry.value).replace(".", ",")}${habit.unit ? ` ${habit.unit}` : ""}`;
  return "";
}

/** Souhrn z GET /dashboard (`habits` – null = modul vypnutý nebo bez dat). */
export function summaryFrom(data: unknown): HabitsSummary | null {
  const raw = data && typeof data === "object" ? (data as Record<string, unknown>).habits : null;
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const n = (k: string) => (typeof r[k] === "number" && Number.isFinite(r[k]) ? (r[k] as number) : 0);
  return { total: n("total"), done: n("done"), skipped: n("skipped"), open: n("open"), week_done: n("week_done"), week_expected: n("week_expected") };
}

export function percent(done: number, total: number): number {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

/** „2026-10-07" → „st 7. 10." bez převodu přes časovou zónu prohlížeče. */
export function shortDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return `${["ne", "po", "út", "st", "čt", "pá", "so"][d.getUTCDay()]} ${Number(m[3])}. ${Number(m[2])}.`;
}
