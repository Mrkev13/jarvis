/**
 * Sdílené formátování pro UI (Roadmap 4A) – jedna definice místo kopií po stránkách.
 *
 * Česká lokalizace (cs-CZ). Formátuje jen zobrazení: časové významy (UTC v DB, pražské „dnes")
 * řeší backend a lib/reminders.ts; tady se nic nepřepočítává mezi pásmy kromě explicitní Europe/Prague.
 * Bez závislostí (testy: format.test.mjs).
 */
export const LOCALE = "cs-CZ";
export const PRAGUE_TZ = "Europe/Prague";
export const EMPTY = "–";

function isNum(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** 12 345,5 – max. 2 desetinná místa; chybějící hodnota → „–". */
export function formatNumber(value: number | null | undefined, maxFractionDigits = 2): string {
  if (!isNum(value)) return EMPTY;
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: maxFractionDigits }).format(value);
}

/** 4 821 Kč (bez haléřů, pokud nejsou potřeba). */
export function formatCzk(value: number | null | undefined): string {
  if (!isNum(value)) return EMPTY;
  return `${formatNumber(value, Math.abs(value) >= 100 ? 0 : 2)} Kč`;
}

/** 12,5 h */
export function formatHours(value: number | null | undefined): string {
  if (!isNum(value)) return EMPTY;
  return `${formatNumber(value, 1)} h`;
}

/** 42 % (zaokrouhleno, oříznuto na 0–100 jen když clamp=true). */
export function formatPercent(value: number | null | undefined, clamp = false): string {
  if (!isNum(value)) return EMPTY;
  const v = clamp ? Math.max(0, Math.min(100, value)) : value;
  return `${Math.round(v)} %`;
}

/** Znaménko pro změny: +12 %, −4 h (skutečné minus). */
export function formatSigned(value: number, formatted: string): string {
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `−${formatted.replace(/^-/, "")}`;
  return formatted;
}

/** Česká množná čísla: plural(1, "den", "dny", "dní"). */
export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n);
  if (a === 1) return one;
  if (a >= 2 && a <= 4) return few;
  return many;
}

/** „3 dny", „1 den", „0 dní". */
export function formatDays(n: number): string {
  return `${n} ${plural(n, "den", "dny", "dní")}`;
}

/** Datum (YYYY-MM-DD nebo ISO) → „5. 10. 2026". Datum bez času se nepřepočítává mezi pásmy. */
export function formatDate(value: string | null | undefined, withYear = true): string {
  if (!value) return EMPTY;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (m) {
    const [, y, mo, d] = m;
    return withYear ? `${Number(d)}. ${Number(mo)}. ${y}` : `${Number(d)}. ${Number(mo)}.`;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat(LOCALE, {
    timeZone: PRAGUE_TZ, day: "numeric", month: "numeric", ...(withYear ? { year: "numeric" } : {}),
  }).formatToParts(date);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return withYear ? `${get("day")}. ${get("month")}. ${get("year")}` : `${get("day")}. ${get("month")}.`;
}

/** Okamžik (ISO s offsetem / Z) → „5. 10. 8:05" v pražském čase. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat(LOCALE, {
    timeZone: PRAGUE_TZ, day: "numeric", month: "numeric", hour: "numeric", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("day")}. ${get("month")}. ${get("hour")}:${get("minute")}`;
}

/** „dnes", „zítra", „za 3 dny", „před 2 dny" podle počtu dní (z backendu, ne z hodin prohlížeče). */
export function formatRelativeDays(daysLeft: number): string {
  if (daysLeft === 0) return "dnes";
  if (daysLeft === 1) return "zítra";
  if (daysLeft === -1) return "včera";
  if (daysLeft > 1) return `za ${formatDays(daysLeft)}`;
  return `před ${formatDays(-daysLeft)}`;
}
