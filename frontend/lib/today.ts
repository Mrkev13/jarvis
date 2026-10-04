/**
 * Režim Dnes (Roadmap 4G) – čistá logika zobrazení (testy: today.test.mjs). Data skládá backend (GET /today,
 * today_service.py): pražský den, deduplikace a „další" se počítají tam; tady jen bezpečné převzetí, skupiny
 * časové osy a české popisky. Čas se počítá jednou při načtení – žádný tikající časovač.
 */

export type TodayStatus = "upcoming" | "due" | "past" | "done" | "overdue" | "open";

export interface TodayItem {
  id: string;
  type: string;
  title: string;
  subtitle: string;
  area: string | null;
  date: string | null;
  time: string | null;
  status: TodayStatus;
  priority: number | null;
  severity: "important" | "warning" | "info" | null;
  href: string | null;
  /** Roadmap 4H: co jde udělat přímo z řádku (backend today_service – jen tam, kde to existující pravidla dovolí). */
  actions: TodayActionId[];
}

export type TodayActionId = "complete" | "snooze" | "record_result";
const ACTION_IDS: TodayActionId[] = ["complete", "snooze", "record_result"];

/** Volba odložení spočítaná serverem v pražském čase (žádné datum z prohlížeče). */
export interface SnoozeOption {
  id: string;
  label: string;
  minutes?: number;
  until_local?: string;
}

export interface TodayPayload {
  date: string;
  date_label: string;
  now_local: string;
  summary: { remaining: number; done: number; attention: number; next: (TodayItem & { minutes_until: number | null }) | null };
  timeline: TodayItem[];
  attention: TodayItem[];
  priorities: TodayItem[];
  upcoming: TodayItem[];
  snooze_options: SnoozeOption[];
  errors: Partial<Record<"timeline" | "attention" | "priorities" | "upcoming", string>>;
}

const STATUSES: TodayStatus[] = ["upcoming", "due", "past", "done", "overdue", "open"];
const SEVERITIES = ["important", "warning", "info"] as const;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

/** Odkaz jen v rámci aplikace („/school?exam=3"), nic jiného. */
function safeHref(v: unknown): string | null {
  return typeof v === "string" && v.startsWith("/") && !v.startsWith("//") ? v : null;
}

export function normalizeItem(raw: unknown): TodayItem | null {
  if (!isRecord(raw) || !str(raw.id) || !str(raw.title)) return null;
  const status = STATUSES.includes(raw.status as TodayStatus) ? (raw.status as TodayStatus) : "open";
  const severity = SEVERITIES.includes(raw.severity as (typeof SEVERITIES)[number]) ? (raw.severity as TodayItem["severity"]) : null;
  const time = /^\d{2}:\d{2}$/.test(str(raw.time)) ? str(raw.time) : null;
  return {
    id: str(raw.id),
    type: str(raw.type) || "item",
    title: str(raw.title),
    subtitle: str(raw.subtitle),
    area: str(raw.area) || null,
    date: str(raw.date) || null,
    time,
    status,
    priority: typeof raw.priority === "number" && raw.priority > 0 ? raw.priority : null,
    severity,
    href: safeHref(raw.href),
    actions: Array.isArray(raw.actions) ? ACTION_IDS.filter((a) => (raw.actions as unknown[]).includes(a)) : [],
  };
}

function normalizeSnooze(raw: unknown): SnoozeOption[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).flatMap((o): SnoozeOption[] => {
    const label = str(o.label);
    if (!str(o.id) || !label) return [];
    if (typeof o.minutes === "number" && o.minutes > 0) return [{ id: str(o.id), label, minutes: o.minutes }];
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(str(o.until_local))) return [{ id: str(o.id), label, until_local: str(o.until_local) }];
    return [];
  });
}

function items(raw: unknown): TodayItem[] {
  return Array.isArray(raw) ? raw.map(normalizeItem).filter((x): x is TodayItem => x !== null) : [];
}

export function normalizeToday(raw: unknown): TodayPayload {
  const r = isRecord(raw) ? raw : {};
  const s = isRecord(r.summary) ? r.summary : {};
  const next = normalizeItem(s.next);
  const errors = isRecord(r.errors) ? r.errors : {};
  return {
    date: str(r.date),
    date_label: str(r.date_label),
    now_local: str(r.now_local),
    summary: {
      remaining: Number(s.remaining) || 0,
      done: Number(s.done) || 0,
      attention: Number(s.attention) || 0,
      next: next ? { ...next, minutes_until: isRecord(s.next) && typeof s.next.minutes_until === "number" ? s.next.minutes_until : null } : null,
    },
    timeline: items(r.timeline),
    attention: items(r.attention),
    priorities: items(r.priorities),
    upcoming: items(r.upcoming),
    snooze_options: normalizeSnooze(r.snooze_options),
    errors: Object.fromEntries(
      (["timeline", "attention", "priorities", "upcoming"] as const).filter((k) => typeof errors[k] === "string").map((k) => [k, errors[k] as string]),
    ),
  };
}

/** Časová osa: s časem (chronologicky), „Během dne" (bez času) a „Hotovo" (hotové / proběhlé). */
export function groupTimeline(list: TodayItem[]): { timed: TodayItem[]; untimed: TodayItem[]; done: TodayItem[] } {
  const done = list.filter((it) => it.status === "done");
  const rest = list.filter((it) => it.status !== "done");
  const timed = rest.filter((it) => it.time).sort((a, b) => (a.time! < b.time! ? -1 : a.time! > b.time! ? 1 : 0));
  return { timed, untimed: rest.filter((it) => !it.time), done };
}

/** „za 5 min", „za 2 h", „za 2 h 15 min" (čas do další položky, spočítaný při načtení). */
export function untilLabel(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes) || minutes < 0) return "";
  if (minutes < 1) return "teď";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `za ${m} min`;
  return m ? `za ${h} h ${m} min` : `za ${h} h`;
}

/** 1 položka, 2–4 položky, 5+ / 0 položek. */
export function itemsLabel(n: number): string {
  const word = n === 1 ? "položka" : n >= 2 && n <= 4 ? "položky" : "položek";
  return `${n} ${word}`;
}

/** Stav slovem (nikdy jen barvou). */
export const STATUS_META: Record<TodayStatus, { label: string; tone: "neutral" | "accent" | "warning" | "danger" | "success" | "info" }> = {
  upcoming: { label: "čeká", tone: "neutral" },
  open: { label: "dnes", tone: "info" },
  due: { label: "k vyřízení", tone: "warning" },
  past: { label: "proběhlo", tone: "neutral" },
  done: { label: "hotovo", tone: "success" },
  overdue: { label: "po termínu", tone: "danger" },
};

export const SEVERITY_META: Record<NonNullable<TodayItem["severity"]>, { label: string; tone: "danger" | "warning" | "info" }> = {
  important: { label: "Důležité", tone: "danger" },
  warning: { label: "Varování", tone: "warning" },
  info: { label: "Info", tone: "info" },
};

export const TYPE_LABELS: Record<string, string> = {
  reminder: "Připomínka",
  exam: "Zkouška",
  assignment: "Úkol",
  planner: "Plán",
  notification: "Upozornění",
};

/** Krátké české datum pro „Potom" (pá 16. 10.) – z ISO data bez převodu přes časovou zónu prohlížeče. */
export function shortDate(iso: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!m) return "";
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  const wd = ["ne", "po", "út", "st", "čt", "pá", "so"][d.getUTCDay()];
  return `${wd} ${Number(m[3])}. ${Number(m[2])}.`;
}

export function isEmptyDay(p: TodayPayload): boolean {
  return !p.timeline.length && !p.attention.length && !p.priorities.length && Object.keys(p.errors).length === 0;
}

// ---------- akce z řádku (Roadmap 4H) ----------

/** „reminder:5" → {kind: "reminder", id: 5}; jiné / poškozené → null. */
export function parseRef(ref: string): { kind: string; id: number } | null {
  const m = /^([a-z_]+):(\d+)$/.exec(ref);
  return m ? { kind: m[1], id: Number(m[2]) } : null;
}

/** Druh záznamu pro akci (řádek plánu „assignment:5" je úkol). */
export function entityKind(item: TodayItem): "reminder" | "assignment" | "exam" | null {
  const kind = parseRef(item.id)?.kind;
  return kind === "reminder" || kind === "assignment" || kind === "exam" ? kind : null;
}

/** Přístupný název ovládání vždy s názvem záznamu („Dokončit připomínku: Fyzioterapie"). */
export function actionLabel(item: TodayItem, action: TodayActionId): string {
  const kind = entityKind(item);
  if (action === "complete") return kind === "assignment" ? `Dokončit úkol: ${item.title}` : `Dokončit připomínku: ${item.title}`;
  if (action === "snooze") return `Odložit připomínku: ${item.title}`;
  return `Zapsat výsledek zkoušky: ${item.title}`;
}

/** Hláška po úspěchu (oznamuje se čtečce, ukazuje se v liště nahoře). */
export function successMessage(item: TodayItem, action: TodayActionId, snoozeLabel?: string): string {
  if (action === "snooze") return `Odloženo: ${item.title}${snoozeLabel ? ` (${snoozeLabel})` : ""}.`;
  return entityKind(item) === "assignment" ? `Úkol „${item.title}“ je hotový.` : `Připomínka „${item.title}“ je hotová.`;
}

/**
 * Chyba akce → {zastaralé?, text}. Zastaralé (už hotové / změněné / smazané jinde) = obnovit stránku, žádné
 * opakování; jinak (síť, 5xx) řádek zůstane a nabídne „Zkusit znovu".
 */
export function classifyActionError(status: number | null, detail: unknown): { stale: boolean; message: string } {
  const text = typeof detail === "string" ? detail : isRecord(detail) && typeof detail.message === "string" ? detail.message : "";
  if (status === 400 || status === 404 || status === 409) {
    return { stale: true, message: `${text || "Záznam se mezitím změnil."} Stav jsem obnovil.` };
  }
  return { stale: false, message: "Akci se nepodařilo provést. Zkus to znovu." };
}

/** Pořadí akčních řádků pro posun fokusu po akci: další akční řádek ve stejném seznamu, jinak předchozí. */
export function nextFocusId(ids: string[], current: string): string | null {
  const i = ids.indexOf(current);
  if (i < 0) return null;
  return ids[i + 1] ?? ids[i - 1] ?? null;
}
