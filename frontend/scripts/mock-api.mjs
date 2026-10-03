// Vývojový mock backendu pro vizuální kontrolu UI (Roadmap 4A) – NE produkce, žádný Groq.
// Data v scripts/fixtures/*.json vznikla ze skutečných backendových služeb (seed + fake LLM).
// Spuštění: node scripts/mock-api.mjs  (port 8000, nebo MOCK_API_PORT)
import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const PORT = Number(process.env.MOCK_API_PORT || 8000);
const DELAY_MS = Number(process.env.MOCK_API_DELAY_MS || 0); // simulace pomalé sítě pro skeletony
const ACTION_DELAY_MS = 700; // akce trvají chvíli, aby byl vidět busy stav

const GET_ROUTES = {
  "/auth/session/validate": () => ({ valid: true, auth_disabled: false }),
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

function send(res, req, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": req.headers.origin || "*",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
  });
  res.end(body === undefined ? "" : JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url, "http://mock");
  if (req.method === "OPTIONS") return send(res, req, 204);
  const respond = (status, body, delay = DELAY_MS) => setTimeout(() => send(res, req, status, body), delay);
  if (req.method === "GET") {
    if (url.pathname === "/reminders") {
      return respond(200, fixture(url.searchParams.get("status") === "all" ? "reminders-all" : "reminders-active"));
    }
    if (url.pathname === "/planner") {
      const mode = url.searchParams.get("mode") || "daily";
      return respond(200, fixture(["daily", "weekly", "goal_review"].includes(mode) ? `planner-${mode}` : "planner-daily"));
    }
    if (url.pathname.startsWith("/weekly-review/week/")) return respond(200, fixture("weekly-review"));
    const route = GET_ROUTES[url.pathname];
    return route ? respond(200, route()) : respond(404, { detail: "Mock: neznámá cesta" });
  }
  // Zápisy: úspěch po krátké prodlevě (UI ukáže busy stav), data se nemění.
  return respond(200, {}, ACTION_DELAY_MS);
}).listen(PORT, "127.0.0.1", () => console.log(`[mock-api] http://127.0.0.1:${PORT}`));
