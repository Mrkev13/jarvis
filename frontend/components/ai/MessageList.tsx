"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { ErrorState, LoadingState } from "@/components/ui";
import type { ActionOutcome } from "@/hooks/useAiChat";
import type { ChatMessage } from "@/lib/aiChat";
import type { PendingAction } from "@/lib/pendingActions";
import { ActionOutcomeCard } from "./ActionOutcomeCard";
import { EmptyConversation } from "./EmptyConversation";
import { MessageItem, ThinkingIndicator, type MessageTts } from "./MessageItem";
import { PendingActionCard } from "./PendingActionCard";

/** Jak blízko u spodku (px) se ještě počítá jako „čtu nejnovější" – pak se nové zprávy dorolují. */
const STICK_PX = 120;

/**
 * Historie konverzace s posunem: nová zpráva / odpověď / karta akce se dorolují, jen když je uživatel
 * u spodku (ruční posun nahoru se respektuje); po přepnutí konverzace nebo odeslání vždy na konec.
 */
export function MessageList({
  conversationId,
  history,
  loading,
  error,
  onRetryLoad,
  sending,
  pendingActions,
  confirmingId,
  failedAction,
  outcomes,
  tts,
  onConfirm,
  onReject,
  onUndo,
  onPickSuggestion,
  forceScrollKey,
}: {
  conversationId: number | null;
  history: ChatMessage[];
  loading: boolean;
  error: string | null;
  onRetryLoad: () => void;
  sending: boolean;
  pendingActions: PendingAction[];
  confirmingId: string | null;
  failedAction: { id: string; attempt: number } | null;
  outcomes: ActionOutcome[];
  tts: MessageTts | null;
  onConfirm: (a: PendingAction) => void;
  onReject: (a: PendingAction) => void;
  onUndo: (o: ActionOutcome) => void;
  onPickSuggestion: (text: string) => void;
  /** Změna = posunout na konec bez ohledu na pozici (odeslání zprávy). */
  forceScrollKey: number;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX;
  }

  // přepnutí konverzace / odeslání → na konec
  useEffect(() => {
    stick.current = true;
  }, [conversationId, forceScrollKey]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [history, sending, pendingActions, outcomes, loading, forceScrollKey]);

  const empty = !loading && !error && history.length === 0 && !sending;

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
      aria-busy={loading || sending}
    >
      <div className="mx-auto w-full max-w-4xl px-4 py-5 md:px-6 md:py-6">
        {loading && history.length === 0 ? (
          <LoadingState lines={4} label="Načítám historii konverzace…" />
        ) : error ? (
          <ErrorState message={error} onRetry={onRetryLoad} />
        ) : empty ? (
          <EmptyConversation onPick={onPickSuggestion} />
        ) : (
          <ol className="space-y-5" aria-label="Zprávy konverzace" aria-live="polite" aria-relevant="additions">
            {history.map((m, i) => (
              <MessageItem key={m.id} message={m} showAuthor={i === 0 || history[i - 1].role !== "assistant"} tts={tts} />
            ))}
            {sending ? <ThinkingIndicator /> : null}
          </ol>
        )}

        {pendingActions.length ? (
          <ul className="mt-5 space-y-3" aria-label="Akce čekající na potvrzení">
            {pendingActions.map((a) => {
              const executing = confirmingId === a.id;
              const failed = !executing && failedAction?.id === a.id;
              return (
                <PendingActionCard
                  // pokus v klíči → animace selhání se přehraje při každém dalším selhání
                  key={`${a.id}-${failed ? failedAction?.attempt : 0}`}
                  action={a}
                  state={executing ? "executing" : failed ? "failed" : "pending"}
                  onConfirm={() => onConfirm(a)}
                  onReject={() => onReject(a)}
                />
              );
            })}
          </ul>
        ) : null}

        {outcomes.length ? (
          <ul className="mt-3 space-y-2" aria-live="polite" aria-label="Výsledky akcí">
            {outcomes.map((o) => (
              <ActionOutcomeCard key={o.key} outcome={o} onUndo={() => onUndo(o)} />
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
