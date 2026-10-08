"use client";

import { useEffect, useRef } from "react";
import { API_URL } from "@/lib/api";
import { createDomainEventClient, type DomainEvent, type StreamReset } from "@/lib/domainEvents";

/**
 * MRK-19: jedno sdílené SSE spojení na doménové události pro celou aplikaci (víc posluchačů, jeden stream).
 * Spojení se otevře s prvním posluchačem a zavře s posledním. Pozice se mezi obnoveními stránky neukládá
 * (start = „od teď"); výpadky během běhu dohání EventSource přes Last-Event-ID.
 */
type Listener = { onEvent?: (e: DomainEvent) => void; onReset?: (r: StreamReset) => void };

const listeners = new Set<Listener>();
let client: ReturnType<typeof createDomainEventClient> | null = null;

function ensureClient() {
  if (client || typeof window === "undefined" || typeof EventSource === "undefined") return;
  client = createDomainEventClient({
    baseUrl: API_URL,
    create: (url) => new EventSource(url, { withCredentials: true }),
    onEvent: (e) => listeners.forEach((l) => l.onEvent?.(e)),
    onReset: (r) => listeners.forEach((l) => l.onReset?.(r)),
  });
}

export function useDomainEvents(handlers: Listener) {
  const ref = useRef(handlers);
  useEffect(() => {
    ref.current = handlers;
  });
  useEffect(() => {
    const listener: Listener = {
      onEvent: (e) => ref.current.onEvent?.(e),
      onReset: (r) => ref.current.onReset?.(r),
    };
    listeners.add(listener);
    ensureClient();
    return () => {
      listeners.delete(listener);
      if (!listeners.size && client) {
        client.close();
        client = null;
      }
    };
  }, []);
}
