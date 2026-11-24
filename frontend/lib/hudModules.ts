/**
 * MRK-134: HUD jádra modulů (components/jarvis/HudCore.tsx) – čistá, deterministická logika (testy: hudModules.test.mjs).
 * Každá funkce vrací segmenty reaktoru (celkem / rozsvícené), náladu a jednu větu stavu. Žádné AI, žádný síťový dotaz;
 * Finance jen vizuál na stránce Finance (nikdy do AI, MRK-60).
 */
import { things } from "./jarvisCore.ts";

export type CoreModel = { total: number; lit: number; mood: "alert" | "done" | "calm"; line: string };

const num = (n: number, digits = 0) => n.toLocaleString("cs-CZ", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

/** 1 návyk / 2–4 návyky / 5+ návyků. */
export function habitsWord(n: number): string {
  return n === 1 ? "návyk" : n >= 2 && n <= 4 ? "návyky" : "návyků";
}

export function habitsCore(s: { total: number; done: number; skipped: number; open: number; week_done: number; week_expected: number }): CoreModel {
  const total = Math.max(0, s.total);
  if (total === 0) return { total: 0, lit: 0, mood: "calm", line: "Na dnešek žádný návyk." };
  const week = s.week_expected > 0 ? ` Týden: ${s.week_done}/${s.week_expected}.` : "";
  if (s.open > 0) return { total, lit: s.done, mood: "calm", line: `Dnes zbývá ${s.open} ${habitsWord(s.open)}.${week}` };
  return { total, lit: s.done, mood: "done", line: `Dnešní návyky jsou vyřízené.${week}` };
}

/** Práce: prstenec = kolik měsíce uběhlo (pražský den), věta s hodinami a výdělkem. */
export function workCore(hours: number | null | undefined, earnings: number | null | undefined, day: number, daysInMonth: number): CoreModel {
  const total = 10;
  const lit = Math.max(0, Math.min(total, Math.round((day / Math.max(1, daysInMonth)) * total)));
  const h = typeof hours === "number" ? hours : 0;
  const e = typeof earnings === "number" ? earnings : 0;
  const line = h > 0 ? `Tento měsíc ${num(h, 1)} h · ${num(e)} Kč.` : "Tento měsíc zatím žádná práce.";
  return { total, lit, mood: "calm", line };
}

/** Finance: „energie systému" – kolik z příjmů pohltily výdaje (10 dílků). Výdaje nad příjmy = pozor. */
export function financeCore(income: number | null | undefined, expenses: number | null | undefined): CoreModel {
  const inc = Math.max(0, Number(income) || 0);
  const exp = Math.max(0, Number(expenses) || 0);
  const total = 10;
  if (inc === 0 && exp === 0) return { total, lit: 0, mood: "calm", line: "Zatím žádné pohyby." };
  if (exp > inc) return { total, lit: total, mood: "alert", line: "Výdaje převyšují příjmy." };
  const lit = Math.round(((inc - exp) / inc) * total);
  return { total, lit, mood: lit >= 3 ? "done" : "calm", line: `Zůstává ${Math.round(((inc - exp) / inc) * 100)} % příjmů.` };
}

export function mffCore(t4: number, fullyBuiltT4: number): CoreModel {
  const total = Math.max(0, t4);
  if (total === 0) return { total: 0, lit: 0, mood: "calm", line: "Zatím žádná T4 postava." };
  const lit = Math.min(total, Math.max(0, fullyBuiltT4));
  return { total, lit, mood: lit === total ? "done" : "calm", line: `Plně postaveno ${lit} z ${total} T4.` };
}

export function wowCore(s: { characters: number; max_level: number; with_target: number; at_target: number }): CoreModel {
  if (s.characters === 0) return { total: 0, lit: 0, mood: "calm", line: "Zatím žádná postava." };
  if (s.with_target === 0) return { total: s.characters, lit: 0, mood: "calm", line: `Nejvyšší level ${s.max_level}. Nastav altům cíl.` };
  const done = s.at_target === s.with_target;
  return {
    total: s.with_target,
    lit: s.at_target,
    mood: done ? "done" : "calm",
    line: `${s.at_target} z ${s.with_target} na cíli · nejvyšší level ${s.max_level}.`,
  };
}

/** WoT: zaměřený tank = první aktivní grind; 10 dílků podle průběhu. */
export function wotCore(grind: { tank: string; progress: number | null; remaining: number } | null): CoreModel {
  if (!grind) return { total: 10, lit: 0, mood: "calm", line: "Žádný aktivní grind – zaměř další tank." };
  const pct = grind.progress;
  const lit = pct === null ? 0 : Math.round(pct / 10);
  const rest = grind.remaining > 0 ? ` Zbývá ${num(grind.remaining)} XP.` : "";
  return { total: 10, lit, mood: pct !== null && pct >= 100 ? "done" : "calm", line: `Zaměřeno: ${grind.tank}${pct === null ? "" : ` – ${pct} %`}.${rest}` };
}

/** „za 2 h 14 min" / „za 5 min" / „teď". */
export function untilLabel(minutes: number): string {
  if (minutes <= 0) return "teď";
  if (minutes < 60) return `za ${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h >= 48) return `za ${Math.round(h / 24)} dny`;
  return m ? `za ${h} h ${m} min` : `za ${h} h`;
}

/**
 * Efektivní termín jako backend (`reminder_service.effective_due`): odložený výskyt opakované připomínky žije jen
 * v `snoozed_until` (due_at zůstává další pravidelný) – platí dřívější z obou. Codex review #104.
 */
export function effectiveDueMs(r: { due_at: string; snoozed_until?: string | null }): number {
  const due = Date.parse(r.due_at);
  const snoozed = r.snoozed_until ? Date.parse(r.snoozed_until) : NaN;
  return Number.isFinite(snoozed) && (!Number.isFinite(due) || snoozed < due) ? snoozed : due;
}

/** Připomínky: odpočet do nejbližší naplánované; prstenec = 12 h (rozsvícené = kolik z nich už uplynulo). */
export function remindersCore(items: { title: string; status: string; state: string; due_at: string; snoozed_until?: string | null }[], now: number): CoreModel {
  const due = items.filter((r) => r.state === "due").length;
  const upcoming = items
    .filter((r) => r.state !== "due" && (r.status === "scheduled" || r.status === "snoozed"))
    .map((r) => ({ r, at: effectiveDueMs(r) }))
    .filter((x) => Number.isFinite(x.at) && x.at >= now)
    .sort((a, b) => a.at - b.at);
  const firing = due > 0 ? `${due} ${things(due)} čeká na vyřízení. ` : "";
  if (!upcoming.length) return { total: 12, lit: due ? 12 : 0, mood: due ? "alert" : "calm", line: `${firing}Žádná další naplánovaná připomínka.`.trim() };
  const minutes = Math.max(0, Math.round((upcoming[0].at - now) / 60000));
  const lit = Math.max(0, Math.min(12, 12 - Math.ceil(minutes / 60)));
  return { total: 12, lit, mood: due ? "alert" : "calm", line: `${firing}Další ${untilLabel(minutes)}: ${upcoming[0].r.title}.` };
}

/** Pražský den v měsíci a počet dní měsíce (pro prstenec Práce). */
export function pragueMonthDay(now: Date = new Date()): { day: number; daysInMonth: number } {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Prague", year: "numeric", month: "numeric", day: "numeric" }).formatToParts(now);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value);
  const y = get("year");
  const m = get("month");
  return { day: get("day"), daysInMonth: new Date(Date.UTC(y, m, 0)).getUTCDate() };
}

/** Kalendář: kam v seřazených řádcích dne patří ryska „teď" (index prvního řádku, který začíná později). */
export function nowLineIndex(startsAt: number[], now: number): number {
  const i = startsAt.findIndex((t) => Number.isFinite(t) && t > now);
  return i === -1 ? startsAt.length : i;
}

/** „HH:MM" v pražském čase a pražské datum YYYY-MM-DD. */
export function pragueNow(now: Date = new Date()): { date: string; time: string } {
  const f = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Prague", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const p = Object.fromEntries(f.formatToParts(now).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}
