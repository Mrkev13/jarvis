"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";

type NotificationItem = {
  id: number;
  area: string;
  title: string;
  message: string;
  severity: "info" | "warning" | "important" | string;
  read: boolean;
  created_at: string | null;
  action_url?: string | null;
  resolved?: boolean;
};

type NotificationSummary = {
  unread: number;
  important: number;
  warning: number;
  info: number;
};

function formatTime(value?: string | null) {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function severityBadge(severity: string) {
  const s = severity.toLowerCase();
  if (s === "important") {
    return "bg-red-500/15 border-red-500/40 text-red-300";
  }
  if (s === "warning") {
    return "bg-yellow-500/15 border-yellow-500/40 text-yellow-300";
  }
  return "bg-sky-500/15 border-sky-500/40 text-sky-300";
}

export default function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState<NotificationSummary>({
    unread: 0,
    important: 0,
    warning: 0,
    info: 0,
  });
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);

  const unread = summary.unread || 0;

  const refreshSummary = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/notifications/summary"));
      if (!res.ok) return;
      const data = (await res.json()) as NotificationSummary;
      setSummary({
        unread: Number(data.unread) || 0,
        important: Number(data.important) || 0,
        warning: Number(data.warning) || 0,
        info: Number(data.info) || 0,
      });
    } catch {
      return;
    }
  }, []);

  async function refreshList() {
    try {
      const res = await fetch(apiUrl("/notifications"));
      if (!res.ok) return;
      const data = (await res.json()) as NotificationItem[];
      setItems(Array.isArray(data) ? data : []);
    } catch {
      return;
    }
  }

  async function ensureGenerated() {
    try {
      await fetch(apiUrl("/notifications/generate"), { method: "POST" });
    } catch {
      return;
    }
  }

  async function openPanel() {
    setOpen(true);
    setLoading(true);
    try {
      await ensureGenerated();
      await Promise.all([refreshSummary(), refreshList()]);
    } finally {
      setLoading(false);
    }
  }

  async function markRead(id: number) {
    try {
      await fetch(apiUrl(`/notifications/${id}/read`), { method: "PATCH" });
      await Promise.all([refreshSummary(), refreshList()]);
    } catch {
      return;
    }
  }

  async function resolve(id: number) {
    try {
      await fetch(apiUrl(`/notifications/${id}/resolve`), { method: "PATCH" });
      await Promise.all([refreshSummary(), refreshList()]);
    } catch {
      return;
    }
  }

  async function readAll() {
    try {
      await fetch(apiUrl("/notifications/read-all"), { method: "PATCH" });
      await Promise.all([refreshSummary(), refreshList()]);
    } catch {
      return;
    }
  }

  useEffect(() => {
    queueMicrotask(() => {
      void refreshSummary();
    });
    const t = window.setInterval(() => {
      void refreshSummary();
    }, 30000);
    return () => window.clearInterval(t);
  }, [refreshSummary]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  const sorted = useMemo(() => {
    return [...items].sort((a, b) => {
      const at = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bt = b.created_at ? new Date(b.created_at).getTime() : 0;
      return bt - at;
    });
  }, [items]);

  return (
    <>
      <button
        type="button"
        aria-label="Notifikace"
        onClick={() => (open ? setOpen(false) : void openPanel())}
        className="relative px-3 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors text-sm"
      >
        <span className="select-none">🔔</span>
        {unread > 0 && (
          <span className="ml-2 inline-flex items-center justify-center px-2 py-0.5 text-xs font-semibold rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-200">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            className="absolute right-0 top-0 h-full w-full md:h-auto md:top-16 md:right-6 md:w-[520px] bg-zinc-950 border border-zinc-800 md:rounded-2xl shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
              <div>
                <div className="text-sm font-semibold">Notifikace</div>
                <div className="text-xs text-zinc-500">
                  Unread: {summary.unread} · Important: {summary.important} · Warning:{" "}
                  {summary.warning}
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={readAll}
                  className="text-xs px-3 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                >
                  Přečíst vše
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="text-xs px-3 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                >
                  Zavřít
                </button>
              </div>
            </div>

            <div className="max-h-[calc(100vh-120px)] md:max-h-[70vh] overflow-y-auto p-3 space-y-2">
              {loading && (
                <div className="text-sm text-zinc-500 px-2 py-3">Načítám…</div>
              )}
              {!loading && sorted.length === 0 && (
                <div className="text-sm text-zinc-500 px-2 py-6">
                  Zatím žádné aktivní notifikace.
                </div>
              )}

              {sorted.map((n) => (
                <div
                  key={n.id}
                  className={`border rounded-2xl p-4 ${
                    n.read ? "border-zinc-800 bg-zinc-900/40" : "border-zinc-700 bg-zinc-900"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className={`px-2 py-0.5 text-xs rounded-full border ${severityBadge(
                            n.severity,
                          )}`}
                        >
                          {String(n.severity).toUpperCase()}
                        </span>
                        <span className="text-xs text-zinc-500 uppercase tracking-wider font-semibold">
                          {n.area}
                        </span>
                        <span className="text-xs text-zinc-500">{formatTime(n.created_at)}</span>
                        {!n.read && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-white text-black font-semibold">
                            UNREAD
                          </span>
                        )}
                      </div>
                      <div className="font-semibold mt-2">{n.title}</div>
                      <div className="text-sm text-zinc-300 mt-1 whitespace-pre-wrap">
                        {n.message}
                      </div>
                    </div>

                    <div className="flex flex-col gap-2 shrink-0">
                      {!n.read && (
                        <button
                          type="button"
                          onClick={() => void markRead(n.id)}
                          className="text-xs px-3 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                        >
                          Přečteno
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void resolve(n.id)}
                        className="text-xs px-3 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                      >
                        Vyřešit
                      </button>
                      {n.action_url && (
                        <button
                          type="button"
                          onClick={() => {
                            window.location.href = String(n.action_url);
                            setOpen(false);
                          }}
                          className="text-xs px-3 py-2 rounded-xl bg-white text-black hover:bg-zinc-200 transition-colors"
                        >
                          Otevřít
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
