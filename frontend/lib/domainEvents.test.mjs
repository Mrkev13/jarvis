// MRK-19: SSE klient doménových událostí – parser, dedupe, reset, reconnect s Last-Event-ID, Jarvis mapování.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CLOSED,
  createDomainEventClient,
  createEventTracker,
  isModuleSettingsEvent,
  JARVIS_FRESH_MS,
  jarvisSignalFor,
  parseDomainEvent,
  parseReset,
  parseSse,
  streamUrl,
} from "./domainEvents.ts";

const NOW = Date.parse("2026-10-08T12:00:00Z");
const ev = (id, type = "system.module.enabled", extra = {}) => ({
  id, type, module_id: null, aggregate_type: "module", aggregate_id: "mff", occurred_at: "2026-10-08T12:00:00Z",
  payload: { module_id: "mff" }, ...extra,
});
const wire = (e) => `id: ${e.id}\nevent: domain_event\ndata: ${JSON.stringify(e)}\n\n`;

test("parseSse: messages, comments, retry and partial chunks", () => {
  const text = `retry: 3000\n\n: keepalive\n\n${wire(ev(5))}id: 9\nevent: reset\ndata: {"reason":"retention","latest_id":9}\n\nid: 10\nevent: dom`;
  const { messages, rest } = parseSse(text);
  assert.deepEqual(messages.map((m) => [m.id, m.event]), [["5", "domain_event"], ["9", "reset"]]);
  assert.equal(rest, "id: 10\nevent: dom", "nedokončená zpráva čeká na další chunk");
  const second = parseSse(rest + `ain_event\ndata: ${JSON.stringify(ev(10))}\n\n`);
  assert.equal(second.messages[0].id, "10");
  assert.equal(parseSse("id: 1\r\nevent: x\r\ndata: {}\r\n\r\n").messages.length, 1, "CRLF");
  assert.equal(parseSse("data: a\ndata: b\n\n").messages[0].data, "a\nb", "víceřádková data");
});

test("parseDomainEvent / parseReset reject malformed data", () => {
  const parsed = parseDomainEvent(JSON.stringify(ev(3)));
  assert.equal(parsed.type, "system.module.enabled");
  assert.deepEqual(Object.keys(parsed).sort(), ["aggregate_id", "aggregate_type", "id", "module_id", "occurred_at", "payload", "type"]);
  for (const bad of ["{", "null", "[]", JSON.stringify({ id: "3", type: "x" }), JSON.stringify({ id: 3 }), JSON.stringify({ ...ev(3), aggregate_type: null })]) {
    assert.equal(parseDomainEvent(bad), null, bad);
  }
  assert.deepEqual(parseReset('{"reason":"overflow","latest_id":44}'), { reason: "overflow", latest_id: 44 });
  assert.equal(parseReset('{"latest_id":"x"}'), null);
});

test("tracker applies each id at most once and jumps forward on reset", () => {
  const t = createEventTracker();
  assert.equal(t.accept(1), true);
  assert.equal(t.accept(1), false, "duplicita");
  assert.equal(t.accept(0), false);
  assert.equal(t.accept(3), true);
  assert.equal(t.accept(2), false, "starší než poslední zpracované");
  t.jumpTo(10);
  assert.equal(t.accept(9), false);
  assert.equal(t.accept(11), true);
  t.jumpTo(5);
  assert.equal(t.lastId, 11, "reset nikdy necouvá");
});

test("streamUrl resumes with last_event_id only when known", () => {
  assert.equal(streamUrl("http://h:8000/", null), "http://h:8000/events/stream");
  assert.equal(streamUrl("http://h:8000", 42), "http://h:8000/events/stream?last_event_id=42");
});

function fakeSources() {
  const created = [];
  const create = (url) => {
    const listeners = {};
    const es = {
      url, readyState: 1, onerror: null, closed: false,
      addEventListener: (type, fn) => { (listeners[type] ??= []).push(fn); },
      close() { this.closed = true; this.readyState = CLOSED; },
      emit(type, data, id) { for (const fn of listeners[type] ?? []) fn({ data, lastEventId: id }); },
    };
    created.push(es);
    return es;
  };
  return { created, create };
}

test("client: dedupes replayed events after an automatic reconnect", () => {
  const { created, create } = fakeSources();
  const got = [];
  createDomainEventClient({ baseUrl: "http://h", create, onEvent: (e) => got.push(e.id) });
  const es = created[0];
  assert.equal(es.url, "http://h/events/stream", "start bez pozice = jen nové události");
  es.emit("domain_event", JSON.stringify(ev(5)), "5");
  es.emit("domain_event", JSON.stringify(ev(6)), "6");
  // EventSource se připojí sám (readyState CONNECTING) a server přehraje od Last-Event-ID – včetně překryvu
  es.readyState = 0;
  es.onerror?.({});
  assert.equal(created.length, 1, "CONNECTING: nový zdroj se nevytváří (Last-Event-ID řeší prohlížeč)");
  es.emit("domain_event", JSON.stringify(ev(6)), "6");
  es.emit("domain_event", JSON.stringify(ev(7)), "7");
  es.emit("domain_event", "garbage", "8");
  assert.deepEqual(got, [5, 6, 7], "každá událost nejvýš jednou, neplatná data ignorována");
});

test("client: closed connection is reopened with ?last_event_id= after backoff", () => {
  const { created, create } = fakeSources();
  const timers = [];
  const client = createDomainEventClient({
    baseUrl: "http://h", create, onEvent: () => {},
    schedule: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, cancel: () => {},
  });
  created[0].emit("domain_event", JSON.stringify(ev(12)), "12");
  created[0].readyState = CLOSED;
  created[0].onerror?.({});
  created[0].onerror?.({}); // druhá chyba nesmí naplánovat druhé spojení
  assert.deepEqual(timers.map((t) => t.ms), [1000]);
  timers[0].fn();
  assert.equal(created.length, 2);
  assert.equal(created[1].url, "http://h/events/stream?last_event_id=12");
  created[1].readyState = CLOSED;
  created[1].onerror?.({});
  assert.equal(timers[1].ms, 3000, "rostoucí odstup");
  client.close();
  assert.equal(created[1].closed, true);
});

test("client: reset jumps forward and notifies", () => {
  const { created, create } = fakeSources();
  const got = [];
  const resets = [];
  createDomainEventClient({ baseUrl: "http://h", create, onEvent: (e) => got.push(e.id), onReset: (r) => resets.push(r) });
  created[0].emit("reset", '{"reason":"retention","latest_id":50}', "50");
  created[0].emit("domain_event", JSON.stringify(ev(49)), "49");
  created[0].emit("domain_event", JSON.stringify(ev(51)), "51");
  assert.deepEqual(resets, [{ reason: "retention", latest_id: 50 }]);
  assert.deepEqual(got, [51]);
});

test("Jarvis mapping: one table, fresh events only, failed exam is not celebrated", () => {
  const done = { ...ev(1, "school.assignment.completed"), occurred_at: "2026-10-08T11:59:30Z" };
  assert.equal(jarvisSignalFor(done, NOW), "success");
  assert.equal(jarvisSignalFor({ ...done, occurred_at: new Date(NOW - JARVIS_FRESH_MS - 1000).toISOString() }, NOW), null, "replay starých událostí neslaví");
  assert.equal(jarvisSignalFor({ ...ev(2, "school.exam.closed"), occurred_at: "2026-10-08T11:59:30Z", payload: { outcome: "failed" } }, NOW), null);
  assert.equal(jarvisSignalFor({ ...ev(3, "school.exam.closed"), occurred_at: "2026-10-08T11:59:30Z", payload: { outcome: "passed" } }, NOW), "success");
  assert.equal(jarvisSignalFor(ev(4, "system.module.enabled"), NOW), null);
});

test("module settings events are recognised for the realtime module refresh", () => {
  assert.equal(isModuleSettingsEvent(ev(1, "system.module.enabled")), true);
  assert.equal(isModuleSettingsEvent(ev(2, "system.module.disabled")), true);
  assert.equal(isModuleSettingsEvent(ev(3, "school.assignment.completed")), false);
});

test("client: unavailable stream does not throw and cleanup stops reconnects", () => {
  const { created, create } = fakeSources();
  const timers = [];
  let cancelled = 0;
  const client = createDomainEventClient({
    baseUrl: "http://h", create, onEvent: () => {},
    schedule: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, cancel: () => { cancelled += 1; },
  });
  created[0].readyState = CLOSED;
  assert.doesNotThrow(() => created[0].onerror?.({}));
  client.close();
  assert.equal(cancelled, 1, "naplánované obnovení se zruší");
  timers[0].fn();
  assert.equal(created.length, 1, "po close se už nepřipojuje");
});
