/**
 * Jarvis companion (MRK-16) – čistý, deterministický stavový stroj malého robota v rámu aplikace.
 * Žádný React, žádné časovače: komponenta posílá události (`stepCompanion`) a jediný časovač
 * nastavuje podle `nextCompanionDeadline`. Všechno časování je v `COMPANION_TIMING`.
 *
 * Priorita zobrazeného stavu: error/warning > success > listening/thinking > walking > idle.
 * - nálady (listening/thinking/warning) trvají, dokud je zdroj hlásí,
 * - success/error jsou krátké záblesky (pulse), pak se vrátí k náladě nebo k idle,
 * - chůze jen mezi kotvami ve vyhrazeném pruhu dole; vyšší priorita ji zastaví na místě
 *   a po odeznění se dojde k původní kotvě,
 * - bez roamingu (reduced motion) stojí na pevné kotvě, výrazy se ale mění dál.
 * - obsazenost kotev (karty, ovládací prvky pod nimi) měří komponenta jen v určitých chvílích
 *   (změna rozvržení, dosednutí po scrollu, jedna pozdější kontrola) a posílá `occupancy`;
 *   obsazenou kotvu stroj opustí na nejbližší volnou, když jsou obsazené všechny, jen vykoukne
 *   od pravého okraje (`edge`), a když ani tam není místo, dočasně se schová.
 *   Během scrollu je průhledný a přestaví se, dokud ho není vidět.
 */
import type { JarvisState } from "./jarvisAvatar.ts";

export const COMPANION_STATES = ["hidden", "idle", "walking", "listening", "thinking", "success", "warning", "error"] as const;
export type CompanionState = (typeof COMPANION_STATES)[number];

export const COMPANION_PRIORITY: Record<CompanionState, number> = {
  hidden: 0,
  idle: 1,
  walking: 2,
  listening: 3,
  thinking: 3,
  success: 4,
  warning: 5,
  error: 5,
};

export const COMPANION_TIMING = {
  successMs: 2600,
  errorMs: 3200,
  bubbleMs: 2400,
  /** Stejná bublina se nezopakuje dřív – žádný spam. */
  bubbleCooldownMs: 20_000,
  /** Klidný přesun v nečinnosti – základ; skutečné pauzy se deterministicky střídají (`RELOCATION_PAUSE_OFFSETS`). */
  relocateEveryMs: 44_000,
  /** Cestovní (ustálená) rychlost; rozjezd a dojezd jsou pomalejší. */
  walkPxPerSecond: 72,
  /** Délka jednoho kroku – z ní a z rychlosti plyne délka krokového cyklu, aby nohy „neklouzaly". */
  stridePx: 18,
  /** Otočení a nakročení před odchodem (stojí na místě). */
  departMs: 280,
  /** Doběhnutí po příchodu (ještě „walking", už stojí na kotvě). */
  settleMs: 360,
  /** Podíl cesty, kdy zrychluje (a stejný podíl na konci, kdy zpomaluje). */
  accelFraction: 0.22,
  minTravelMs: 900,
  maxTravelMs: 7000,
  /** Scroll se považuje za ukončený po této pauze; pak se znovu změří volné kotvy. */
  scrollSettleMs: 220,
  /** Jedna pozdější kontrola po změně rozvržení – obsah stránky se často načítá až po vykreslení. */
  recheckAfterLayoutMs: 1200,
} as const;

/** Rozměr postavičky a vyhrazeného pruhu dole (px). */
export const COMPANION_BOX = { width: 64, height: 84, margin: 24, bottom: 12, laneHeight: 104 } as const;
/** Pod touto šířkou (tablet, mobil) se companion nezobrazuje – žádné potulování na 390 px. */
export const COMPANION_MIN_VIEWPORT = 1024;
/** Kolik z postavičky vykoukne od pravého okraje, když jsou všechny kotvy obsazené (px). */
export const COMPANION_PEEK_WIDTH = 26;
/** Šířka sloupce konverzací na /ai (Tailwind `w-72`). */
const AI_COLUMN_WIDTH = 288;

export const COMPANION_PREF_KEY = "standa-hub:jarvis-companion:v1";

export type AnchorId = "left" | "left-mid" | "center" | "right-mid" | "right" | "ai" | "edge";
export interface CompanionAnchor {
  id: AnchorId;
  x: number;
  y: number;
  /** Viditelná šířka (u `edge` jen vykukující část). */
  width: number;
  /** Nouzové vykouknutí od okraje – není cílem klidných přesunů. */
  peek?: boolean;
  /** Vyhrazené místo (dok na /ai) – obsazenost se neměří. */
  reserved?: boolean;
}
export interface CompanionViewport {
  width: number;
  height: number;
  /** Šířka levého panelu navigace. */
  sidebar: number;
}
export type CompanionLayout = "default" | "ai";

/** Pauzy mezi klidnými přesuny se střídají (± pár sekund) – živější, ale stále deterministické. */
export const RELOCATION_PAUSE_OFFSETS: readonly number[] = [0, 9_000, -5_000, 4_000];
/** Krokový cyklus (dva kroky) synchronizovaný s cestovní rychlostí. */
export const WALK_STEP_CYCLE_MS = Math.round(((2 * COMPANION_TIMING.stridePx) / COMPANION_TIMING.walkPxPerSecond) * 1000);
/** Pevná kotva bez roamingu (reduced motion). */
const FIXED_ANCHOR: AnchorId = "right";

const BUBBLES: Partial<Record<CompanionState, string>> = {
  listening: "Poslouchám…",
  thinking: "Moment, přemýšlím…",
  success: "Hotovo!",
  warning: "Čekám na tvoje potvrzení.",
  error: "Tohle se nepovedlo.",
};

export type WalkPhase = "depart" | "travel" | "arrive";

export interface CompanionWalk {
  from: number;
  to: number;
  target: AnchorId;
  start: number;
  /** otočení/nakročení → cesta → doběhnutí */
  departMs: number;
  travelMs: number;
  settleMs: number;
  /** celkem (depart + travel + settle) */
  duration: number;
}

export interface CompanionMachine {
  state: CompanionState;
  enabled: boolean;
  roaming: boolean;
  anchors: CompanionAnchor[];
  anchor: AnchorId;
  x: number;
  facing: "left" | "right";
  mood: JarvisState;
  flash: { kind: "success" | "error"; until: number } | null;
  walk: CompanionWalk | null;
  pendingTarget: AnchorId | null;
  relocationIndex: number;
  /** Směr klidných přesunů po sousedních kotvách (−1 doleva, +1 doprava); na konci se otočí. */
  relocationDir: -1 | 1;
  walkPhase: WalkPhase | null;
  nextRelocateAt: number;
  bubble: { text: string; until: number } | null;
  lastBubbleAt: Partial<Record<CompanionState, number>>;
  /** Kotvy, pod kterými je teď obsah (poslední měření). */
  occupied: AnchorId[];
  /** false = poloha ještě není ověřená (po změně rozvržení / během scrollu) → průhledný. */
  measured: boolean;
  /** Všechno obsazené včetně okraje → dočasně schovaný. */
  parked: boolean;
  scrollUntil: number | null;
  checkAt: number | null;
  /** Roste, když má komponenta změřit obsazenost kotev. */
  measureRequest: number;
}

export type CompanionEvent =
  | { type: "tick"; now: number }
  | { type: "mood"; mood: JarvisState; now: number }
  | { type: "pulse"; kind: "success" | "error"; now: number }
  | { type: "enabled"; value: boolean; now: number }
  | { type: "roaming"; value: boolean; now: number }
  | { type: "layout"; anchors: CompanionAnchor[]; now: number }
  | { type: "goto"; target: AnchorId; now: number }
  | { type: "scroll"; now: number }
  | { type: "stroll"; now: number }
  | { type: "occupancy"; occupied: AnchorId[]; now: number };

// ---------- rozvržení ----------

export function companionLayout(pathname: string | null): CompanionLayout {
  return pathname?.startsWith("/ai") ? "ai" : "default";
}

export function companionVisible({ width, enabled }: { width: number; enabled: boolean }): boolean {
  return enabled && width >= COMPANION_MIN_VIEWPORT;
}

function clampX(x: number, vp: CompanionViewport): number {
  return Math.round(Math.min(Math.max(x, vp.sidebar), vp.width - COMPANION_BOX.width));
}

/** Bezpečné kotvy v pruhu pod obsahem (vpravo od navigace, uvnitř viewportu). */
export function companionAnchors(vp: CompanionViewport, layout: CompanionLayout): CompanionAnchor[] {
  if (vp.width < COMPANION_MIN_VIEWPORT) return [];
  const y = Math.max(0, vp.height - COMPANION_BOX.bottom - COMPANION_BOX.height);
  if (layout === "ai") {
    const x = clampX(vp.sidebar + (AI_COLUMN_WIDTH - COMPANION_BOX.width) / 2, vp);
    return [{ id: "ai", x, y, width: COMPANION_BOX.width, reserved: true }];
  }
  // pět rovnoměrných kotev → klidné přesuny jsou krátké skoky k sousedovi, ne přejezd přes celou obrazovku
  const first = vp.sidebar + COMPANION_BOX.margin;
  const last = vp.width - COMPANION_BOX.margin - COMPANION_BOX.width;
  const width = COMPANION_BOX.width;
  const ids: AnchorId[] = ["left", "left-mid", "center", "right-mid", "right"];
  return [
    ...ids.map((id, i) => ({ id, x: clampX(first + ((last - first) * i) / (ids.length - 1), vp), y, width })),
    { id: "edge", x: vp.width - COMPANION_PEEK_WIDTH, y, width: COMPANION_PEEK_WIDTH, peek: true },
  ];
}

export function companionBubbleSide(x: number, viewportWidth: number): "left" | "right" {
  return x + COMPANION_BOX.width / 2 > viewportWidth / 2 ? "left" : "right";
}

interface Rect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function anchorRect(a: CompanionAnchor): Rect {
  return { left: a.x, right: a.x + a.width, top: a.y, bottom: a.y + COMPANION_BOX.height };
}

/**
 * Body, ve kterých komponenta zjišťuje, co leží pod kotvou (mřížka 3 × 3 uvnitř viditelné plochy).
 * Jen pár `elementsFromPoint` při měření – žádné procházení DOM ani observery.
 */
export function anchorSamplePoints(a: CompanionAnchor): { x: number; y: number }[] {
  const inset = 4;
  const r = anchorRect(a);
  const xs = [r.left + inset, (r.left + r.right) / 2, r.right - inset];
  const ys = [r.top + inset, (r.top + r.bottom) / 2, r.bottom - inset];
  return ys.flatMap((y) => xs.map((x) => ({ x: Math.round(x), y: Math.round(y) })));
}

/** Kotvy, kde je pod některým vzorkovým bodem obsah. Vyhrazený dok se neměří. */
export function measureOccupied(anchors: CompanionAnchor[], hasContentAt: (x: number, y: number) => boolean): AnchorId[] {
  return anchors.filter((a) => !a.reserved && anchorSamplePoints(a).some((p) => hasContentAt(p.x, p.y))).map((a) => a.id);
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/**
 * Fokusovaný ovládací prvek pod Jarvisem → nejbližší kotva, která ho nepřekrývá.
 * `null` = není třeba se hýbat (nebo není kam).
 */
export function pickSafeAnchor(anchors: CompanionAnchor[], current: AnchorId, control: Rect): AnchorId | null {
  const here = anchors.find((a) => a.id === current);
  if (here?.peek) return null; // u okraje nic nezakrývá
  if (!here || !overlaps(anchorRect(here), control)) return null;
  const safe = anchors
    .filter((a) => a.id !== current && !a.peek && !overlaps(anchorRect(a), control))
    .sort((a, b) => Math.abs(a.x - here.x) - Math.abs(b.x - here.x));
  return safe[0]?.id ?? null;
}

// ---------- preference ----------

/**
 * Inline skript do <head>: nastaví `html[data-jarvis-companion]` ještě před prvním vykreslením
 * (pruh dole, skrytý avatar v hlavičce /ai) – bez skoku rozvržení po hydrataci.
 */
export function companionBootScript(): string {
  return `try{var on=localStorage.getItem(${JSON.stringify(COMPANION_PREF_KEY)})!=="off"&&matchMedia("(min-width: ${COMPANION_MIN_VIEWPORT}px)").matches;document.documentElement.dataset.jarvisCompanion=on?"on":"off"}catch(e){}`;
}

export function parseCompanionPref(raw: string | null): boolean {
  return raw !== "off";
}

export function serializeCompanionPref(enabled: boolean): string {
  return enabled ? "on" : "off";
}

// ---------- stroj ----------

/**
 * Lichoběžníkový průběh rychlosti: rozjezd (zrychlení), cesta stálou rychlostí, dojezd (zpomalení).
 * Vrací podíl uražené dráhy v čase t ∈ [0, 1].
 */
function trapezoid(t: number): number {
  const r = COMPANION_TIMING.accelFraction;
  const k = 2 * r * (1 - r);
  if (t < r) return (t * t) / k;
  if (t > 1 - r) return 1 - ((1 - t) * (1 - t)) / k;
  return (t - r / 2) / (1 - r);
}

/** Vzorky průběhu – stejné body používá CSS `linear()` i `walkPosition`, takže přerušení sedí na pixel. */
export const WALK_EASING_POINTS: readonly number[] = Array.from({ length: 25 }, (_, i) => Math.round(trapezoid(i / 24) * 10_000) / 10_000);

export function walkEasingCss(): string {
  return `linear(${WALK_EASING_POINTS.join(", ")})`;
}

function easeWalk(t: number): number {
  const n = WALK_EASING_POINTS.length - 1;
  const at = Math.min(Math.max(t, 0), 1) * n;
  const i = Math.min(Math.floor(at), n - 1);
  return WALK_EASING_POINTS[i] + (WALK_EASING_POINTS[i + 1] - WALK_EASING_POINTS[i]) * (at - i);
}

export function walkPhase(walk: CompanionWalk, now: number): WalkPhase {
  const elapsed = now - walk.start;
  if (elapsed < walk.departMs) return "depart";
  if (elapsed < walk.departMs + walk.travelMs) return "travel";
  return "arrive";
}

export function walkPosition(walk: CompanionWalk, now: number): number {
  const t = (now - walk.start - walk.departMs) / walk.travelMs;
  return Math.round(walk.from + (walk.to - walk.from) * easeWalk(t));
}

/** Doba cesty tak, aby ustálená rychlost byla přesně `walkPxPerSecond` (průměr je nižší kvůli rozjezdu a dojezdu). */
function travelDuration(distance: number): number {
  const cruise = COMPANION_TIMING.walkPxPerSecond * (1 - COMPANION_TIMING.accelFraction);
  const ms = (Math.abs(distance) / cruise) * 1000;
  return Math.round(Math.min(Math.max(ms, COMPANION_TIMING.minTravelMs), COMPANION_TIMING.maxTravelMs));
}

function walkTo(from: number, to: number, target: AnchorId, start: number): CompanionWalk {
  const { departMs, settleMs } = COMPANION_TIMING;
  const travelMs = travelDuration(to - from);
  return { from, to, target, start, departMs, travelMs, settleMs, duration: departMs + travelMs + settleMs };
}

function relocationPause(index: number): number {
  return COMPANION_TIMING.relocateEveryMs + RELOCATION_PAUSE_OFFSETS[index % RELOCATION_PAUSE_OFFSETS.length];
}

function findAnchor(m: CompanionMachine, id: AnchorId): CompanionAnchor | undefined {
  return m.anchors.find((a) => a.id === id);
}

/** Kotva v tomto rozvržení: požadovaná, jinak pevná, jinak první dostupná. */
function resolveAnchor(anchors: CompanionAnchor[], wanted: AnchorId): CompanionAnchor | undefined {
  return anchors.find((a) => a.id === wanted) ?? anchors.find((a) => a.id === FIXED_ANCHOR) ?? anchors[0];
}

function startWalk(m: CompanionMachine, target: AnchorId, now: number): CompanionMachine {
  const anchor = findAnchor(m, target);
  if (!anchor || anchor.x === m.x) {
    return anchor ? { ...m, anchor: anchor.id, x: anchor.x, pendingTarget: null } : { ...m, pendingTarget: null };
  }
  // otočí se hned na začátku (fáze depart), ještě než vykročí
  return { ...m, walk: walkTo(m.x, anchor.x, target, now), walkPhase: "depart", facing: anchor.x > m.x ? "right" : "left", pendingTarget: null };
}

function snapTo(m: CompanionMachine, target: AnchorId): CompanionMachine {
  const anchor = resolveAnchor(m.anchors, target);
  if (!anchor) return { ...m, walk: null, walkPhase: null, pendingTarget: null };
  return { ...m, anchor: anchor.id, x: anchor.x, walk: null, walkPhase: null, pendingTarget: null };
}

/** Sousední volná kotva ve směru chůze; na konci řady (nebo před obsazenou) se směr otočí. */
function nextRelocationTarget(m: CompanionMachine): { target: AnchorId | null; dir: -1 | 1 } {
  const lane = m.anchors.filter((a) => !a.peek && !a.reserved).sort((a, b) => a.x - b.x);
  const i = lane.findIndex((a) => a.id === m.anchor);
  if (i < 0) return { target: null, dir: m.relocationDir };
  for (const dir of [m.relocationDir, (m.relocationDir * -1) as -1 | 1]) {
    const next = lane[i + dir];
    if (next && !m.occupied.includes(next.id)) return { target: next.id, dir };
  }
  return { target: null, dir: m.relocationDir };
}

/** Nejvyšší požadovaný stav bez ohledu na chůzi. */
function desiredState(m: CompanionMachine, now: number): CompanionState {
  if (!m.enabled || m.anchors.length === 0 || m.parked) return "hidden";
  // pořadí = přednost při shodě priorit: čerstvý záblesk (error) před trvající náladou (warning)
  const candidates: CompanionState[] = [];
  if (m.flash && m.flash.until > now) candidates.push(m.flash.kind);
  if (m.mood === "listening" || m.mood === "thinking" || m.mood === "warning") candidates.push(m.mood);
  return candidates.reduce<CompanionState>((best, s) => (COMPANION_PRIORITY[s] > COMPANION_PRIORITY[best] ? s : best), "idle");
}

/**
 * Kam patří podle obsazenosti: současná (cílová) kotva, je-li volná; jinak nejbližší volná běžná;
 * jinak vykouknutí od okraje; jinak nikam (`null` → schovat).
 */
export function chooseCompanionAnchor(
  anchors: CompanionAnchor[],
  occupied: readonly AnchorId[],
  current: AnchorId,
  x: number,
): AnchorId | null {
  const free = anchors.filter((a) => !occupied.includes(a.id));
  const regular = free.filter((a) => !a.peek);
  const here = regular.find((a) => a.id === current);
  if (here) return here.id;
  const nearest = [...regular].sort((a, b) => Math.abs(a.x - x) - Math.abs(b.x - x))[0];
  return nearest?.id ?? free.find((a) => a.peek)?.id ?? null;
}

function place(m: CompanionMachine, now: number, wasVisible: boolean): CompanionMachine {
  const heading = m.walk?.target ?? m.pendingTarget ?? m.anchor;
  const x = m.walk ? walkPosition(m.walk, now) : m.x;
  const target = chooseCompanionAnchor(m.anchors, m.occupied, heading, x);
  if (!target) return { ...m, parked: true, walk: null, pendingTarget: null };
  const next = { ...m, parked: false };
  const anchor = findAnchor(next, target);
  if (target === heading && (next.walk || next.pendingTarget)) return next;
  if (target === next.anchor && anchor && anchor.x === x) return next;
  // viditelný a v klidu → dojde; jinak (průhledný, reakce, reduced motion, okraj) se přestaví na místě
  const calm = COMPANION_PRIORITY[desiredState(next, now)] <= COMPANION_PRIORITY.walking;
  const canWalk = wasVisible && next.roaming && !anchor?.peek && calm;
  return canWalk ? startWalk({ ...next, walk: null, x }, target, now) : snapTo(next, target);
}

function requestMeasure(m: CompanionMachine): CompanionMachine {
  return { ...m, measureRequest: m.measureRequest + 1 };
}

function applyEvent(m: CompanionMachine, e: CompanionEvent): CompanionMachine {
  switch (e.type) {
    case "tick": {
      let next = m;
      if (next.scrollUntil !== null && e.now >= next.scrollUntil) next = requestMeasure({ ...next, scrollUntil: null });
      if (next.checkAt !== null && e.now >= next.checkAt) next = requestMeasure({ ...next, checkAt: null });
      return next;
    }
    case "scroll": {
      if (!m.enabled) return m;
      // obsah pod ním se hýbe: zprůhlednit, zastavit chůzi; po dosednutí se změří a postaví znovu
      const x = m.walk ? walkPosition(m.walk, e.now) : m.x;
      const heading = m.walk?.target ?? m.pendingTarget ?? m.anchor;
      const settle = e.now + COMPANION_TIMING.scrollSettleMs;
      return { ...m, measured: false, walk: null, walkPhase: null, pendingTarget: null, x, anchor: heading, scrollUntil: settle };
    }
    case "occupancy": {
      const next = { ...m, occupied: [...e.occupied], measured: true };
      return place(next, e.now, m.measured && !m.parked);
    }
    case "mood":
      return { ...m, mood: e.mood };
    case "pulse": {
      const ms = e.kind === "success" ? COMPANION_TIMING.successMs : COMPANION_TIMING.errorMs;
      return { ...m, flash: { kind: e.kind, until: e.now + ms } };
    }
    case "enabled": {
      if (e.value === m.enabled) return m;
      const next = { ...m, enabled: e.value, nextRelocateAt: e.now + relocationPause(m.relocationIndex) };
      // po zapnutí nejdřív ověřit, že pod ním nic není
      return e.value ? requestMeasure({ ...next, measured: false }) : next;
    }
    case "roaming": {
      if (e.value === m.roaming) return m;
      const next = { ...m, roaming: e.value, nextRelocateAt: e.now + relocationPause(m.relocationIndex) };
      // bez roamingu pevná kotva – pokud je obsazená, nejbližší volná (přestaví se, nechodí)
      return e.value ? next : place(snapTo(next, FIXED_ANCHOR), e.now, false);
    }
    case "layout": {
      const keep = m.walk?.target ?? m.pendingTarget ?? m.anchor;
      // bez roamingu zůstává na své kotvě (např. po ustoupení z pole), jinak na pevné
      const reset = { ...m, anchors: e.anchors, occupied: [], measured: false, parked: false };
      const next = snapTo(reset, m.roaming ? keep : m.anchor);
      return requestMeasure({ ...next, checkAt: e.now + COMPANION_TIMING.recheckAfterLayoutMs });
    }
    case "stroll":
      // ruční „projdi se" (vývojová ukázka) – stejný přesun jako v nečinnosti, jen hned
      return { ...m, nextRelocateAt: e.now };
    case "goto":
      if (!findAnchor(m, e.target)) return m;
      // během reakce by chůzi hned zastavila priorita → ustoupit rovnou (pole pod ním nesmí zůstat zakryté)
      if (COMPANION_PRIORITY[desiredState(m, e.now)] > COMPANION_PRIORITY.walking) return snapTo(m, e.target);
      return m.roaming ? startWalk({ ...m, walk: null, x: m.walk ? walkPosition(m.walk, e.now) : m.x }, e.target, e.now) : snapTo(m, e.target);
  }
}

function withBubble(m: CompanionMachine, previous: CompanionState, now: number): CompanionMachine {
  let bubble = m.bubble && m.bubble.until > now ? m.bubble : null;
  let lastBubbleAt = m.lastBubbleAt;
  if (m.state === "hidden") bubble = null;
  else if (m.state !== previous) {
    const text = BUBBLES[m.state];
    const last = lastBubbleAt[m.state];
    if (text && (last === undefined || now - last >= COMPANION_TIMING.bubbleCooldownMs)) {
      bubble = { text, until: now + COMPANION_TIMING.bubbleMs };
      lastBubbleAt = { ...lastBubbleAt, [m.state]: now };
    } else {
      bubble = null; // bublina k předchozí reakci nepatří k novému stavu
    }
  }
  return bubble === m.bubble && lastBubbleAt === m.lastBubbleAt ? m : { ...m, bubble, lastBubbleAt };
}

export function stepCompanion(machine: CompanionMachine, event: CompanionEvent): CompanionMachine {
  const now = event.now;
  let m = applyEvent(machine, event);
  if (m.flash && m.flash.until <= now) m = { ...m, flash: null };

  // dojít do cíle
  if (m.walk && now >= m.walk.start + m.walk.duration) {
    m = { ...m, x: m.walk.to, anchor: m.walk.target, walk: null, walkPhase: null, nextRelocateAt: now + relocationPause(m.relocationIndex) };
  }

  const desired = desiredState(m, now);
  if (desired === "idle" && COMPANION_PRIORITY[machine.state] > COMPANION_PRIORITY.walking) {
    // po reakci chvíli klid – žádné okamžité odkráčení
    m = { ...m, nextRelocateAt: now + relocationPause(m.relocationIndex) };
  }
  if (COMPANION_PRIORITY[desired] > COMPANION_PRIORITY.walking || desired === "hidden") {
    // reakce přeruší chůzi: zastavit na místě, cíl si zapamatovat
    if (m.walk) m = { ...m, x: walkPosition(m.walk, now), pendingTarget: m.walk.target, walk: null, walkPhase: null };
  } else if (!m.walk && m.roaming) {
    if (m.pendingTarget) {
      m = startWalk(m, m.pendingTarget, now);
    } else if (now >= m.nextRelocateAt && m.measured && m.anchors.length > 1) {
      const { target, dir } = nextRelocationTarget(m);
      const index = m.relocationIndex + 1;
      m = { ...m, relocationIndex: index, relocationDir: dir, nextRelocateAt: now + relocationPause(index) };
      if (target) m = startWalk(m, target, now);
    }
  }

  const phase = m.walk ? walkPhase(m.walk, now) : null;
  if (phase !== m.walkPhase) m = { ...m, walkPhase: phase };
  const state: CompanionState = m.walk ? "walking" : desired;
  m = state === m.state ? m : { ...m, state };
  return withBubble(m, machine.state, now);
}

export function createCompanion({
  now,
  anchors,
  enabled,
  roaming,
}: {
  now: number;
  anchors: CompanionAnchor[];
  enabled: boolean;
  roaming: boolean;
}): CompanionMachine {
  const start = resolveAnchor(anchors, FIXED_ANCHOR);
  const base: CompanionMachine = {
    state: "hidden",
    enabled,
    roaming,
    anchors,
    anchor: start?.id ?? FIXED_ANCHOR,
    x: start?.x ?? 0,
    facing: "left",
    mood: "idle",
    flash: null,
    walk: null,
    pendingTarget: null,
    relocationIndex: 0,
    relocationDir: -1,
    walkPhase: null,
    nextRelocateAt: now + relocationPause(0),
    bubble: null,
    lastBubbleAt: {},
    occupied: [],
    measured: false,
    parked: false,
    scrollUntil: null,
    checkAt: null,
    measureRequest: 0,
  };
  return stepCompanion(base, { type: "tick", now });
}

/** Kdy má komponenta stroj znovu „tiknout" (jediný časovač). `Infinity` = nic neplánovat. */
export function nextCompanionDeadline(m: CompanionMachine): number {
  if (!m.enabled) return Infinity;
  const times: number[] = [];
  if (m.scrollUntil !== null) times.push(m.scrollUntil);
  if (m.checkAt !== null) times.push(m.checkAt);
  if (m.state === "hidden") return times.length ? Math.min(...times) : Infinity;
  if (m.flash) times.push(m.flash.until);
  if (m.bubble) times.push(m.bubble.until);
  if (m.walk) {
    // hranice fází chůze (vykročení, příchod, konec doběhnutí)
    const { start, departMs, travelMs, duration } = m.walk;
    const boundary = { depart: start + departMs, travel: start + departMs + travelMs, arrive: start + duration };
    times.push(boundary[m.walkPhase ?? "depart"]);
  }
  const atEdge = findAnchor(m, m.anchor)?.peek === true; // z okraje ho vrátí až měření, ne klidný přesun
  if (m.state === "idle" && m.roaming && m.measured && !atEdge && m.anchors.length > 1) times.push(m.nextRelocateAt);
  return times.length ? Math.min(...times) : Infinity;
}
