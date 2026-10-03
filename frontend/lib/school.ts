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

/** Zkouška je uzavřená, když už má výsledek (splněno/nesplněno). */
export function isExamClosed(status: string | null | undefined): boolean {
  const s = String(status ?? "").toLowerCase();
  return s === "failed" || isDoneStatus(s);
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
