// Vývojový mock backendu pro vizuální kontrolu UI (Roadmap 4A) – NE produkce, žádný Groq.
// Data v scripts/fixtures/*.json vznikla ze skutečných backendových služeb (seed + fake LLM).
// Spuštění: node scripts/mock-api.mjs  (port 8000, nebo MOCK_API_PORT)
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { handleAi } from "./mock-ai.mjs";
import { stubPng } from "./stub-png.mjs";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const PORT = Number(process.env.MOCK_API_PORT || 8000);
const DELAY_MS = Number(process.env.MOCK_API_DELAY_MS || 0); // simulace pomalé sítě pro skeletony
const ACTION_DELAY_MS = 700; // akce trvají chvíli, aby byl vidět busy stav

const GET_ROUTES = {
  "/dashboard": () => fixture("dashboard"),
  "/briefing/today": () => fixture("briefing"),
  "/weekly-review": () => fixture("weekly-review"),
  "/weekly-review/history": () => fixture("weekly-history"),
  "/notifications/summary": () => fixture("notifications-summary"),
  "/notifications": () => fixture("notifications"),
  "/push/config": () => fixture("push-config"),
  // Roadmap 4B: moduly
  "/finance/summary": () => fixture("finance-summary"),
  "/finance/transactions": () => fixture("finance-transactions"),
  "/goals/list": () => fixture("goals-list"),
  "/goals/summary": () => fixture("goals-summary"),
  "/memories": () => fixture("memories"),
  "/mff/characters": () => fixture("mff-characters"),
  "/mff/summary": () => fixture("mff-summary"),
  "/school/subjects": () => fixture("school-subjects"),
  "/school/assignments": () => fixture("school-assignments"),
  "/school/exams": () => fixture("school-exams"),
  "/work/sessions": () => fixture("work-sessions"),
  "/work/summary": () => fixture("work-summary"),
  "/wot/grinds": () => wotState.grinds,
  "/wot/resources": () => fixture("wot-resources"),
  "/activity": () => fixture("activity"),
  // Roadmap 4G: GET /today ze skutečného today_service (ne 11. 10. 2026 14:30 Praha). Prázdný den a částečnou
  // chybu (fixtures/today-empty.json, today-partial.json) podstrkuje ui-check přes page.route.
  "/today": () => fixture(todayState.fixture),
};

function send(res, req, status, body, extraHeaders = {}) {
  res.writeHead(status, {
    ...extraHeaders,
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": req.headers.origin || "*",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
  });
  res.end(body === undefined ? "" : JSON.stringify(body));
}

// Game Enrichment B: stavový WoT (splnění grindu, historie, milníky, screenshoty). Výchozí data = fixtures ze
// skutečného wot_service; /__mock/wot/reset vrátí výchozí stav. Screenshoty = neutrální testovací PNG (ne herní
// grafika); id 5 představuje soubor smazaný z disku (404 → náhradní stav v galerii).
const wotState = {};
function resetWot() {
  Object.assign(wotState, {
    grinds: fixture("wot-grinds"),
    completed: fixture("wot-completed"),
    milestones: fixture("wot-milestones"),
    files: new Map(),
    seq: 100,
    // Game Enrichment C: knihovna replayů (fixtures ze skutečného wot_replay_service)
    replays: fixture("wot-replays").items,
  });
}
// ui-check nahrává scripts/fixtures/replay-upload.wotreplay (syntetický) → odpověď skutečného serveru pro tentýž soubor
const REPLAY_UPLOAD = fixture("wot-replay-upload");
const REPLAY_MAGIC = Buffer.from([0x12, 0x32, 0x34, 0x11]);
const PRESET_TAGS = ["mko", "carry", "spotting", "record", "mistake", "fun", "close-game"];
const normText = (t) => String(t ?? "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
function replayView(r) {
  const m = r.linked_milestone_id ? wotMilestone(r.linked_milestone_id) : null;
  const milestone = m ? { id: m.id, tank: m.tank, mastery: m.mastery, map_name: m.map_name, played_on: m.played_on, screenshots: m.screenshots } : null;
  return { ...r, linked_milestone_id: m ? m.id : null, milestone };
}
function replayList(qs) {
  const rows = wotState.replays;
  const facets = {
    tanks: [...new Set(rows.map((r) => r.tank_name || r.tank_tag).filter(Boolean))].sort((a, b) => normText(a).localeCompare(normText(b))),
    maps: [...new Set(rows.map((r) => r.map_name).filter(Boolean))].sort((a, b) => normText(a).localeCompare(normText(b))),
    tags: [...new Set(rows.flatMap((r) => r.tags))].sort((a, b) => ((PRESET_TAGS.indexOf(a) + 1 || 99) - (PRESET_TAGS.indexOf(b) + 1 || 99)) || a.localeCompare(b)),
  };
  const q = normText(qs.get("q"));
  const g = (k) => qs.get(k) || "";
  let out = rows.filter((r) => {
    const hay = normText([r.tank_name, r.tank_tag, r.map_name, r.notes, r.original_filename, r.tags.join(" ")].filter(Boolean).join(" "));
    if (q && !q.split(" ").every((w) => hay.includes(w))) return false;
    if (g("tank") && ![r.tank_name, r.tank_tag].includes(g("tank"))) return false;
    if (g("map") && r.map_name !== g("map")) return false;
    if (g("tag") && !r.tags.includes(g("tag").toLowerCase())) return false;
    if (g("favorite") && String(r.favorite) !== g("favorite")) return false;
    if (g("mastery") && (r.mastery || "none") !== g("mastery")) return false;
    if (g("result") && r.battle_result !== g("result")) return false;
    return true;
  });
  const sort = g("sort") || "played_desc";
  if (sort === "uploaded_desc") out = [...out].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at) || b.id - a.id);
  else {
    const dated = out.filter((r) => r.played_at).sort((a, b) => a.played_at.localeCompare(b.played_at) || a.id - b.id);
    if (sort === "played_desc") dated.reverse();
    out = [...dated, ...out.filter((r) => !r.played_at).sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))];
  }
  return { items: out.map(replayView), total: rows.length, facets, preset_tags: PRESET_TAGS, statuses: ["parsed", "partial", "unsupported", "invalid"] };
}
resetWot();
const SHOT_COLORS = [[58, 70, 84], [64, 80, 72], [84, 70, 58], [70, 64, 90]];
const wotNow = () => new Date().toISOString().slice(0, 19) + "Z";
function wotMilestone(id) {
  return wotState.milestones.find((m) => m.id === id);
}

// Auth (Roadmap 4C – kontrola proxy a loginu): session cookie „expired" = neplatná session, jinak platná.
// POST /auth/login: PIN 1234 nastaví cookie „ok", jiný PIN = 401 invalid_credentials (jako backend).
const AUTH_COOKIE = "standa_hub_session";
const normalizeQuery = (t) => String(t ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
const searchCalls = []; // pro ui-check: kolik dotazů /search přišlo (debounce)
const quickAddCalls = []; // Roadmap 4E: texty /quick-add/parse (debounce, žádný zápis při rozboru)
const quickAddPrepared = [];
const quickAddConfirmed = [];
const quickAddFailOnce = new Set();
let quickAddSeq = 0;
// Roadmap 4H: akce z Dnes. Stav dne = fixture vygenerovaná skutečným backendem PO dané akci
// (today-after-*.json); /__mock/today/fail?mode=error|stale|confirm_error nastaví jednorázové selhání.
const todayState = { fixture: "today", fail: null, calls: [], seq: 0, undone: new Set() };
const sessionOf = (req) => /(?:^|;\s*)standa_hub_session=([^;]+)/.exec(req.headers.cookie || "")?.[1] ?? null;

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      req.rawBody = Buffer.concat(chunks); // upload replaye (Game Enrichment C) potřebuje bajty
      const raw = req.rawBody.toString("utf8");
      try {
        resolve(raw ? JSON.parse(raw) : null);
      } catch {
        resolve(null);
      }
    });
  });
}

createServer(async (req, res) => {
  const url = new URL(req.url, "http://mock");
  if (req.method === "OPTIONS") return send(res, req, 204);
  const respond = (status, body, delay = DELAY_MS, headers) => setTimeout(() => send(res, req, status, body, headers), delay);
  const body = req.method === "GET" ? null : await readBody(req);
  if (url.pathname === "/auth/session/validate") {
    return respond(200, { valid: sessionOf(req) !== "expired", auth_disabled: false });
  }
  if (url.pathname === "/auth/login" && req.method === "POST") {
    if (body?.pin === "1234") {
      return respond(200, { ok: true }, 300, { "Set-Cookie": `${AUTH_COOKIE}=ok; Path=/; HttpOnly; SameSite=Lax` });
    }
    return respond(401, { ok: false, error: "invalid_credentials" }, 300);
  }
  // Roadmap 4D: /search – odpovědi ze skutečné search_service (fixtures/search.json, viz generátor);
  // neznámý dotaz = prázdný výsledek. Krátká prodleva ukáže stav „Hledám…".
  if (url.pathname === "/search" && req.method === "GET") {
    const nq = normalizeQuery(url.searchParams.get("q")).slice(0, 100);
    searchCalls.push(nq);
    const all = fixture("search");
    const hit = Object.entries(all).find(([k]) => normalizeQuery(k) === nq);
    return respond(200, hit ? { ...hit[1], query: nq } : { query: nq, results: [], total: 0 }, 220);
  }
  if (url.pathname === "/__mock/search-calls") return respond(200, searchCalls.splice(0));
  // Roadmap 4E: Rychlé přidání. /quick-add/parse = odpovědi skutečného quick_add_service.parse (fixtures/quick-add.json,
  // now = 2026-10-11 17:00 UTC jako ostatní fixtures, předměty ze school-subjects.json); neznámý text = „unknown". /quick-add/prepare vrátí pending akci „qa-…", /actions/confirm
  // ji „zapíše" (bez undo). Popis „chyba" = první potvrzení selže (kontrola cesty „Zkusit znovu").
  if (url.pathname.startsWith("/quick-add/") && sessionOf(req) === "expired") return respond(401, { detail: "Not authenticated" });
  if (url.pathname === "/quick-add/parse" && req.method === "POST") {
    const text = String(body?.text ?? "").trim().replace(/\s+/g, " ");
    quickAddCalls.push(text);
    const hit = Object.entries(fixture("quick-add")).find(([k]) => k === text);
    if (text === "simuluj chybu") return respond(500, { detail: "Simulovaná chyba serveru." }, 150);
    const empty = text.length < 2;
    return respond(200, hit ? hit[1] : {
      kind: empty ? "empty" : "unknown", confidence: "low", fields: {}, display: { title: "", subtitle: "", area: null },
      warnings: [], needs_input: [], errors: [], ready: false,
    }, 150);
  }
  if (url.pathname === "/quick-add/prepare" && req.method === "POST") {
    const f = body?.fields ?? {};
    quickAddPrepared.push(body);
    const errors = [];
    if (!["reminder", "finance", "work", "exam", "assignment"].includes(body?.kind)) errors.push({ field: "kind", message: "Neznámý typ záznamu." });
    if (body?.kind === "finance" && !(Number(f.amount) > 0)) errors.push({ field: "amount", message: "Částka musí být kladná." });
    if (body?.kind === "work" && !(Number(f.hours) > 0 && Number(f.hours) <= 24)) errors.push({ field: "hours", message: "Hodiny musí být mezi 0 a 24." });
    if ((body?.kind === "exam" || body?.kind === "assignment") && !f.subject_id) errors.push({ field: "subject_id", message: "Vyber existující předmět." });
    if (errors.length) return respond(422, { detail: { errors } }, 200);
    const id = `qa-${++quickAddSeq}`;
    if (String(f.description || f.title || f.project || "").toLowerCase() === "chyba") quickAddFailOnce.add(id);
    return respond(200, { ok: true, pending_action: { id, tool: `quick_add:${body.kind}`, arguments: { ...f, _source: "quick_add" }, expires_at: null } }, 250);
  }
  if (url.pathname === "/actions/confirm" && req.method === "POST" && String(body?.action_id || "").startsWith("qa-")) {
    const id = String(body.action_id);
    if (quickAddFailOnce.delete(id)) return respond(200, { ok: false, error: "execution_failed", detail: "Zápis se nepodařil (simulace) – zkus to znovu." }, 400);
    quickAddConfirmed.push(id);
    return respond(200, { ok: true, tool: "x", arguments: {}, result: { id: quickAddConfirmed.length } }, 400);
  }
  if (url.pathname === "/__mock/quick-add") {
    return respond(200, { parse: quickAddCalls.splice(0), prepared: quickAddPrepared.splice(0), confirmed: quickAddConfirmed.splice(0) });
  }
  if (url.pathname === "/__mock/today/reset") {
    Object.assign(todayState, { fixture: "today", fail: null, calls: [], seq: 0, undone: new Set() });
    return respond(200, { ok: true });
  }
  if (url.pathname === "/__mock/today/fail") {
    todayState.fail = url.searchParams.get("mode");
    return respond(200, { ok: true });
  }
  if (url.pathname === "/__mock/today") return respond(200, todayState.calls);
  const todayReminder = /^\/reminders\/(\d+)\/(done|snooze)$/.exec(url.pathname);
  if (todayReminder && req.method === "POST" && url.searchParams.get("source") === "today") {
    const [, id, op] = todayReminder;
    todayState.calls.push(`${op}:reminder:${id}${body?.minutes ? `:+${body.minutes}` : body?.until_local ? `:${body.until_local}` : ""}`);
    const fail = todayState.fail;
    todayState.fail = null;
    if (fail === "error") return respond(500, { detail: "Simulovaná chyba serveru." }, 300);
    if (fail === "stale") {
      todayState.fixture = "today-after-reminder-done"; // jiná záložka ji mezitím dokončila
      return respond(400, { detail: "Připomínka už je hotová nebo zrušená." }, 300);
    }
    todayState.fixture = op === "done" ? "today-after-reminder-done" : "today-after-reminder-snooze";
    return respond(200, { id: Number(id), status: op === "done" ? "done" : "scheduled", next_label: "ne 11. 10. 2026 15:30" }, 400);
  }
  if (url.pathname === "/today/actions/prepare" && req.method === "POST") {
    todayState.calls.push(`prepare:${body?.ref}`);
    if (todayState.fail === "stale") {
      todayState.fail = null;
      todayState.fixture = "today-after-assignment-done";
      return respond(409, { detail: { error: "no_change", message: "Záznam už má požadované hodnoty – není co měnit." } }, 300);
    }
    const id = `today-${++todayState.seq}`;
    return respond(200, { ok: true, pending_action: { id, tool: "modify_records", arguments: { _source: "today" }, expires_at: null } }, 250);
  }
  if (url.pathname === "/actions/confirm" && req.method === "POST" && String(body?.action_id || "").startsWith("today-")) {
    const id = String(body.action_id);
    todayState.calls.push(`confirm:${id}`);
    if (todayState.fail === "confirm_error") {
      todayState.fail = null;
      return respond(200, { ok: false, error: "execution_failed", detail: "Simulovaná chyba při zápisu." }, 300);
    }
    if (id.includes("undo")) {
      todayState.fixture = "today";
      return respond(200, { ok: true, tool: "undo_change", arguments: {}, result: { undone: true } }, 300);
    }
    todayState.fixture = "today-after-assignment-done";
    return respond(200, { ok: true, tool: "modify_records", arguments: {}, result: { undo_available: true } }, 400);
  }
  if (url.pathname === "/actions/undo" && req.method === "POST" && String(body?.action_id || "").startsWith("today-")) {
    todayState.calls.push(`undo:${body.action_id}`);
    return respond(200, { ok: true, pending_action: { id: `today-undo-${body.action_id}`, tool: "undo_change", arguments: { _source: "today" } } }, 250);
  }
  if (url.pathname === "/__mock/wot/reset") {
    resetWot();
    return respond(200, { ok: true });
  }
  const wotComplete = /^\/wot\/grind\/(\d+)\/complete$/.exec(url.pathname);
  if (wotComplete && req.method === "POST") {
    const g = wotState.grinds.find((x) => x.id === Number(wotComplete[1]));
    if (!g) return respond(404, { detail: { error: "not_found", message: "Grind neexistuje." } });
    if (g.status === "completed") return respond(409, { detail: { error: "already_completed", message: "Grind už je splněný." } }, 300);
    const before = g.xp_remaining;
    Object.assign(g, { status: "completed", xp_remaining: 0, progress: 100 });
    const cid = ++wotState.seq;
    const completion = { id: `completion:${cid}`, completion_id: cid, grind_id: g.id, tank: g.tank, completed_at: wotNow(), started_at: g.started_at,
      xp_start: g.xp_start, xp_remaining_before: before, duration_days: g.started_at ? 30 : null, source: "manual", legacy: false };
    wotState.completed.unshift(completion);
    return respond(200, { ok: true, grind: g, completion }, 350);
  }
  if (url.pathname === "/wot/grinds/completed" && req.method === "GET") return respond(200, wotState.completed);
  if (url.pathname === "/wot/milestones" && req.method === "GET") {
    return respond(200, wotState.milestones.map((m) => ({ ...m, replay_ids: wotState.replays.filter((r) => r.linked_milestone_id === m.id).map((r) => r.id) })));
  }
  if (url.pathname === "/wot/milestones" && req.method === "POST") {
    if (!String(body?.tank ?? "").trim()) return respond(400, { detail: { error: "invalid_tank", message: "Vyplň pole tank." } });
    const m = { id: ++wotState.seq, milestone_type: "mastery", mastery: null, map_name: null, played_on: null, damage: null, assist: null, kills: null,
      base_xp: null, notes: null, favorite: false, ...body, tank: String(body.tank).trim(), created_at: wotNow(), updated_at: wotNow(), screenshots: [] };
    wotState.milestones.unshift(m);
    return respond(200, m, 250);
  }
  const wotMs = /^\/wot\/milestones\/(\d+)$/.exec(url.pathname);
  if (wotMs) {
    const m = wotMilestone(Number(wotMs[1]));
    if (!m) return respond(404, { detail: { error: "not_found", message: "Milník neexistuje." } });
    if (req.method === "PATCH") {
      Object.assign(m, body ?? {}, { updated_at: wotNow() });
      return respond(200, m, 200);
    }
    if (req.method === "DELETE") {
      wotState.milestones = wotState.milestones.filter((x) => x.id !== m.id);
      return respond(200, { ok: true, id: m.id, files_removed: m.screenshots.length }, 200);
    }
  }
  const wotUpload = /^\/wot\/milestones\/(\d+)\/screenshots$/.exec(url.pathname);
  if (wotUpload && req.method === "POST") {
    const m = wotMilestone(Number(wotUpload[1]));
    if (!m) return respond(404, { detail: { error: "not_found", message: "Milník neexistuje." } });
    const sid = ++wotState.seq;
    const shot = { id: sid, url: `/wot/screenshots/${sid}/file`, caption: url.searchParams.get("caption"), original_name: url.searchParams.get("filename"),
      content_type: "image/png", size_bytes: 1000, position: m.screenshots.length, created_at: wotNow() };
    m.screenshots.push(shot);
    wotState.files.set(sid, true);
    return respond(200, shot, 250);
  }
  const wotShot = /^\/wot\/screenshots\/(\d+)(\/file)?$/.exec(url.pathname);
  if (wotShot) {
    const sid = Number(wotShot[1]);
    if (wotShot[2] && req.method === "GET") {
      if (sid === 5) return respond(404, { detail: "Soubor neexistuje." });
      const png = stubPng(sid % 2 ? 320 : 256, sid % 2 ? 180 : 192, SHOT_COLORS[sid % SHOT_COLORS.length]);
      res.writeHead(200, { "Content-Type": "image/png", "Access-Control-Allow-Origin": req.headers.origin || "*", "Access-Control-Allow-Credentials": "true", "Cache-Control": "private, max-age=60" });
      return res.end(png);
    }
    const owner = wotState.milestones.find((m) => m.screenshots.some((s) => s.id === sid));
    if (!owner) return respond(404, { detail: { error: "not_found", message: "Screenshot neexistuje." } });
    if (req.method === "DELETE") {
      owner.screenshots = owner.screenshots.filter((s) => s.id !== sid);
      return respond(200, { ok: true, id: sid, file_removed: true });
    }
    if (req.method === "PATCH") {
      const s = owner.screenshots.find((x) => x.id === sid);
      if (body && "caption" in body) s.caption = body.caption;
      return respond(200, s);
    }
  }
  // ----- Game Enrichment C: knihovna replayů -----
  if (url.pathname === "/__mock/wot/milestones-empty") {
    wotState.milestones = [];
    return respond(200, { ok: true });
  }
  // „Vytvořit Mko z tohoto replaye" – jako backend: z údajů replaye, rovnou propojí; propojený → 409, bez tanku → 422
  const fromReplay = /^\/wot\/replays\/(\d+)\/milestone$/.exec(url.pathname);
  if (fromReplay && req.method === "POST") {
    const r = wotState.replays.find((x) => x.id === Number(fromReplay[1]));
    if (!r) return respond(404, { detail: { error: "not_found", message: "Replay neexistuje." } });
    if (r.linked_milestone_id && wotMilestone(r.linked_milestone_id)) return respond(409, { detail: { error: "already_linked", message: "Replay už je propojený s Mkem." } });
    const tank = r.tank_name || (r.tank_tag ? r.tank_tag.split(":").slice(1).join(":") : "");
    if (!tank) return respond(422, { detail: { error: "missing_tank", message: "Replay nemá tank – doplň ho v údajích replaye." } });
    const m = { id: ++wotState.seq, milestone_type: "mastery", mastery: r.mastery ?? null, tank, map_name: r.map_name ?? null,
      played_on: r.played_at ? String(r.played_at).slice(0, 10) : null, damage: r.damage ?? null, assist: r.assist ?? null, kills: r.kills ?? null,
      base_xp: r.base_xp ?? null, notes: null, favorite: false, created_at: wotNow(), updated_at: wotNow(), screenshots: [] };
    wotState.milestones.unshift(m);
    r.linked_milestone_id = m.id;
    return respond(200, { replay: replayView(r), milestone: m }, 300);
  }
  if (url.pathname === "/__mock/wot/replays-empty") {
    wotState.replays = [];
    return respond(200, { ok: true });
  }
  if (url.pathname === "/wot/replays" && req.method === "GET") return respond(200, replayList(url.searchParams), 150);
  if (url.pathname === "/wot/replays" && req.method === "POST") {
    const name = url.searchParams.get("filename") || "";
    const data = req.rawBody ?? Buffer.alloc(0);
    if (!name.toLowerCase().endsWith(".wotreplay") || !data.length) {
      return respond(400, { detail: { error: "invalid_file", message: !data.length ? "Soubor je prázdný." : "Nahrát jde jen soubor .wotreplay." } }, 300);
    }
    const sha = createHash("sha256").update(data).digest("hex");
    const dup = wotState.replays.find((r) => r.sha256 === sha);
    if (dup) return respond(409, { detail: { error: "duplicate", message: "Tenhle replay už v knihovně je.", replay_id: dup.id } }, 400);
    let r;
    if (sha === REPLAY_UPLOAD.sha256) r = { ...REPLAY_UPLOAD, original_filename: name };
    else if (data.subarray(0, 4).equals(REPLAY_MAGIC)) {
      r = { ...REPLAY_UPLOAD, sha256: sha, original_filename: name, parser_status: "unsupported", parser_warnings: ["Hlavičku replaye se nepodařilo přečíst (neznámá verze formátu)."],
        tank_tag: null, map_name: null, played_at: null, damage: null, assist: null, kills: null, base_xp: null, mastery: null, battle_result: null, game_version: null };
    } else return respond(400, { detail: { error: "invalid_file", message: "Soubor nevypadá jako replay World of Tanks." } }, 300);
    const id = ++wotState.seq;
    // jako backend: lidský název z manifestu (frontend) se uloží jen k rozpoznanému vozidlu
    const hint = (url.searchParams.get("tank_name") || "").split(/\s+/).filter(Boolean).join(" ");
    if (r.tank_tag && hint && hint.length <= 100) r = { ...r, tank_name: hint };
    r = { ...r, id, file_size: data.length, download_url: `/wot/replays/${id}/file`, uploaded_at: wotNow(), created_at: wotNow(), updated_at: wotNow(), tags: [], favorite: false, linked_milestone_id: null };
    wotState.replays.push(r);
    return respond(200, replayView(r), 600);
  }
  const wotReplay = /^\/wot\/replays\/(\d+)(\/file)?$/.exec(url.pathname);
  if (wotReplay) {
    const r = wotState.replays.find((x) => x.id === Number(wotReplay[1]));
    if (!r) return respond(404, { detail: { error: "not_found", message: "Replay neexistuje." } });
    if (wotReplay[2] && req.method === "GET") {
      res.writeHead(200, { "Content-Type": "application/octet-stream", "Content-Disposition": `attachment; filename="${r.original_filename || `replay-${r.id}.wotreplay`}"`,
        "Access-Control-Allow-Origin": req.headers.origin || "*", "Access-Control-Allow-Credentials": "true" });
      return res.end(Buffer.concat([REPLAY_MAGIC, Buffer.from(r.sha256)]));
    }
    if (req.method === "GET") return respond(200, replayView(r));
    if (req.method === "PATCH") {
      const b = { ...(body ?? {}) };
      if ("linked_milestone_id" in b && b.linked_milestone_id != null && !wotMilestone(b.linked_milestone_id)) {
        return respond(404, { detail: { error: "milestone_not_found", message: "Milník neexistuje." } });
      }
      if ("played_at" in b && b.played_at && b.played_at.length === 10) b.played_at = `${b.played_at}T10:00:00Z`;
      Object.assign(r, b, { updated_at: wotNow() });
      return respond(200, replayView(r), 300);
    }
    if (req.method === "DELETE") {
      wotState.replays = wotState.replays.filter((x) => x.id !== r.id);
      return respond(200, { ok: true, id: r.id, file_removed: true }, 300);
    }
  }
  if (handleAi(req, url, body, respond)) return;
  if (req.method === "GET") {
    if (url.pathname === "/reminders") {
      return respond(200, fixture(url.searchParams.get("status") === "all" ? "reminders-all" : "reminders-active"));
    }
    if (url.pathname === "/planner") {
      const mode = url.searchParams.get("mode") || "daily";
      return respond(200, fixture(["daily", "weekly", "goal_review"].includes(mode) ? `planner-${mode}` : "planner-daily"));
    }
    const activityDetail = /^\/activity\/(\d+)$/.exec(url.pathname);
    if (activityDetail) {
      const item = fixture("activity-details")[activityDetail[1]];
      return item ? respond(200, item) : respond(404, { detail: "ActivityLog not found" });
    }
    if (url.pathname.startsWith("/weekly-review/week/")) return respond(200, fixture("weekly-review"));
    const route = GET_ROUTES[url.pathname];
    return route ? respond(200, route()) : respond(404, { detail: "Mock: neznámá cesta" });
  }
  // Zápisy: úspěch po krátké prodlevě (UI ukáže busy stav), data se nemění.
  return respond(200, {}, ACTION_DELAY_MS);
}).listen(PORT, "127.0.0.1", () => console.log(`[mock-api] http://127.0.0.1:${PORT}`));
