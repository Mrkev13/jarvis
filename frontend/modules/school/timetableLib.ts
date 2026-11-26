/**
 * MRK-41: ruční týdenní rozvrh – čisté funkce (testy: timetableLib.test.mjs). Data = backend `GET /calendar/timetable`
 * (modules/calendar/timetable.py): hodiny jsou opakované události Kalendáře zdroje „Rozvrh“.
 */
export type TimetableKind = "lecture" | "seminar" | "exercise" | "lab";
export type TimetableException = { date: string; action: "cancel" | "move"; starts_at: string | null; ends_at: string | null };
export type TimetableEntry = {
  id: number;
  subject_id: number | null;
  subject_name: string | null;
  title: string;
  kind: TimetableKind | null;
  kind_label: string | null;
  room: string | null;
  weekday: number;
  weekday_label: string;
  start: string;
  end: string;
  valid_from: string;
  valid_until: string;
  exceptions: TimetableException[];
};
export type TimetableResponse = { entries: TimetableEntry[]; kinds: Record<TimetableKind, string> };

export const WEEKDAYS = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"];
export const KIND_OPTIONS: { value: TimetableKind; label: string }[] = [
  { value: "lecture", label: "Přednáška" },
  { value: "seminar", label: "Seminář" },
  { value: "exercise", label: "Cvičení" },
  { value: "lab", label: "Laboratoř" },
];

export type TimetableDraft = {
  subject_id: string; kind: TimetableKind; weekday: string; start: string; end: string; room: string;
  valid_from: string; valid_until: string;
};

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Výchozí platnost = aktuální semestr: zimní 1. 10. – 31. 1., letní 15. 2. – 31. 5.; jinak od dneška 4 měsíce. */
export function defaultSemester(todayIso: string): { valid_from: string; valid_until: string } {
  const [y, m] = todayIso.split("-").map(Number);
  if (m >= 9 || m === 1) {
    const start = m === 1 ? y - 1 : y;
    return { valid_from: `${start}-10-01`, valid_until: `${start + 1}-01-31` };
  }
  if (m >= 2 && m <= 5) return { valid_from: `${y}-02-15`, valid_until: `${y}-05-31` };
  const from = new Date(`${todayIso}T12:00:00`);
  const until = new Date(from);
  until.setMonth(until.getMonth() + 4);
  return { valid_from: todayIso, valid_until: iso(until) };
}

export function emptyDraft(todayIso: string, subjectId = ""): TimetableDraft {
  return { subject_id: subjectId, kind: "lecture", weekday: "0", start: "09:00", end: "10:30", room: "", ...defaultSemester(todayIso) };
}

export function draftFrom(e: TimetableEntry): TimetableDraft {
  return {
    subject_id: e.subject_id != null ? String(e.subject_id) : "", kind: e.kind ?? "lecture", weekday: String(e.weekday),
    start: e.start, end: e.end, room: e.room ?? "", valid_from: e.valid_from, valid_until: e.valid_until,
  };
}

/** Kontrola formuláře (backend kontroluje znovu); null = v pořádku. */
export function validateDraft(d: TimetableDraft): string | null {
  if (!d.subject_id) return "Vyber předmět.";
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(d.start) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(d.end)) return "Čas ve tvaru HH:MM.";
  if (d.end <= d.start) return "Konec musí být po začátku.";
  if (!d.valid_from || !d.valid_until) return "Vyplň, od kdy do kdy rozvrh platí.";
  if (d.valid_until < d.valid_from) return "„Platí do“ musí být po „Platí od“.";
  return null;
}

export function draftPayload(d: TimetableDraft) {
  return {
    subject_id: Number(d.subject_id), kind: d.kind, weekday: Number(d.weekday), start: d.start, end: d.end,
    room: d.room.trim() || null, valid_from: d.valid_from, valid_until: d.valid_until,
  };
}

/** Rozvrh po dnech: jen dny, kdy něco je; v rámci dne podle začátku. */
export function byWeekday(entries: TimetableEntry[]): { weekday: number; label: string; entries: TimetableEntry[] }[] {
  const out: { weekday: number; label: string; entries: TimetableEntry[] }[] = [];
  for (let wd = 0; wd < 7; wd++) {
    const day = entries.filter((e) => e.weekday === wd).sort((a, b) => a.start.localeCompare(b.start) || a.id - b.id);
    if (day.length) out.push({ weekday: wd, label: WEEKDAYS[wd], entries: day });
  }
  return out;
}

/** „zrušeno 12. 10.“ / „12. 10. → 21. 10. 13:00“. */
export function exceptionLabel(x: TimetableException): string {
  const d = (s: string) => { const [, m, day] = s.slice(0, 10).split("-"); return `${Number(day)}. ${Number(m)}.`; };
  if (x.action === "cancel") return `zrušeno ${d(x.date)}`;
  const t = x.starts_at ? x.starts_at.slice(11, 16) : "";
  return `${d(x.date)} → ${x.starts_at ? d(x.starts_at) : "?"} ${t}`.trim();
}

/** Další datum (YYYY-MM-DD) od `fromIso` včetně, kdy je den v týdnu `weekday` (0 = pondělí). */
export function nextWeekday(fromIso: string, weekday: number): string {
  const d = new Date(`${fromIso}T12:00:00`);
  const current = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() + ((weekday - current + 7) % 7));
  return iso(d);
}
