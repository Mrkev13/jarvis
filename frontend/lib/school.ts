/**
 * Škola (Roadmap 4B): české popisky stavů/typů, počet dní do termínu a řazení termínů.
 * Čisté funkce bez Reactu (testy: school.test.mjs). Data jsou datum bez času (YYYY-MM-DD) –
 * počítá se s kalendářními dny, takže se nic neposouvá podle časového pásma ani letního času.
 */
import type { Tone } from "./ui.ts";

/** Stavy, které se zobrazují jako hotové/uzavřené (ztlumení). */
export const DONE_STATUSES = ["done", "passed", "completed", "hotovo"];

export function isDoneStatus(status: string | null | undefined): boolean {
  return DONE_STATUSES.includes(String(status ?? "").toLowerCase());
}

/** Zkouška je uzavřená: má výsledek (splněno/nesplněno) nebo je uzavřená bez hodnocení (MRK-14). */
export function isExamClosed(status: string | null | undefined): boolean {
  const s = String(status ?? "").toLowerCase();
  return s === "failed" || s === "closed" || isDoneStatus(s);
}

type Meta = { label: string; tone: Tone };

const ASSIGNMENT_STATUS: Record<string, Meta> = {
  todo: { label: "K vypracování", tone: "neutral" },
  in_progress: { label: "Rozpracováno", tone: "info" },
  done: { label: "Hotovo", tone: "success" },
};

const EXAM_STATUS: Record<string, Meta> = {
  upcoming: { label: "Nadcházející", tone: "neutral" },
  passed: { label: "Splněno", tone: "success" },
  failed: { label: "Nesplněno", tone: "danger" },
  closed: { label: "Uzavřeno", tone: "neutral" },
};

const EXAM_TYPE: Record<string, string> = {
  exam: "Zkouška",
  test: "Test",
  quiz: "Kvíz",
  midterm: "Průběžný test",
  oral: "Ústní zkouška",
  other: "Jiné",
};

/** Stav úkolu → český popisek + tón; neznámý stav zůstane čitelný (neutrálně). */
export function assignmentStatusMeta(status: string | null | undefined): Meta {
  const s = String(status ?? "").toLowerCase();
  return ASSIGNMENT_STATUS[s] ?? { label: isDoneStatus(s) ? "Hotovo" : String(status || "–"), tone: isDoneStatus(s) ? "success" : "neutral" };
}

export function examStatusMeta(status: string | null | undefined): Meta {
  const s = String(status ?? "").toLowerCase();
  return EXAM_STATUS[s] ?? { label: isDoneStatus(s) ? "Splněno" : String(status || "–"), tone: isDoneStatus(s) ? "success" : "neutral" };
}

export function examTypeLabel(type: string | null | undefined): string {
  const t = String(type ?? "").toLowerCase();
  return EXAM_TYPE[t] ?? String(type || "–");
}

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Kalendářní dny od `today` (místní datum prohlížeče, jako dřív) do data YYYY-MM-DD.
 * 0 = dnes, 1 = zítra, záporné = po termínu. Neplatné/chybějící datum → null.
 */
export function daysUntil(value: string | null | undefined, today: Date = new Date()): number | null {
  if (!value) return null;
  const m = DATE_RE.exec(value);
  if (!m) return null;
  const target = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  if (Number.isNaN(target)) return null;
  const base = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - base) / 86_400_000);
}

/** Do kolika dní je termín „blízko" (varování). */
export const SOON_DAYS = 3;

/**
 * Tón termínu a případná předpona („Po termínu" u úkolu, „Proběhlo" u zkoušky bez výsledku).
 * Uzavřené položky jsou vždy neutrální.
 */
export function deadlineMeta(
  days: number | null,
  kind: "assignment" | "exam",
  closed = false,
): { tone: Tone; prefix: string | null; overdue: boolean } {
  if (days === null || closed) return { tone: "neutral", prefix: null, overdue: false };
  if (days < 0) {
    return kind === "assignment"
      ? { tone: "danger", prefix: "Po termínu", overdue: true }
      : { tone: "warning", prefix: "Proběhlo", overdue: true };
  }
  if (days <= SOON_DAYS) return { tone: "warning", prefix: null, overdue: false };
  return { tone: "neutral", prefix: null, overdue: false };
}

/** Řazení podle data vzestupně; položky bez data na konec, při shodě stabilně. */
export function sortByDate<T>(items: T[], getDate: (item: T) => string | null | undefined, descending = false): T[] {
  return items
    .map((item, i) => ({ item, i, d: getDate(item) || null }))
    .sort((a, b) => {
      if (a.d === b.d) return a.i - b.i;
      if (a.d === null) return 1;
      if (b.d === null) return -1;
      const cmp = a.d < b.d ? -1 : 1;
      return descending ? -cmp : cmp;
    })
    .map((x) => x.item);
}

/** Kredity: „1 kredit", „3 kredity", „5 kreditů". */
export function creditsLabel(n: number): string {
  const a = Math.abs(n);
  const word = a === 1 ? "kredit" : a >= 2 && a <= 4 ? "kredity" : "kreditů";
  return `${n} ${word}`;
}

// ---------- MRK-14: uzavření zkoušky s volitelným výsledkem ----------

export const EXAM_OUTCOMES = [
  { value: "passed", label: "Složeno" },
  { value: "failed", label: "Nesloženo" },
  { value: "closed", label: "Bez hodnocení" },
] as const;

export const RESULT_TYPES = [
  { value: "", label: "Bez výsledku", placeholder: "" },
  { value: "percent", label: "Procenta", placeholder: "např. 87,5" },
  { value: "points", label: "Body", placeholder: "např. 42/50" },
  { value: "grade", label: "Známka", placeholder: "např. 1, 2- nebo A" },
  { value: "pass_fail", label: "Splněno / nesplněno", placeholder: "" },
] as const;

export type ExamCloseDraft = { outcome: string; result_type: string; result_value: string };
export const emptyCloseDraft = (): ExamCloseDraft => ({ outcome: "passed", result_type: "", result_value: "" });

const POINTS_RE = /^\d{1,4}([.,]\d{1,2})?(\s*\/\s*\d{1,4}([.,]\d{1,2})?)?$/;
const GRADE_RE = /^([1-5]([+-]|,5)?|[A-Fa-f][+-]?)$/;

/** Stejná pravidla jako backend (school_service.normalize_result); výsledek je nepovinný. */
export function examCloseBody(d: ExamCloseDraft): { ok: true; body: Record<string, string | null> } | { ok: false; error: string } {
  const value = d.result_value.trim();
  const body = { outcome: d.outcome, result_type: d.result_type || null, result_value: value || null };
  if (!d.result_type) return { ok: true, body: { ...body, result_value: null } };
  if (d.result_type === "pass_fail") {
    return d.outcome === "closed" ? { ok: false, error: "Splněno / nesplněno potřebuje výsledek Složeno nebo Nesloženo." } : { ok: true, body: { ...body, result_value: null } };
  }
  if (!value) return { ok: false, error: "Vyplň hodnotu výsledku, nebo zvol „Bez výsledku“." };
  if (d.result_type === "percent") {
    const n = Number(value.replace(",", ".").replace(/%$/, "").trim());
    if (!Number.isFinite(n) || n < 0 || n > 100) return { ok: false, error: "Procenta: číslo 0–100." };
  }
  if (d.result_type === "points" && !POINTS_RE.test(value)) return { ok: false, error: "Body: číslo, případně „42/50“." };
  if (d.result_type === "grade" && !GRADE_RE.test(value)) return { ok: false, error: "Známka: 1–5 (třeba 2-) nebo A–F." };
  return { ok: true, body };
}

/** Výsledek k zobrazení („87,5 %", „42/50 b", „známka 2-"); splněno/nesplněno říká už stav. */
export function examResultLabel(type: string | null | undefined, value: string | null | undefined): string | null {
  if (!type || !value || type === "pass_fail") return null;
  if (type === "percent") return `${value} %`;
  if (type === "points") return `${value} b`;
  if (type === "grade") return `známka ${value}`;
  return value;
}

// ---------- MRK-75: úprava a archivace předmětů ----------

export type SchoolSubject = {
  id: number;
  name: string;
  code: string;
  semester: string;
  credits: number;
  active: boolean;
};

export type SubjectDraft = { name: string; code: string; semester: string; credits: string };

/** Předměty, které se nabízejí pro nové úkoly, zkoušky a mapování (archivované ne). */
export function offeredSubjects<T extends { active?: boolean }>(subjects: T[]): T[] {
  return subjects.filter((s) => s.active !== false);
}

/** Seznam v sekci Předměty: aktivní; s přepínačem i archivované (až za aktivními). */
export function visibleSubjects(subjects: SchoolSubject[], showArchived: boolean): SchoolSubject[] {
  const active = subjects.filter((s) => s.active);
  return showArchived ? [...active, ...subjects.filter((s) => !s.active)] : active;
}

export function subjectDraftFrom(s: SchoolSubject): SubjectDraft {
  return { name: s.name, code: s.code ?? "", semester: s.semester ?? "", credits: String(s.credits ?? 0) };
}

/** Jen změněná pole pro PATCH; null = neplatný formulář (prázdný název, kredity mimo 0–99). */
export function subjectPatch(original: SchoolSubject, draft: SubjectDraft): Partial<SchoolSubject> | null {
  const name = draft.name.trim();
  const credits = draft.credits.trim() === "" ? 0 : Number(draft.credits);
  if (!name || !Number.isInteger(credits) || credits < 0 || credits > 99) return null;
  const next = { name, code: draft.code.trim(), semester: draft.semester.trim(), credits };
  const patch: Partial<SchoolSubject> = {};
  for (const key of ["name", "code", "semester", "credits"] as const) {
    if (next[key] !== (original[key] ?? (key === "credits" ? 0 : ""))) (patch as Record<string, unknown>)[key] = next[key];
  }
  return patch;
}
