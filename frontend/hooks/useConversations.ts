"use client";

import { useCallback, useRef, useState } from "react";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { mapConversation, type Conversation } from "@/lib/aiChat";

type RawConversation = { id: number; title: string; created_at?: unknown; updated_at?: unknown };

/**
 * Seznam konverzací AI asistenta a aktivní konverzace (Roadmap 4C: z page.tsx beze změny chování –
 * prázdný seznam založí nový chat; po smazání aktivní konverzace se přepne na další nebo založí nový).
 */
export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveIdState] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef<number | null>(null);
  const listRef = useRef<Conversation[]>([]);

  const setActiveId = useCallback((id: number | null) => {
    activeRef.current = id;
    setActiveIdState(id);
  }, []);

  const setList = useCallback((updater: (prev: Conversation[]) => Conversation[]) => {
    setConversations((prev) => {
      const next = updater(prev);
      listRef.current = next;
      return next;
    });
  }, []);

  const create = useCallback(async (): Promise<number | null> => {
    try {
      const data = await apiJson<RawConversation>("/conversations", jsonBody("POST", { title: null }));
      const created = mapConversation(data);
      setList((prev) => [created, ...prev]);
      return created.id;
    } catch (err) {
      setError(errorMessage(err, "Nový chat se nepodařilo založit."));
      return null;
    }
  }, [setList]);

  /** Načte seznam; vrátí id konverzace, která má být aktivní (preferovaná → aktivní → první → nová). */
  const refresh = useCallback(
    async (preferId?: number | null): Promise<number | null> => {
      setRefreshing(true);
      setError(null);
      try {
        const data = await apiJson<RawConversation[]>("/conversations");
        const items = (data ?? []).map(mapConversation);
        setList(() => items);
        let next: number | null = preferId ?? activeRef.current ?? items[0]?.id ?? null;
        if (next == null) next = await create();
        if (next != null) setActiveId(next);
        return next;
      } catch (err) {
        setError(errorMessage(err, "Konverzace se nepodařilo načíst."));
        return null;
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [create, setActiveId, setList],
  );

  const rename = useCallback(
    async (id: number, title: string): Promise<boolean> => {
      const trimmed = title.trim();
      if (!trimmed) return false;
      try {
        const data = await apiJson<RawConversation>(`/conversations/${id}`, jsonBody("PATCH", { title: trimmed }));
        const updated = mapConversation(data);
        setList((prev) => prev.map((c) => (c.id === id ? { ...c, title: updated.title, updatedAt: updated.updatedAt } : c)));
        return true;
      } catch (err) {
        setError(errorMessage(err, "Chat se nepodařilo přejmenovat."));
        return false;
      }
    },
    [setList],
  );

  /** Smaže konverzaci; když byla aktivní, vrátí id další (nebo nově založené), jinak null. */
  const remove = useCallback(
    async (id: number): Promise<number | null> => {
      try {
        await apiJson(`/conversations/${id}`, { method: "DELETE" });
      } catch (err) {
        setError(errorMessage(err, "Chat se nepodařilo smazat."));
        return null;
      }
      const rest = listRef.current.filter((c) => c.id !== id);
      setList(() => rest);
      if (activeRef.current !== id) return null;
      const next = rest[0]?.id ?? (await create());
      setActiveId(next ?? null);
      return next ?? null;
    },
    [create, setActiveId, setList],
  );

  return { conversations, activeId, setActiveId, loading, refreshing, error, refresh, create, rename, remove };
}

export type Conversations = ReturnType<typeof useConversations>;
