"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";

const AREAS = [
  "finance",
  "work",
  "goals",
  "memory",
  "school",
  "mff",
  "wot",
  "ai",
  "system",
] as const;

const AREA_LABELS: Record<(typeof AREAS)[number], string> = {
  finance: "Finance",
  work: "Work",
  goals: "Goals",
  memory: "Memory",
  school: "School",
  mff: "MFF",
  wot: "WoT",
  ai: "AI",
  system: "System",
};

const ACTION_TYPES = [
  "all",
  "create",
  "update",
  "delete",
  "approve",
  "reject",
  "snapshot",
  "scheduler",
  "backup",
  "expire",
  "sync",
  "error",
] as const;

const ACTION_ICONS: Record<Exclude<(typeof ACTION_TYPES)[number], "all">, string> = {
  create: "✚",
  update: "✎",
  delete: "🗑",
  approve: "✓",
  reject: "✗",
  snapshot: "📊",
  scheduler: "⏰",
  backup: "💾",
  expire: "⧗",
  sync: "⇌",
  error: "⚠",
};

type ActivityItem = {
  id: number;
  timestamp: string;
  area: string;
  action_type: string;
  entity_type: string | null;
  entity_id: number | null;
  summary: string;
  user_context: string | null;
  delta_json?: unknown | null;
};

type ActivityResponse = {
  items: ActivityItem[];
  total: number;
  limit: number;
  offset: number;
};

function formatTime(ts: string) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("cs-CZ", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function dayKey(ts: string) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 10) ?? "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatDayHeader(key: string) {
  if (!key) return key;
  const today = new Date();
  const ty = today.getFullYear();
  const tm = String(today.getMonth() + 1).padStart(2, "0");
  const td = String(today.getDate()).padStart(2, "0");
  const todayKey = `${ty}-${tm}-${td}`;

  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yy = yesterday.getFullYear();
  const ym = String(yesterday.getMonth() + 1).padStart(2, "0");
  const yd = String(yesterday.getDate()).padStart(2, "0");
  const yKey = `${yy}-${ym}-${yd}`;

  if (key === todayKey) return "Dnes";
  if (key === yKey) return "Včera";

  const parts = key.split("-");
  if (parts.length === 3) {
    return `${parts[2]}. ${parts[1]}. ${parts[0]} ⭐`;
  }
  return key + " ⭐";
}

function areaCardClass(area: string, summary: string): string {
  switch (area) {
    case "finance": {
      const s = summary.trimStart();
      if (s.startsWith("+")) return "bg-green-100";
      if (s.startsWith("-")) return "bg-red-100";
      return "bg-gray-100";
    }
    case "work":
      return "bg-blue-100";
    case "goals":
      return "bg-purple-100";
    case "memory":
      return "bg-gray-50";
    case "school":
      return "bg-orange-100";
    case "mff":
      return "bg-teal-100";
    case "wot":
      return "bg-emerald-200";
    case "ai":
      return "bg-sky-100";
    case "system":
      return "bg-slate-200";
    default:
      return "bg-gray-100";
  }
}

function actionIcon(actionType: string): string {
  return (ACTION_ICONS as Record<string, string>)[actionType] ?? "•";
}

function prettyJson(value: unknown | null | undefined): string {
  if (value == null) return "{}";
  try {
    if (typeof value === "string") {
      const parsed = JSON.parse(value);
      return JSON.stringify(parsed, null, 2);
    }
    return JSON.stringify(value, null, 2);
  } catch {
    if (typeof value === "string") return value;
    return String(value);
  }
}

export default function ActivityPage() {
  const [selectedAreas, setSelectedAreas] = useState<Set<string>>(new Set());
  const [actionType, setActionType] = useState<string>("all");
  const [q, setQ] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const PAGE_LIMIT = 20;

  const toggleArea = (area: string) => {
    setSelectedAreas((prev) => {
      const next = new Set(prev);
      if (next.has(area)) {
        next.delete(area);
      } else {
        next.add(area);
      }
      return next;
    });
  };

  const buildQuery = useCallback(
    (currentOffset: number) => {
      const params = new URLSearchParams();
      if (selectedAreas.size > 0) {
        params.set("area", Array.from(selectedAreas).join(","));
      }
      if (actionType !== "all") {
        params.set("action_type", actionType);
      }
      if (q.trim()) {
        params.set("q", q.trim());
      }
      if (fromDate) {
        const from = new Date(fromDate);
        if (!Number.isNaN(from.getTime())) {
          params.set("from", from.toISOString());
        }
      }
      if (toDate) {
        const to = new Date(toDate);
        if (!Number.isNaN(to.getTime())) {
          to.setHours(23, 59, 59, 999);
          params.set("to", to.toISOString());
        }
      }
      params.set("limit", String(PAGE_LIMIT));
      params.set("offset", String(currentOffset));
      return params.toString();
    },
    [selectedAreas, actionType, q, fromDate, toDate]
  );

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = buildQuery(0);
      const res = await fetch(apiUrl(`/activity?${query}`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ActivityResponse;
      setItems(data.items);
      setTotal(data.total);
      setOffset(data.items.length);
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se načíst aktivitu z backendu.");
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  const loadMore = useCallback(async () => {
    if (loadingMore) return;
    if (offset >= total) return;
    setLoadingMore(true);
    setError(null);
    try {
      const query = buildQuery(offset);
      const res = await fetch(apiUrl(`/activity?${query}`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ActivityResponse;
      setItems((prev) => [...prev, ...data.items]);
      setTotal(data.total);
      setOffset((prev) => prev + data.items.length);
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se načíst další záznamy.");
    } finally {
      setLoadingMore(false);
    }
  }, [buildQuery, loadingMore, offset, total]);

  useEffect(() => {
    queueMicrotask(() => {
      void loadInitial().catch(() => {});
    });
  }, [loadInitial]);

  const grouped = useMemo(() => {
    const map = new Map<string, ActivityItem[]>();
    for (const item of items) {
      const key = dayKey(item.timestamp);
      if (!map.has(key)) {
        map.set(key, []);
      }
      map.get(key)!.push(item);
    }
    return Array.from(map.entries());
  }, [items]);

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const resetFilters = () => {
    setSelectedAreas(new Set());
    setActionType("all");
    setQ("");
    setFromDate("");
    setToDate("");
  };

  const hasMore = offset < total;

  return (
    <main className="p-4 md:p-8 max-w-7xl mx-auto space-y-8">
      <header>
        <h1 className="text-2xl md:text-4xl font-bold">📜 Aktivita</h1>
        <p className="text-zinc-400 mt-2">
          Časová osa auditních záznamů napříč všemi moduly.
        </p>
      </header>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <div className="flex flex-col md:grid md:grid-cols-3 gap-6">
        <section className="md:col-span-1 space-y-5 bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6 h-fit">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Filtry</h2>
            <button
              type="button"
              onClick={resetFilters}
              className="text-xs text-zinc-400 hover:text-white underline underline-offset-2"
            >
              Resetovat
            </button>
          </div>

          <div>
            <label className="block text-sm text-zinc-400 mb-2">
              Oblast (Area)
            </label>
            <div className="grid grid-cols-2 md:grid-cols-1 gap-2">
              {AREAS.map((area) => {
                const checked = selectedAreas.has(area);
                return (
                  <label
                    key={area}
                    className="flex items-center gap-2 text-sm cursor-pointer select-none p-2 rounded-lg hover:bg-zinc-800/60 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleArea(area)}
                      className="w-4 h-4 accent-indigo-500"
                    />
                    <span className={checked ? "text-white" : "text-zinc-300"}>
                      {AREA_LABELS[area]}
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <div>
            <label
              htmlFor="action-type"
              className="block text-sm text-zinc-400 mb-2"
            >
              Typ akce
            </label>
            <select
              id="action-type"
              value={actionType}
              onChange={(e) => setActionType(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
            >
              {ACTION_TYPES.map((at) => (
                <option key={at} value={at}>
                  {at === "all" ? "Všechny" : at}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="q-search" className="block text-sm text-zinc-400 mb-2">
              Hledat v popisu
            </label>
            <input
              id="q-search"
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Hledat v popisu..."
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="from-date" className="block text-sm text-zinc-400 mb-2">
                Od
              </label>
              <input
                id="from-date"
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
              />
            </div>
            <div>
              <label htmlFor="to-date" className="block text-sm text-zinc-400 mb-2">
                Do
              </label>
              <input
                id="to-date"
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
              />
            </div>
          </div>

          <div className="pt-2 border-t border-zinc-800">
            <div className="text-xs text-zinc-400">
              Zobrazeno {items.length} z {total}
            </div>
          </div>
        </section>

        <section className="md:col-span-2 space-y-6">
          {loading ? (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
              Načítám aktivitu...
            </div>
          ) : grouped.length === 0 ? (
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
              Zatím žádné záznamy aktivity.
            </div>
          ) : (
            grouped.map(([dayKeyName, dayItems]) => (
              <div key={dayKeyName} className="space-y-3">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm md:text-base font-semibold text-zinc-300">
                    {formatDayHeader(dayKeyName)}
                  </h3>
                  <div className="flex-1 h-px bg-zinc-800" />
                  <span className="text-xs text-zinc-500">
                    {dayItems.length}
                  </span>
                </div>
                <div className="space-y-2">
                  {dayItems.map((item) => {
                    const expanded = expandedIds.has(item.id);
                    return (
                      <div
                        key={item.id}
                        className={`border border-zinc-200/60 rounded-xl overflow-hidden shadow-sm ${areaCardClass(
                          item.area,
                          item.summary
                        )}`}
                      >
                        <button
                          type="button"
                          onClick={() => toggleExpand(item.id)}
                          className="w-full text-left p-3 md:p-4 flex items-start gap-3 hover:brightness-95 transition"
                        >
                          <div className="text-xl leading-none shrink-0 pt-0.5 w-8 text-center">
                            {actionIcon(item.action_type)}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap text-xs text-zinc-700 mb-1">
                              <span className="font-mono bg-white/50 px-1.5 py-0.5 rounded">
                                {item.area}
                              </span>
                              <span className="font-mono bg-white/50 px-1.5 py-0.5 rounded">
                                {item.action_type}
                              </span>
                              {item.entity_type && (
                                <span className="font-mono bg-white/40 px-1.5 py-0.5 rounded">
                                  {item.entity_type}
                                  {item.entity_id != null ? ` #${item.entity_id}` : ""}
                                </span>
                              )}
                              {item.user_context && (
                                <span className="font-mono bg-white/40 px-1.5 py-0.5 rounded">
                                  ctx: {item.user_context}
                                </span>
                              )}
                            </div>
                            <div className="text-sm md:text-base font-medium text-zinc-900 break-words">
                              {item.summary}
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <div className="text-xs text-zinc-600 font-mono">
                              {formatTime(item.timestamp)}
                            </div>
                            <div className="text-xs text-zinc-500 mt-0.5">
                              {expanded ? "▲" : "▼"}
                            </div>
                          </div>
                        </button>
                        {expanded && (
                          <div className="border-t border-zinc-300/60">
                            <pre className="bg-slate-900 text-slate-100 p-3 rounded-none text-xs overflow-x-auto whitespace-pre-wrap break-words">
                              {prettyJson(item.delta_json)}
                            </pre>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}

          {!loading && grouped.length > 0 && (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={() => void loadMore()}
                disabled={!hasMore || loadingMore}
                className="bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-6 py-2.5 rounded-lg transition-colors"
              >
                {loadingMore
                  ? "Načítám..."
                  : hasMore
                    ? "Načíst další"
                    : "Vše načteno"}
              </button>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
