"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, apiFetch, apiJson, errorMessage, jsonBody } from "@/lib/api";
import { confirmedMessage, describeAction, rejectedMessage } from "@/lib/aiActions";
import {
  chatHttpFailure,
  chatNetworkFailure,
  mapMessage,
  plannerCardFrom,
  type ChatFailure,
  type ChatMessage,
} from "@/lib/aiChat";
import { MOTION } from "@/lib/motion";
import {
  confirmActionBody,
  isUndoAvailable,
  normalizePendingActions,
  rejectActionPath,
  UNDO_PATH,
  undoActionBody,
  type PendingAction,
} from "@/lib/pendingActions";

/** Jak dlouho zůstane nabídka „Vrátit" u potvrzené změny (pak jde vrátit přes chat „vrať poslední změnu"). */
export const UNDO_OFFER_MS = 20000;

export type ActionOutcome = {
  key: string;
  title: string;
  kind: "success" | "rejected";
  /** id provedené akce, kterou backend umí vrátit → u výsledku tlačítko „Vrátit". */
  undoActionId?: string;
};

type RawMessage = { id: number; role: "user" | "assistant"; content: string; created_at?: unknown };

let localSeq = 0;
const localId = (prefix: string) => `${prefix}-${Date.now()}-${++localSeq}`;

/**
 * Stav jedné konverzace AI asistenta (Roadmap 4C: logika z page.tsx beze změny sémantiky):
 * historie, odeslání /chat, pending akce (potvrzení / zamítnutí / vrácení) a krátké výsledky akcí.
 * Lokální zprávy asistenta (výsledky akcí, chyby) se jako dřív ukládají do historie konverzace.
 */
export function useAiChat({
  activeId,
  beforeSend,
  onAnswered,
}: {
  activeId: number | null;
  /** Před odesláním (zastavení diktování). */
  beforeSend?: () => void;
  /** Po úspěšné odpovědi – obnova seznamu konverzací (název, pořadí) bez ztráty pending akcí. */
  onAnswered?: (conversationId: number) => void;
}) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [failure, setFailure] = useState<(ChatFailure & { prompt: string }) | null>(null);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [failedAction, setFailedAction] = useState<{ id: string; attempt: number } | null>(null);
  const [outcomes, setOutcomes] = useState<ActionOutcome[]>([]);

  const activeRef = useRef(activeId);
  const timers = useRef(new Set<number>());
  const callbacks = useRef({ beforeSend, onAnswered });
  useEffect(() => {
    activeRef.current = activeId;
    callbacks.current = { beforeSend, onAnswered };
  });
  useEffect(() => {
    const all = timers.current;
    return () => all.forEach((t) => window.clearTimeout(t));
  }, []);

  /** Zpráva asistenta vzniklá v prohlížeči: zobrazit a uložit do historie konverzace. */
  const appendLocal = useCallback((content: string) => {
    setHistory((h) => [...h, { id: localId("a"), role: "assistant", content, createdAt: Date.now() }]);
    const conversationId = activeRef.current;
    if (conversationId == null) return;
    void apiFetch(`/conversations/${conversationId}/messages`, jsonBody("POST", { role: "assistant", content })).catch(() => undefined);
  }, []);

  const showOutcome = useCallback((title: string, kind: ActionOutcome["kind"], undoActionId?: string) => {
    const key = localId(kind);
    setOutcomes((prev) => [...prev, { key, title, kind, undoActionId }]);
    const t = window.setTimeout(() => {
      timers.current.delete(t);
      setOutcomes((prev) => prev.filter((o) => o.key !== key));
    }, undoActionId ? UNDO_OFFER_MS : MOTION.highlightMs);
    timers.current.add(t);
  }, []);

  /** keepPending: obnova téže konverzace hned po /chat nesmí smazat právě vrácené pending akce. */
  const loadMessages = useCallback(async (conversationId: number, keepPending = false) => {
    setLoadingMessages(true);
    setMessagesError(null);
    try {
      const data = await apiJson<RawMessage[]>(`/conversations/${conversationId}/messages`);
      setHistory((data ?? []).map(mapMessage));
      if (!keepPending) setPendingActions([]);
    } catch (err) {
      setMessagesError(errorMessage(err, "Historii konverzace se nepodařilo načíst."));
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  /** Nová / přepnutá konverzace: prázdná historie, žádné pending akce ani chyby. */
  const reset = useCallback(() => {
    setHistory([]);
    setPendingActions([]);
    setFailure(null);
    setSending(false);
  }, []);

  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const prompt = text.trim();
      const conversationId = activeRef.current;
      if (!prompt || sending || conversationId == null) return false;
      try {
        callbacks.current.beforeSend?.();
      } catch {
        /* ignore */
      }
      setHistory((h) => [...h, { id: localId("u"), role: "user", content: prompt, createdAt: Date.now() }]);
      setSending(true);
      setFailure(null);
      setPendingActions([]);
      try {
        let response: Response;
        try {
          response = await apiFetch("/chat", jsonBody("POST", { conversation_id: conversationId, message: prompt }));
        } catch {
          const f = chatNetworkFailure(API_URL);
          setFailure({ ...f, prompt });
          appendLocal(f.message);
          return true;
        }
        if (!response.ok) {
          let body: { error?: unknown; answer?: unknown } | null = null;
          try {
            body = await response.clone().json();
          } catch {
            body = null;
          }
          const f = chatHttpFailure(response.status, body);
          setFailure({ ...f, prompt });
          appendLocal(f.message);
          return true;
        }
        const data = (await response.json()) as { answer?: string; pending_actions?: unknown; planner_result?: unknown };
        setHistory((h) => [
          ...h,
          { id: localId("a"), role: "assistant", content: data.answer ?? "", createdAt: Date.now(), plannerCard: plannerCardFrom(data.planner_result) },
        ]);
        const incoming = normalizePendingActions(data.pending_actions);
        if (incoming.length) setPendingActions(incoming);
        callbacks.current.onAnswered?.(conversationId);
        return true;
      } catch (err) {
        const msg = `Chyba AI: ${errorMessage(err, "Nepodařilo se spojit s AI backendem.")}`;
        setFailure({ kind: "other", message: msg, notice: "Odpověď se nepodařilo zpracovat.", prompt });
        appendLocal(msg);
        return true;
      } finally {
        setSending(false);
      }
    },
    [appendLocal, sending],
  );

  const confirm = useCallback(
    async (action: PendingAction) => {
      const view = describeAction(action);
      setConfirmingId(action.id);
      const markFailed = () =>
        setFailedAction((prev) => ({ id: action.id, attempt: prev && prev.id === action.id ? prev.attempt + 1 : 1 }));
      try {
        const response = await apiFetch("/actions/confirm", jsonBody("POST", confirmActionBody(action)));
        if (!response.ok) {
          let detail = "";
          try {
            const err = (await response.json()) as { detail?: unknown };
            detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail ?? err);
          } catch {
            /* ignore */
          }
          throw new Error(`HTTP ${response.status}${detail ? ` – ${detail.slice(0, 400)}` : ""}`);
        }
        const data = (await response.json()) as { ok: boolean; detail?: string; error?: string; result?: unknown };
        if (data.ok) {
          appendLocal(confirmedMessage(view, Boolean(action.preview)));
          setPendingActions((prev) => prev.filter((a) => a.id !== action.id));
          setFailedAction(null);
          showOutcome(view.doneTitle, "success", isUndoAvailable(data) ? action.id : undefined);
        } else {
          appendLocal(`❌ Změnu se nepodařilo provést.\n\n${data.detail ?? data.error ?? "Neznámá chyba"}`);
          markFailed();
        }
      } catch (err) {
        markFailed();
        appendLocal(`Chyba potvrzení: ${err instanceof Error ? err.message : "nepodařilo se potvrdit akci."}`);
      } finally {
        setConfirmingId(null);
      }
    },
    [appendLocal, showOutcome],
  );

  const reject = useCallback(
    async (action: PendingAction) => {
      const view = describeAction(action);
      setPendingActions((prev) => prev.filter((a) => a.id !== action.id));
      showOutcome(view.title, "rejected");
      appendLocal(rejectedMessage(view));
      // Zamítnout i na serveru – jinak by akce zůstala potvrditelná do vypršení. 409 = už zpracovaná.
      try {
        const response = await apiFetch(rejectActionPath(action), { method: "POST" });
        if (!response.ok && response.status !== 409) throw new Error(`HTTP ${response.status}`);
      } catch {
        appendLocal("⚠️ Zrušení se nepodařilo uložit na serveru – akce zůstane nepotvrzená a sama vyprší.");
      }
    },
    [appendLocal, showOutcome],
  );

  /** „Vrátit": backend připraví vrácení jako běžnou pending akci → stejná karta s náhledem a potvrzením. */
  const requestUndo = useCallback(
    async (outcome: ActionOutcome) => {
      if (!outcome.undoActionId) return;
      setOutcomes((prev) => prev.filter((o) => o.key !== outcome.key));
      try {
        const data = await apiJson<{ ok?: boolean; pending_action?: unknown; detail?: string }>(
          UNDO_PATH,
          jsonBody("POST", undoActionBody(outcome.undoActionId)),
        );
        const incoming = data.ok ? normalizePendingActions([data.pending_action]) : [];
        if (incoming.length) setPendingActions((prev) => [...prev, ...incoming]);
        else appendLocal(`⚠️ Změnu nejde vrátit: ${data.detail ?? "neznámý důvod"}`);
      } catch {
        appendLocal("⚠️ Vrácení se nepodařilo připravit.");
      }
    },
    [appendLocal],
  );

  return {
    history,
    loadingMessages,
    messagesError,
    sending,
    failure,
    dismissFailure: () => setFailure(null),
    pendingActions,
    confirmingId,
    failedAction,
    outcomes,
    loadMessages,
    reset,
    send,
    confirm,
    reject,
    requestUndo,
  };
}

export type AiChat = ReturnType<typeof useAiChat>;
