// Mock AI asistenta pro vizuální kontrolu (Roadmap 4C) – ŽÁDNÝ Groq. Tvary odpovědí odpovídají backendu:
// /chat {answer, pending_actions[], planner_result?}, chyby 429/500 {error, answer}, /actions/confirm
// {ok, result: {undo_available}}, /actions/undo {ok, pending_action}, /ai/reject/{id}, /conversations CRUD.
// Scénář /chat se volí podle textu zprávy (viz SCENARIOS). Stav je v paměti procesu.
import { readFileSync } from "node:fs";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const iso = (d) => d.toISOString().slice(0, 19); // naive UTC jako backend

let seq = 100;
let actionSeq = 500;
const now = Date.parse("2026-10-11T17:00:00Z");
const conversations = [
  { id: 1, title: "Plán na týden", created_at: iso(new Date(now - 86400000)), updated_at: iso(new Date(now - 3600000)) },
  { id: 2, title: "Finance – září a rezerva na tři měsíce výdajů (dlouhý název)", created_at: iso(new Date(now - 5 * 86400000)), updated_at: iso(new Date(now - 2 * 86400000)) },
  { id: 3, title: "Prázdný chat", created_at: iso(new Date(now - 7 * 86400000)), updated_at: iso(new Date(now - 6 * 86400000)) },
];
const messages = {
  1: [
    { id: 1, role: "user", content: "Co mám dnes dělat?", created_at: iso(new Date(now - 3700000)) },
    {
      id: 2,
      role: "assistant",
      content:
        "## Dnešek\nNejdřív **dokonči úkol Sada** – je po termínu. Pak:\n\n1. Připrav se na `Zkouška fyzika` (15. 10.).\n2. Zapiš včerejší práci.\n\n_Finance jsou v pořádku_, výdaje jsou pod průměrem.",
      created_at: iso(new Date(now - 3650000)),
    },
    { id: 3, role: "assistant", content: "✅ Přidán pracovní záznam.\n\n10. 10. 2026\nKlient XYZ\n6,5 h\n2 437,50 Kč", created_at: iso(new Date(now - 3600000)) },
  ],
  2: [
    { id: 4, role: "user", content: "Kolik jsem utratil v září?", created_at: iso(new Date(now - 2 * 86400000)) },
    { id: 5, role: "assistant", content: "V září jsi utratil **5 090 Kč**, nejvíc za bydlení (2 200 Kč).", created_at: iso(new Date(now - 2 * 86400000 + 60000)) },
    { id: 6, role: "assistant", content: "⚠️ AI má plnou kapacitu (Groq rate limit). Zkus to prosím za 10–20 sekund znovu.", created_at: iso(new Date(now - 2 * 86400000 + 120000)) },
  ],
  3: [],
};

// smazání v mocku napoprvé selže (zastaralý náhled) → stav „Zkusit znovu"; druhý pokus projde
const failOnce = new Set();
const pending = (tool, args, preview) => ({ id: String(++actionSeq), tool, arguments: args, expires_at: null, ...(preview ? { preview } : {}) });

function withFailOnce(action) {
  failOnce.add(action.id);
  return action;
}

const SCENARIOS = [
  {
    match: /denní limit/i,
    status: 429,
    body: () => ({
      error: "AI provider má vyčerpaný denní limit (rate limit tokenů/požadavků za den byl překročen).",
      answer: "⚠️ AI provider má vyčerpaný denní limit.\n\nDenní limit se během pár sekund neobnoví – zkus to prosím později.",
      pending_actions: [],
    }),
  },
  {
    match: /limit/i,
    status: 429,
    body: () => ({
      error: "AI provider nedisponuje (Rate limit 8 000 tokenů/minutu byl překročen).",
      answer: "⚠️ AI provider nedisponuje (Rate limit 8 000 tokenů/minutu byl překročen).\n\nZa 10 sekund by to mělo zase fungovat.",
      pending_actions: [],
    }),
  },
  { match: /chyba/i, status: 500, body: () => ({ error: "Interní chyba: mock", answer: "⚠️ Stala se neočekávaná chyba při volání AI.", pending_actions: [] }) },
  {
    match: /plán|plan/i,
    status: 200,
    body: () => ({ answer: "Plán na tento týden:", pending_actions: [], planner_result: { card_type: "weekly", payload: fixture("planner-weekly") } }),
  },
  {
    match: /zapiš|zapis|práci/i,
    status: 200,
    body: () => ({
      answer: "Připravil jsem zápis práce. Potvrď ho, nebo zamítni.",
      pending_actions: [pending("add_work_session", { date_value: "2026-10-10", hours: 6.5, project: "Klient XYZ", hourly_rate: 375, description: "Workshop" })],
    }),
  },
  {
    match: /smaž|smaz/i,
    status: 200,
    body: () => ({
      answer: "Našel jsem 12 transakcí za oběd. Smazání proběhne až po potvrzení.",
      pending_actions: [
        withFailOnce(pending("modify_records", {}, {
          kind: "delete",
          entity: "finance_transaction",
          title: "Smazat transakce",
          count: 12,
          warnings: ["Smazané transakce nepůjde obnovit z aplikace."],
          items: Array.from({ length: 12 }, (_, i) => ({ label: `${i + 1}. 10. 2026 · Oběd · 189,90 Kč`, changes: [] })),
        })),
      ],
    }),
  },
  {
    match: /uprav|změň|zmen/i,
    status: 200,
    body: () => ({
      answer: "Připravil jsem úpravu k potvrzení.",
      pending_actions: [
        pending("modify_records", {}, {
          kind: "update",
          entity: "finance_transaction",
          title: "Upravit transakci",
          count: 1,
          warnings: [],
          items: [{ label: "9. 10. 2026 · Jídlo · oběd s kolegy", changes: [{ label: "Částka", old: "320 Kč", new: "450 Kč" }, { label: "Popis", old: "oběd s kolegy", new: "oběd s týmem" }] }],
        }),
      ],
    }),
  },
  {
    match: /.*/,
    status: 200,
    body: (text) => ({
      answer: `## Odpověď\nRozumím: _${text}_.\n\n- Úkoly: **1 po termínu**\n- Práce tento měsíc: 31,5 h\n\n\`\`\`\nukázkový blok kódu\n\`\`\``,
      pending_actions: [],
    }),
  },
];

function touch(id) {
  const c = conversations.find((x) => x.id === id);
  if (c) c.updated_at = iso(new Date());
}

/** Vrátí true, když požadavek obsloužil. */
export function handleAi(req, url, body, respond) {
  const p = url.pathname;
  if (p === "/conversations" && req.method === "GET") {
    respond(200, [...conversations].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    return true;
  }
  if (p === "/conversations" && req.method === "POST") {
    const c = { id: ++seq, title: (body?.title || "").trim() || "Nový chat", created_at: iso(new Date()), updated_at: iso(new Date()) };
    conversations.unshift(c);
    messages[c.id] = [];
    respond(200, c, 300);
    return true;
  }
  const conv = /^\/conversations\/(\d+)$/.exec(p);
  if (conv) {
    const id = Number(conv[1]);
    const c = conversations.find((x) => x.id === id);
    if (!c) return respond(404, { detail: "conversation_not_found" }), true;
    if (req.method === "PATCH") {
      c.title = String(body?.title || "").trim() || c.title;
      c.updated_at = iso(new Date());
      respond(200, c, 300);
    } else if (req.method === "DELETE") {
      conversations.splice(conversations.indexOf(c), 1);
      respond(200, { ok: true }, 500);
    }
    return true;
  }
  const msgs = /^\/conversations\/(\d+)\/messages$/.exec(p);
  if (msgs) {
    const id = Number(msgs[1]);
    if (!messages[id]) return respond(404, { detail: "conversation_not_found" }), true;
    if (req.method === "GET") respond(200, messages[id], 250);
    else {
      messages[id].push({ id: ++seq, role: body.role, content: body.content, created_at: iso(new Date()) });
      touch(id);
      respond(200, {});
    }
    return true;
  }
  if (p === "/chat" && req.method === "POST") {
    const text = String(body?.message || "");
    const id = Number(body?.conversation_id);
    const s = SCENARIOS.find((x) => x.match.test(text));
    const out = s.body(text);
    if (messages[id]) {
      messages[id].push({ id: ++seq, role: "user", content: text, created_at: iso(new Date()) });
      if (s.status === 200) messages[id].push({ id: ++seq, role: "assistant", content: out.answer, created_at: iso(new Date()) });
      touch(id);
    }
    respond(s.status, out, 900);
    return true;
  }
  if (p === "/actions/confirm" && req.method === "POST") {
    const id = String(body?.action_id || "");
    const failing = failOnce.delete(id);
    respond(200, failing ? { ok: false, error: "action_already_processed", detail: "Akce byla už potvrzena, zamítnuta nebo vypršela." } : { ok: true, tool: "x", arguments: {}, result: { undo_available: true } }, 800);
    return true;
  }
  if (p === "/actions/undo" && req.method === "POST") {
    respond(200, {
      ok: true,
      pending_action: pending("undo_change", {}, {
        kind: "undo",
        entity: "work_session",
        title: "Vrátit změnu",
        count: 1,
        warnings: [],
        items: [{ label: "10. 10. 2026 · 6,5 h · Klient XYZ", changes: [{ label: "Stav", old: "uloženo", new: "smazáno" }] }],
      }),
    }, 400);
    return true;
  }
  if (p.startsWith("/ai/reject/") && req.method === "POST") {
    respond(200, { ok: true, status: "rejected" }, 300);
    return true;
  }
  return false;
}
