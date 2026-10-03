/**
 * AI asistent (Roadmap 4C): čisté pomocné funkce chatu – mapování odpovědí API, texty chyb, druh zprávy.
 * Sémantika /chat, /conversations a pending akcí se nemění. Testy: aiChat.test.mjs.
 */
import { parseApiInstant } from "./format.ts";

export type ChatRole = "user" | "assistant";

export type PlannerCardLike = { card_type: "daily" | "weekly" | "goal_review"; payload: unknown };

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
  plannerCard?: PlannerCardLike | null;
};

export type Conversation = { id: number; title: string; createdAt: number; updatedAt: number };

/** Okamžik z API (naive UTC) → ms; neplatný/chybějící → teď (jako dřív). */
export function toTs(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value) {
    const t = parseApiInstant(value).getTime();
    if (!Number.isNaN(t)) return t;
  }
  return Date.now();
}

export function mapConversation(raw: { id: number; title: string; created_at?: unknown; updated_at?: unknown }): Conversation {
  return { id: raw.id, title: raw.title, createdAt: toTs(raw.created_at), updatedAt: toTs(raw.updated_at) };
}

export function mapMessage(raw: { id: number; role: ChatRole; content: string; created_at?: unknown }): ChatMessage {
  return { id: `db-${raw.id}`, role: raw.role, content: raw.content, createdAt: toTs(raw.created_at) };
}

/** planner_result z /chat → karta, jen když má známý typ. */
export function plannerCardFrom(raw: unknown): PlannerCardLike | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as { card_type?: unknown; payload?: unknown };
  return r.card_type === "daily" || r.card_type === "weekly" || r.card_type === "goal_review"
    ? { card_type: r.card_type, payload: r.payload }
    : null;
}

export type ChatFailureKind = "rate_limit" | "daily_limit" | "server" | "network" | "other";

export type ChatFailure = {
  kind: ChatFailureKind;
  /** Text do historie (co backend vrátil v `answer`, jinak náš). */
  message: string;
  /** Krátké vysvětlení pro stav nad polem pro zprávu. */
  notice: string;
};

/** Chybová odpověď /chat → text do historie + druh chyby (backend sémantiku neměníme, jen ji čteme). */
export function chatHttpFailure(status: number, body: { error?: unknown; answer?: unknown } | null): ChatFailure {
  const error = typeof body?.error === "string" ? body.error : "";
  const answer = typeof body?.answer === "string" ? body.answer : "";
  const daily = status === 429 && /denní limit/i.test(`${error} ${answer}`);
  const kind: ChatFailureKind = daily ? "daily_limit" : status === 429 ? "rate_limit" : status >= 500 ? "server" : "other";
  const fallback =
    kind === "rate_limit"
      ? "AI má plnou kapacitu (Groq rate limit). Zkus to prosím za 10–20 sekund znovu."
      : kind === "daily_limit"
        ? "AI má vyčerpaný denní limit. Zkus to prosím později."
        : kind === "server"
          ? "AI backend má problém (5xx). Zkus to znovu, nebo restartuj backend."
          : `Server vrátil HTTP ${status}.`;
  const notice =
    kind === "rate_limit"
      ? "AI je teď vytížená – zkus to za 10–20 sekund."
      : kind === "daily_limit"
        ? "Denní limit AI je vyčerpaný – během pár sekund se neobnoví."
        : kind === "server"
          ? "AI backend vrátil chybu."
          : "Zprávu se nepodařilo zpracovat.";
  return { kind, message: answer || (error ? `⚠️ ${error}` : "") || fallback, notice };
}

export function chatNetworkFailure(apiUrl: string): ChatFailure {
  return {
    kind: "network",
    message: `Nepodařilo se připojit k backendu na ${apiUrl}. Je backend spuštěný (run-backend.cmd)?`,
    notice: "Backend je nedostupný.",
  };
}

/** Druh zprávy asistenta pro zobrazení (stavové zprávy jsou kompaktní, obsah zůstává beze změny). */
export type MessageVariant = "normal" | "success" | "warning" | "error";

export function messageVariant(m: Pick<ChatMessage, "role" | "content">): MessageVariant {
  if (m.role !== "assistant") return "normal";
  const t = m.content.trimStart();
  if (t.startsWith("✅")) return "success";
  if (t.startsWith("❌") || /^(Chyba |Chyba AI:|Nepodařilo se)/.test(t)) return "error";
  if (t.startsWith("⚠️")) return "warning";
  return "normal";
}

/** Text stavové zprávy bez úvodního symbolu (symbol nahradí ikona). */
export function stripStatusSymbol(content: string): string {
  return content.replace(/^\s*(✅|❌|⚠️)\s*/u, "");
}
