/**
 * MRK-78: Řídicí centrum jako jedna hlavní denní obrazovka – čistý výběr dat pro widgety „Co hoří", „Můj den"
 * a „Od včera" (testy: controlCenter.test.mjs). Nic se tu nepočítá znovu: pražský den, stav položek a „další"
 * dodává backend (GET /today, /dashboard, /timeline/day, /changes); tady jen sloučení bez duplicit a ořez.
 *
 * Každý záznam se na obrazovce ukáže jednou: co je v dnešní časové ose, patří do „Můj den"; „Co hoří" bere
 * jen pozornost (po termínu, upozornění) a školní termíny do 7 dní, které v ose nejsou.
 */
import type { ChangeItem } from "./changes.ts";
import type { TodayItem, TodayPayload } from "./today.ts";

/** Školní termín z GET /dashboard (school_integrations.get_upcoming). */
export interface UpcomingDeadline {
  type: string;
  id: number;
  key?: string;
  title: string;
  area: string;
  date: string;
  days_left: number;
  overdue: boolean;
  subject_name?: string;
}

export interface BurningItem {
  ref: string;
  title: string;
  meta: string;
  kind: "attention" | "deadline";
  type: string;
  tone: "danger" | "warning" | "neutral";
  label: string;
  href: string | null;
}

export interface FreeBlockLike {
  local_start: string;
  local_end: string;
  duration_minutes: number;
}

export const BURNING_LIMIT = 6;
export const BURNING_DAYS = 7;
export const DAY_LIMIT = 4;
export const CHANGES_PREVIEW = 5;

const DEADLINE_TYPES = ["assignment", "exam", "calendar_event"];
const DEADLINE_HREF: Record<string, string> = {
  assignment: "/school?assignment={id}",
  exam: "/school?exam={id}",
  calendar_event: "/calendar?event={id}",
};

function deadlineRef(u: UpcomingDeadline): string {
  return `${u.type}:${u.key ?? u.id}`;
}

function daysLabel(days: number, overdue: boolean): string {
  if (overdue) return days === -1 ? "včera" : `před ${Math.abs(days)} dny`;
  if (days === 0) return "dnes";
  if (days === 1) return "zítra";
  return `za ${days} ${days >= 2 && days <= 4 ? "dny" : "dní"}`;
}

function attentionTone(it: TodayItem): BurningItem["tone"] {
  if (it.status === "overdue" || it.severity === "important") return "danger";
  return it.severity === "warning" ? "warning" : "neutral";
}

/**
 * „Co hoří": nejdřív pozornost z /today (pořadí serveru), pak školní termíny do 7 dní z /dashboard podle
 * blízkosti. Položky z dnešní osy a duplicity (stejný ref) se vynechají; nejvýš `limit` řádků.
 */
export function burningItems(
  today: Pick<TodayPayload, "attention" | "timeline"> | null,
  upcoming: UpcomingDeadline[] | null | undefined,
  limit = BURNING_LIMIT,
): BurningItem[] {
  const seen = new Set((today?.timeline ?? []).map((it) => it.id));
  const out: BurningItem[] = [];
  for (const it of today?.attention ?? []) {
    if (seen.has(it.id)) continue;
    seen.add(it.id);
    out.push({
      ref: it.id,
      title: it.title,
      meta: it.subtitle,
      kind: "attention",
      type: it.type,
      tone: attentionTone(it),
      label: it.status === "overdue" ? "po termínu" : it.severity === "important" ? "důležité" : "pozor",
      href: it.href,
    });
  }
  const deadlines = (upcoming ?? [])
    .filter((u) => DEADLINE_TYPES.includes(u.type) && Number.isFinite(u.days_left) && u.days_left <= BURNING_DAYS)
    .sort((a, b) => a.days_left - b.days_left);
  for (const u of deadlines) {
    const ref = deadlineRef(u);
    // Moodle událost má v /today ref podle id události, ne podle klíče výskytu
    if (seen.has(ref) || seen.has(`${u.type}:${u.id}`)) continue;
    seen.add(ref);
    out.push({
      ref,
      title: u.title,
      meta: u.subject_name ?? "",
      kind: "deadline",
      type: u.type,
      tone: u.overdue ? "danger" : u.days_left <= 1 ? "warning" : "neutral",
      label: daysLabel(u.days_left, u.overdue),
      href: DEADLINE_HREF[u.type]?.replace("{id}", String(u.id)) ?? null,
    });
  }
  return out.slice(0, limit);
}

/**
 * „Můj den": nevyřízené položky dnešní osy (časové chronologicky, pak během dne); „další" jde první.
 * `excludeTypes`: typy, které ukazuje jiný widget (MRK-104: návyky mají vlastní kartu se Splnit).
 */
export function dayItems(
  today: Pick<TodayPayload, "timeline" | "summary"> | null,
  limit = DAY_LIMIT,
  excludeTypes: readonly string[] = [],
): TodayItem[] {
  if (!today) return [];
  const open = today.timeline.filter((it) => it.status !== "done" && it.status !== "past" && !excludeTypes.includes(it.type));
  const timed = open.filter((it) => it.time).sort((a, b) => (a.time! < b.time! ? -1 : a.time! > b.time! ? 1 : 0));
  const list = [...timed, ...open.filter((it) => !it.time)];
  const next = today.summary.next?.id;
  const ordered = next ? [...list.filter((it) => it.id === next), ...list.filter((it) => it.id !== next)] : list;
  return ordered.slice(0, limit);
}

/** Nejbližší volno, které ještě neskončilo; běžící volno se ukáže od teď („HH:MM" pražsky z backendu). */
export function nextFreeBlock<T extends FreeBlockLike>(blocks: T[] | null | undefined, nowLocal: string): (T & { from: string }) | null {
  if (!/^\d{2}:\d{2}$/.test(nowLocal)) return null;
  const block = (blocks ?? []).find((b) => b.local_end > nowLocal);
  if (!block) return null;
  return { ...block, from: block.local_start < nowLocal ? nowLocal : block.local_start };
}

/** „Od včera": začátek okna = 24 h zpět, zaokrouhleno dolů na minutu (URL se nemění při každém vykreslení). */
export function changesSince(now: number = Date.now()): string {
  return new Date(Math.floor((now - 24 * 3_600_000) / 60_000) * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function changesPreviewPath(now: number = Date.now()): string {
  return `/changes?${new URLSearchParams({ since: changesSince(now), limit: String(CHANGES_PREVIEW) })}`;
}

/** Nejnovější změny první, nejvýš `limit` (backend řadí stejně; tady jen pojistka a ořez). */
export function latestChanges(items: ChangeItem[] | null | undefined, limit = CHANGES_PREVIEW): ChangeItem[] {
  return [...(items ?? [])].sort((a, b) => (a.occurred_at < b.occurred_at ? 1 : a.occurred_at > b.occurred_at ? -1 : 0)).slice(0, limit);
}
