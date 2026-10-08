/**
 * MRK-19: klient doménových událostí (SSE GET /events/stream) – čistá logika bez Reactu (testy: domainEvents.test.mjs).
 *
 * Kontrakt streamu (docs/domain-events.md): `event: domain_event` s `id` = domain_events.id a JSON daty,
 * `event: reset` (id = nejnovější, klient má stav načíst znovu přes REST), komentáře `: keepalive`.
 * EventSource při výpadku sám znovu připojí a pošle `Last-Event-ID` → server přehraje zmeškané události.
 * Když spojení skončí nadobro (CLOSED, např. 401/restart), klient ho obnoví sám s `?last_event_id=`.
 * Každá událost se aplikuje nejvýš jednou (id ≤ poslední zpracované se ignoruje).
 */

/** Stabilní tvar `data` zprávy `domain_event` (docs/domain-events.md). */
export interface DomainEvent {
  id: number;
  type: string;
  module_id: string | null;
  aggregate_type: string;
  aggregate_id: string | null;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export interface StreamReset {
  reason: "retention" | "overflow" | "unknown_cursor" | string;
  latest_id: number;
}

/** Jedna SSE zpráva (pro testy a případný fetch-klient; EventSource parsuje sám). */
export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/** Rozdělí text streamu na hotové zprávy; nedokončený konec vrací v `rest`. Komentáře a `retry` přeskočí. */
export function parseSse(buffer: string): { messages: SseMessage[]; rest: string } {
  const normalized = buffer.replace(/\r\n?/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: SseMessage[] = [];
  for (const block of blocks) {
    let id: string | null = null;
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "id") id = value;
      else if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) messages.push({ id, event, data: data.join("\n") });
  }
  return { messages, rest };
}

/** JSON data `domain_event` → událost; cokoli neplatného = null (ignoruje se, nikdy nespadne). */
export function parseDomainEvent(data: string): DomainEvent | null {
  try {
    const e = JSON.parse(data) as Partial<DomainEvent>;
    if (typeof e?.id !== "number" || !Number.isSafeInteger(e.id) || typeof e.type !== "string") return null;
    if (typeof e.aggregate_type !== "string" || typeof e.occurred_at !== "string") return null;
    return {
      id: e.id,
      type: e.type,
      module_id: typeof e.module_id === "string" ? e.module_id : null,
      aggregate_type: e.aggregate_type,
      aggregate_id: e.aggregate_id == null ? null : String(e.aggregate_id),
      occurred_at: e.occurred_at,
      payload: e.payload && typeof e.payload === "object" && !Array.isArray(e.payload) ? (e.payload as Record<string, unknown>) : {},
    };
  } catch {
    return null;
  }
}

export function parseReset(data: string): StreamReset | null {
  try {
    const r = JSON.parse(data) as Partial<StreamReset>;
    return typeof r?.latest_id === "number" && typeof r.reason === "string" ? { reason: r.reason, latest_id: r.latest_id } : null;
  } catch {
    return null;
  }
}

/** Nejvýš jednou: přijme jen id větší než poslední zpracované. */
export function createEventTracker(start = 0) {
  let last = start;
  return {
    get lastId() {
      return last;
    },
    accept(id: number): boolean {
      if (!Number.isSafeInteger(id) || id <= last) return false;
      last = id;
      return true;
    },
    /** Reset streamu: další události začínají za `latestId` (starší se už nepřehrají). */
    jumpTo(latestId: number) {
      if (Number.isSafeInteger(latestId) && latestId > last) last = latestId;
    },
  };
}

export function streamUrl(base: string, lastId: number | null): string {
  const url = `${base.replace(/\/$/, "")}/events/stream`;
  return lastId && lastId > 0 ? `${url}?last_event_id=${lastId}` : url;
}

/** Jedna mapovací tabulka událost → reakce Jarvise (sdílí i budoucí Desktop Jarvis, MRK-17). */
export const JARVIS_EVENT_SIGNALS: Record<string, (e: DomainEvent) => "success" | "error" | null> = {
  "school.assignment.completed": () => "success",
  "school.exam.closed": (e) => (e.payload.outcome === "failed" ? null : "success"),
};

/** Jen čerstvé události (replay po reconnectu nemá slavit staré věci). */
export const JARVIS_FRESH_MS = 2 * 60 * 1000;

export function jarvisSignalFor(e: DomainEvent, now = Date.now()): "success" | "error" | null {
  const map = JARVIS_EVENT_SIGNALS[e.type];
  if (!map) return null;
  const at = Date.parse(e.occurred_at);
  if (!Number.isFinite(at) || now - at > JARVIS_FRESH_MS) return null;
  return map(e);
}

export function isModuleSettingsEvent(e: DomainEvent): boolean {
  return e.type === "system.module.enabled" || e.type === "system.module.disabled";
}

// ---------- klient nad EventSource (injektovatelný kvůli testům) ----------

export interface EventSourceLike {
  readyState: number;
  onerror: ((ev: Event) => unknown) | null;
  addEventListener(type: string, listener: (ev: MessageEvent<string>) => void): void;
  close(): void;
}

export type EventSourceFactory = (url: string) => EventSourceLike;

export interface DomainEventClientOptions {
  baseUrl: string;
  create: EventSourceFactory;
  onEvent: (e: DomainEvent) => void;
  onReset?: (r: StreamReset) => void;
  /** Odložené znovupřipojení po úplném zavření (readyState CLOSED). */
  schedule?: (fn: () => void, ms: number) => unknown;
  cancel?: (handle: unknown) => void;
}

export const CLOSED = 2;
const BACKOFF_MS = [1000, 3000, 10000, 30000];

export function createDomainEventClient(opts: DomainEventClientOptions) {
  const tracker = createEventTracker();
  const schedule = opts.schedule ?? ((fn, ms) => setTimeout(fn, ms));
  const cancel = opts.cancel ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));
  let source: EventSourceLike | null = null;
  let timer: unknown = null;
  let attempts = 0;
  let stopped = false;

  const connect = () => {
    if (stopped) return;
    timer = null;
    const es = opts.create(streamUrl(opts.baseUrl, tracker.lastId || null));
    source = es;
    es.addEventListener("domain_event", (msg) => {
      attempts = 0;
      const e = parseDomainEvent(msg.data);
      if (e && tracker.accept(e.id)) opts.onEvent(e);
    });
    es.addEventListener("reset", (msg) => {
      attempts = 0;
      const r = parseReset(msg.data);
      if (!r) return;
      tracker.jumpTo(r.latest_id);
      opts.onReset?.(r);
    });
    es.onerror = () => {
      // CONNECTING = EventSource se připojí sám (s Last-Event-ID); CLOSED = obnovit ručně s ?last_event_id=
      if (es.readyState !== CLOSED || stopped || timer) return;
      es.close();
      const delay = BACKOFF_MS[Math.min(attempts, BACKOFF_MS.length - 1)];
      attempts += 1;
      timer = schedule(connect, delay);
    };
  };

  connect();
  return {
    get lastId() {
      return tracker.lastId;
    },
    close() {
      stopped = true;
      if (timer) cancel(timer);
      source?.close();
    },
  };
}
