/**
 * Připomínky (Roadmap 3.0 Phase D) – čisté pomocné funkce pro stránku /reminders.
 *
 * Backend ukládá UTC a vrací i pražské popisky (`due_label`, `next_label`). Časy do formulářů posíláme
 * jako pražský „nástěnný" čas `YYYY-MM-DDTHH:MM` (`due_local`) – nezáleží na časovém pásmu prohlížeče.
 * Modul je bez závislostí (testuje se přes `node --test`, viz reminders.test.mjs).
 */
export const PRAGUE_TZ = "Europe/Prague";

export type ReminderStatus = "scheduled" | "fired" | "done" | "cancelled";

export interface Reminder {
  id: number;
  title: string;
  note: string;
  status: ReminderStatus | string;
  state: "due" | ReminderStatus | string;
  due_at: string;
  due_local: string;
  due_label: string;
  next_label: string;
  snoozed_label?: string | null;
  recurrence: "none" | "daily" | "weekly" | string;
  weekdays?: string | null;
  local_time?: string | null;
  recurrence_label: string;
  last_fired_label?: string | null;
}

export type ReminderForm = {
  title: string;
  mode: "once" | "daily" | "weekly";
  dueLocal: string; // datetime-local hodnota, vykládá se jako pražský čas
  timeLocal: string; // HH:MM pro opakování
  weekdays: number[]; // 0 = pondělí … 6 = neděle
  note: string;
};

export const WEEKDAY_LABELS = ["po", "út", "st", "čt", "pá", "so", "ne"];

/** Části pražského data/času pro daný okamžik (bez ohledu na pásmo prohlížeče). */
export function pragueParts(date: Date): { y: string; mo: string; d: string; h: string; mi: string } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: PRAGUE_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return { y: get("year"), mo: get("month"), d: get("day"), h: get("hour"), mi: get("minute") };
}

/** Hodnota pro <input type="datetime-local"> v pražském čase. */
export function toPragueInputValue(date: Date): string {
  const p = pragueParts(date);
  return `${p.y}-${p.mo}-${p.d}T${p.h}:${p.mi}`;
}

/** Výchozí čas nové připomínky: za hodinu, zaokrouhleno nahoru na čtvrthodinu (Praha). */
export function defaultDueLocal(now: Date = new Date()): string {
  const t = new Date(now.getTime() + 60 * 60 * 1000);
  const quarter = 15 * 60 * 1000;
  return toPragueInputValue(new Date(Math.ceil(t.getTime() / quarter) * quarter));
}

/** Formát UTC okamžiku v pražském čase (např. pro chybové hlášky / detail). */
export function formatPrague(isoUtc: string | null | undefined): string {
  if (!isoUtc) return "–";
  const d = new Date(isoUtc);
  if (Number.isNaN(d.getTime())) return isoUtc;
  return d.toLocaleString("cs-CZ", {
    timeZone: PRAGUE_TZ,
    weekday: "short",
    day: "numeric",
    month: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function emptyForm(now: Date = new Date()): ReminderForm {
  return { title: "", mode: "once", dueLocal: defaultDueLocal(now), timeLocal: "08:00", weekdays: [], note: "" };
}

/** Tělo POST /reminders z formuláře; chyba = text pro uživatele. */
export function createBody(form: ReminderForm): Record<string, unknown> {
  const title = form.title.trim();
  if (!title) throw new Error("Napiš, co připomenout.");
  const base: Record<string, unknown> = { title, note: form.note.trim() || undefined };
  if (form.mode === "once") {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(form.dueLocal)) throw new Error("Vyber datum a čas.");
    return { ...base, recurrence: "none", due_local: form.dueLocal };
  }
  if (!/^\d{2}:\d{2}$/.test(form.timeLocal)) throw new Error("Vyber čas opakování.");
  if (form.mode === "weekly") {
    if (!form.weekdays.length) throw new Error("Vyber aspoň jeden den.");
    return {
      ...base,
      recurrence: "weekly",
      time_local: form.timeLocal,
      weekdays: [...new Set(form.weekdays)].sort((a, b) => a - b).join(","),
    };
  }
  return { ...base, recurrence: "daily", time_local: form.timeLocal };
}

export interface SnoozeOption {
  label: string;
  body: { minutes?: number; until_local?: string };
}

/** Rychlé odložení: +15 min, +1 h, zítra 8:00 (Praha). */
export function snoozeOptions(now: Date = new Date()): SnoozeOption[] {
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const p = pragueParts(tomorrow);
  return [
    { label: "+15 min", body: { minutes: 15 } },
    { label: "+1 h", body: { minutes: 60 } },
    { label: "Zítra 8:00", body: { until_local: `${p.y}-${p.mo}-${p.d}T08:00` } },
  ];
}

export interface ReminderGroups {
  due: Reminder[];
  upcoming: Reminder[];
  history: Reminder[];
}

/** Zazněné / splatné nahoře, pak nadcházející; hotové a zrušené zvlášť. */
export function groupReminders(items: Reminder[]): ReminderGroups {
  const due: Reminder[] = [];
  const upcoming: Reminder[] = [];
  const history: Reminder[] = [];
  for (const r of items) {
    if (r.status === "done" || r.status === "cancelled") history.push(r);
    else if (r.state === "due") due.push(r);
    else upcoming.push(r);
  }
  const byDue = (a: Reminder, b: Reminder) => a.due_at.localeCompare(b.due_at);
  return { due: due.sort(byDue), upcoming: upcoming.sort(byDue), history };
}

export function stateLabel(r: Reminder): string {
  if (r.status === "done") return "Hotovo";
  if (r.status === "cancelled") return "Zrušeno";
  if (r.state === "due") return "Teď";
  return r.recurrence === "none" ? "Naplánováno" : "Opakuje se";
}
