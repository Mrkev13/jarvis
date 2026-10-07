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
  /** Klidný přesun v nečinnosti – vzácně, ne náhodně. */
  relocateEveryMs: 90_000,
  walkPxPerSecond: 90,
  minWalkMs: 1200,
  maxWalkMs: 7000,
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

export type AnchorId = "left" | "center" | "right" | "ai" | "edge";
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

/** Pořadí klidných přesunů z výchozí pravé kotvy (dokola). */
export const RELOCATION_ORDER: readonly AnchorId[] = ["center", "left", "center", "right"];
/** Pevná kotva bez roamingu (reduced motion). */
const FIXED_ANCHOR: AnchorId = "right";

const BUBBLES: Partial<Record<CompanionState, string>> = {
  listening: "Poslouchám…",
  thinking: "Moment, přemýšlím…",
  success: "Hotovo!",
  warning: "Čekám na tvoje potvrzení.",
  error: "Tohle se nepovedlo.",
};

export interface CompanionWalk {
  from: number;
  to: number;
  target: AnchorId;
  start: number;
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
  const laneWidth = vp.width - vp.sidebar;
  const width = COMPANION_BOX.width;
  return [
    { id: "left", x: clampX(vp.sidebar + COMPANION_BOX.margin, vp), y, width },
    { id: "center", x: clampX(vp.sidebar + (laneWidth - COMPANION_BOX.width) / 2, vp), y, width },
    { id: "right", x: clampX(vp.width - COMPANION_BOX.margin - COMPANION_BOX.width, vp), y, width },
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

export function walkPosition(walk: CompanionWalk, now: number): number {
  const t = Math.min(Math.max((now - walk.start) / walk.duration, 0), 1);
  return Math.round(walk.from + (walk.to - walk.from) * t);
}

function walkDuration(distance: number): number {
  const ms = (Math.abs(distance) / COMPANION_TIMING.walkPxPerSecond) * 1000;
  return Math.round(Math.min(Math.max(ms, COMPANION_TIMING.minWalkMs), COMPANION_TIMING.maxWalkMs));
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
  return {
    ...m,
    walk: { from: m.x, to: anchor.x, target, start: now, duration: walkDuration(anchor.x - m.x) },
    facing: anchor.x > m.x ? "right" : "left",
    pendingTarget: null,
  };
}

function snapTo(m: CompanionMachine, target: AnchorId): CompanionMachine {
  const anchor = resolveAnchor(m.anchors, target);
  if (!anchor) return { ...m, walk: null, pendingTarget: null };
  return { ...m, anchor: anchor.id, x: anchor.x, walk: null, pendingTarget: null };
}

function nextRelocationTarget(m: CompanionMachine): { target: AnchorId | null; index: number } {
  for (let step = 0; step < RELOCATION_ORDER.length; step += 1) {
    const index = (m.relocationIndex + step) % RELOCATION_ORDER.length;
    const id = RELOCATION_ORDER[index];
    if (id !== m.anchor && findAnchor(m, id) && !m.occupied.includes(id)) return { target: id, index: (index + 1) % RELOCATION_ORDER.length };
  }
  return { target: null, index: m.relocationIndex };
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
  if (target === heading && (next.walk || next.pendingTarget || target === next.anchor)) return next;
  const anchor = findAnchor(next, target);
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
      return { ...m, measured: false, walk: null, pendingTarget: null, x, anchor: heading, scrollUntil: settle };
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
      const next = { ...m, enabled: e.value, nextRelocateAt: e.now + COMPANION_TIMING.relocateEveryMs };
      // po zapnutí nejdřív ověřit, že pod ním nic není
      return e.value ? requestMeasure({ ...next, measured: false }) : next;
    }
    case "roaming": {
      if (e.value === m.roaming) return m;
      const next = { ...m, roaming: e.value, nextRelocateAt: e.now + COMPANION_TIMING.relocateEveryMs };
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
    m = { ...m, x: m.walk.to, anchor: m.walk.target, walk: null, nextRelocateAt: now + COMPANION_TIMING.relocateEveryMs };
  }

  const desired = desiredState(m, now);
  if (desired === "idle" && COMPANION_PRIORITY[machine.state] > COMPANION_PRIORITY.walking) {
    // po reakci chvíli klid – žádné okamžité odkráčení
    m = { ...m, nextRelocateAt: now + COMPANION_TIMING.relocateEveryMs };
  }
  if (COMPANION_PRIORITY[desired] > COMPANION_PRIORITY.walking || desired === "hidden") {
    // reakce přeruší chůzi: zastavit na místě, cíl si zapamatovat
    if (m.walk) m = { ...m, x: walkPosition(m.walk, now), pendingTarget: m.walk.target, walk: null };
  } else if (!m.walk && m.roaming) {
    if (m.pendingTarget) {
      m = startWalk(m, m.pendingTarget, now);
    } else if (now >= m.nextRelocateAt && m.measured && m.anchors.length > 1) {
      const { target, index } = nextRelocationTarget(m);
      m = { ...m, relocationIndex: index, nextRelocateAt: now + COMPANION_TIMING.relocateEveryMs };
      if (target) m = startWalk(m, target, now);
    }
  }

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
    nextRelocateAt: now + COMPANION_TIMING.relocateEveryMs,
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
  if (m.walk) times.push(m.walk.start + m.walk.duration);
  const atEdge = findAnchor(m, m.anchor)?.peek === true; // z okraje ho vrátí až měření, ne klidný přesun
  if (m.state === "idle" && m.roaming && m.measured && !atEdge && m.anchors.length > 1) times.push(m.nextRelocateAt);
  return times.length ? Math.min(...times) : Infinity;
}
