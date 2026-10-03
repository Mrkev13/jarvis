// Vývojový mock backendu pro vizuální kontrolu UI (Roadmap 4A) – NE produkce, žádný Groq.
// Data v scripts/fixtures/*.json vznikla ze skutečných backendových služeb (seed + fake LLM).
// Spuštění: node scripts/mock-api.mjs  (port 8000, nebo MOCK_API_PORT)
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { handleAi } from "./mock-ai.mjs";

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
  "/wot/grinds": () => fixture("wot-grinds"),
  "/wot/resources": () => fixture("wot-resources"),
  "/activity": () => fixture("activity"),
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
const sessionOf = (req) => /(?:^|;\s*)standa_hub_session=([^;]+)/.exec(req.headers.cookie || "")?.[1] ?? null;

function readBody(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
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
  // Roadmap 4E: Rychlé přidání. /quick-add/parse = odpovědi skutečného quick_add_service (fixtures/quick-add.json,
  // generátor viz docs); neznámý text = „unknown". /quick-add/prepare vrátí pending akci „qa-…", /actions/confirm
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
