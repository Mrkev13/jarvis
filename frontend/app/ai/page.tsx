"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatHeader } from "@/components/ai/ChatHeader";
import { Composer } from "@/components/ai/Composer";
import { ConversationPanel } from "@/components/ai/ConversationPanel";
import { MessageList } from "@/components/ai/MessageList";
import { Drawer } from "@/components/ui";
import { useAiChat } from "@/hooks/useAiChat";
import { useAiVoice } from "@/hooks/useAiVoice";
import { useConversations } from "@/hooks/useConversations";
import { MAIN_CONTENT_ID } from "@/lib/shell";

/**
 * AI asistent (Roadmap 4C). Stránka jen skládá části: konverzace (useConversations), chat a akce
 * (useAiChat), hlas (useAiVoice) a komponenty v components/ai. Chování a API se proti dřívějšku nemění.
 */
export default function AiPage() {
  const convs = useConversations();
  const [draft, setDraft] = useState("");
  const [forceScroll, setForceScroll] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const sendRef = useRef<(text: string) => void>(() => undefined);

  const voice = useAiVoice({
    onDictated: (text) => setDraft((prev) => (prev ? `${prev} ${text}` : text)),
    onAutoSend: (text) => queueMicrotask(() => sendRef.current(text)),
  });
  const { stop: stopSpeech, resetTranscript } = voice.stt;
  const refreshList = convs.refresh;

  const chat = useAiChat({
    activeId: convs.activeId,
    beforeSend: () => {
      stopSpeech();
      resetTranscript();
    },
    // Jen seznam (název, pořadí) – historie v prohlížeči už odpovídá serveru a nesmí přijít o kartu plánu
    // ani o právě navržené akce.
    onAnswered: (id) => void refreshList(id),
  });
  const { loadMessages, reset } = chat;

  const send = useCallback(
    (text: string) => {
      if (!text.trim() || chat.sending || convs.activeId == null) return;
      setDraft("");
      setForceScroll((k) => k + 1);
      void chat.send(text);
    },
    [chat, convs.activeId],
  );
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  // první načtení: seznam → aktivní konverzace → její zprávy (prázdný seznam založí nový chat)
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(async () => {
      const id = await refreshList();
      if (!cancelled && id != null) await loadMessages(id);
    });
    return () => {
      cancelled = true;
    };
  }, [refreshList, loadMessages]);

  const focusComposer = () => window.setTimeout(() => textareaRef.current?.focus(), 60);

  async function select(id: number) {
    setDrawerOpen(false);
    if (id !== convs.activeId) {
      convs.setActiveId(id);
      reset();
      await loadMessages(id);
    }
    focusComposer();
  }

  async function newChat() {
    setCreating(true);
    const id = await convs.create();
    setCreating(false);
    if (id == null) return;
    convs.setActiveId(id);
    reset();
    setDrawerOpen(false);
    focusComposer();
  }

  async function refresh() {
    const id = await convs.refresh(convs.activeId);
    if (id != null) await loadMessages(id);
  }

  async function remove(id: number) {
    const next = await convs.remove(id);
    if (next != null) {
      reset();
      await loadMessages(next);
    }
  }

  const active = convs.conversations.find((c) => c.id === convs.activeId) ?? null;

  const panel = (showHeading: boolean) => (
    <ConversationPanel
      conversations={convs.conversations}
      activeId={convs.activeId}
      loading={convs.loading}
      refreshing={convs.refreshing}
      error={convs.error}
      creating={creating}
      onNew={() => void newChat()}
      onRefresh={() => void refresh()}
      onSelect={(id) => void select(id)}
      onRename={convs.rename}
      onDelete={remove}
      showHeading={showHeading}
    />
  );

  return (
    <main
      id={MAIN_CONTENT_ID}
      tabIndex={-1}
      className="flex h-[calc(100dvh-var(--mobile-header-h))] min-h-0 w-full focus:outline-none md:h-dvh"
    >
      <aside aria-label="Konverzace" className="hidden w-72 shrink-0 flex-col border-r border-line bg-surface/40 p-4 lg:flex">
        {panel(true)}
      </aside>

      <section aria-label="Chat" className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          title={active?.title ?? null}
          onOpenConversations={() => setDrawerOpen(true)}
          conversationsOpen={drawerOpen}
          onNew={() => void newChat()}
          creating={creating}
        />
        <MessageList
          conversationId={convs.activeId}
          history={chat.history}
          loading={chat.loadingMessages || (convs.loading && convs.activeId == null)}
          error={chat.messagesError ?? (convs.activeId == null && !convs.loading ? convs.error : null)}
          onRetryLoad={() => void refresh()}
          sending={chat.sending}
          pendingActions={chat.pendingActions}
          confirmingId={chat.confirmingId}
          failedAction={chat.failedAction}
          outcomes={chat.outcomes}
          tts={
            voice.tts.supported
              ? { enabled: voice.tts.enabled, activeKey: voice.tts.activeKey, locale: voice.stt.locale, play: voice.tts.play, stop: voice.tts.stop }
              : null
          }
          onConfirm={(a) => void chat.confirm(a)}
          onReject={(a) => void chat.reject(a)}
          onUndo={(o) => void chat.requestUndo(o)}
          onPickSuggestion={(text) => {
            setDraft(text);
            focusComposer();
          }}
          forceScrollKey={forceScroll}
        />
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => send(draft)}
          sending={chat.sending}
          disabled={convs.activeId == null}
          failure={chat.failure}
          onRetry={() => chat.failure && send(chat.failure.prompt)}
          onDismissFailure={chat.dismissFailure}
          voice={voice}
          textareaRef={textareaRef}
        />
      </section>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Konverzace" width="sm">
        <div className="flex h-full min-h-0 flex-col p-4">{panel(false)}</div>
      </Drawer>
    </main>
  );
}
