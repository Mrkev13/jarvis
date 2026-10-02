"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

type GoalsSummary = {
  active: number;
  in_progress: number;
  completed: number;
  paused: number;
  cancelled: number;
  total: number;
};

type GoalItem = {
  id: number;
  area: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  progress: number;
  tracking_type: "manual" | "automatic" | string;
  target_value: number | null;
  source: string | null;
  current_value: number | null;
  target_date: string | null;
  created_at: string | null;
};

const AREA_OPTIONS = [
  "finance",
  "school",
  "work",
  "wot",
  "mff",
  "personal",
  "travel",
  "fitness",
  "hobby",
];

const STATUS_OPTIONS = [
  "active",
  "in_progress",
  "completed",
  "paused",
  "cancelled",
];

const TRACKING_OPTIONS = [
  { value: "manual", label: "Manuální progress (%)" },
  { value: "automatic", label: "Automaticky (napojen na modul)" },
] as const;

const SOURCE_OPTIONS = [
  {
    value: "finance_balance",
    label: "Finance: Stav účtu (Kč)",
    unit: "Kč",
    placeholder: "150000",
  },
  {
    value: "work_month_hours",
    label: "Work: Hodin za měsíc (h)",
    unit: "h",
    placeholder: "100",
  },
  {
    value: "work_month_earnings",
    label: "Práce – výdělky tento měsíc",
    unit: "Kč",
    placeholder: "80000",
  },
  {
    value: "finance_month_income",
    label: "Finance – příjmy tento měsíc",
    unit: "Kč",
    placeholder: "100000",
  },
  {
    value: "finance_month_expenses",
    label: "Finance – výdaje tento měsíc",
    unit: "Kč",
    placeholder: "50000",
  },
  {
    value: "school_completed_assignments",
    label: "Škola – dokončené úkoly",
    unit: "ks",
    placeholder: "20",
  },
  {
    value: "school_open_assignments",
    label: "Škola – otevřené úkoly",
    unit: "ks",
    placeholder: "10",
  },
  {
    value: "mff_t4_count",
    label: "MFF – celkem T4 postav",
    unit: "ks",
    placeholder: "20",
  },
  {
    value: "mff_built_t4_count",
    label: "MFF – postavené T4",
    unit: "ks",
    placeholder: "15",
  },
  {
    value: "mff_high_priority_built_count",
    label: "MFF – high priority built",
    unit: "ks",
    placeholder: "5",
  },
] as const;

function sourceUnit(source: string | null | undefined): string {
  if (!source) return "";
  return SOURCE_OPTIONS.find((o) => o.value === source)?.unit ?? "";
}

const dateFormatter = new Intl.DateTimeFormat("cs-CZ", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

function areaBadge(area: string) {
  const a = area.trim().toLowerCase();
  const palette: Record<string, string> = {
    finance:
      "bg-green-950/70 border-green-800 text-green-300",
    school:
      "bg-blue-950/70 border-blue-800 text-blue-300",
    work: "bg-purple-950/70 border-purple-800 text-purple-300",
    wot: "bg-amber-950/70 border-amber-800 text-amber-300",
    mff: "bg-pink-950/70 border-pink-800 text-pink-300",
    personal:
      "bg-sky-950/70 border-sky-800 text-sky-300",
    travel:
      "bg-cyan-950/70 border-cyan-800 text-cyan-300",
    fitness:
      "bg-red-950/70 border-red-800 text-red-300",
    hobby:
      "bg-indigo-950/70 border-indigo-800 text-indigo-300",
  };
  const cls = palette[a] ?? "bg-zinc-800 border-zinc-700 text-zinc-300";
  return `px-2.5 py-1 text-xs rounded-lg border font-medium uppercase tracking-wide ${cls}`;
}

function priorityClass(priority: string) {
  const p = priority.trim().toLowerCase();
  if (p === "high") {
    return "px-2 py-0.5 text-xs rounded-full bg-red-950/80 border border-red-800 text-red-300";
  }
  if (p === "medium") {
    return "px-2 py-0.5 text-xs rounded-full bg-yellow-950/70 border border-yellow-800 text-yellow-300";
  }
  if (p === "low") {
    return "px-2 py-0.5 text-xs rounded-full bg-sky-950/70 border border-sky-800 text-sky-300";
  }
  return "px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300";
}

function statusClass(status: string) {
  const s = status.trim().toLowerCase();
  switch (s) {
    case "active":
      return "px-2 py-0.5 text-xs rounded-full bg-indigo-950/70 border border-indigo-800 text-indigo-300";
    case "in_progress":
      return "px-2 py-0.5 text-xs rounded-full bg-blue-950/70 border border-blue-800 text-blue-300";
    case "completed":
      return "px-2 py-0.5 text-xs rounded-full bg-green-950/70 border border-green-800 text-green-300";
    case "paused":
      return "px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300";
    case "cancelled":
      return "px-2 py-0.5 text-xs rounded-full bg-red-950/50 border border-red-900 text-red-300";
    default:
      return "px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300";
  }
}

function clamp(v: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, v));
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("cs-CZ", {
    maximumFractionDigits: 2,
  }).format(value);
}

function progressColor(progress: number, status: string) {
  if (status.trim().toLowerCase() === "completed") return "bg-green-500";
  if (progress >= 80) return "bg-green-500";
  if (progress >= 50) return "bg-yellow-500";
  if (progress >= 20) return "bg-orange-500";
  return "bg-red-500";
}

function todayIso() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

type Draft = {
  id: number | null;
  area: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  progress: string;
  tracking_type: "manual" | "automatic" | string;
  source: string;
  target_value: string;
  target_date: string;
};

const emptyDraft: Draft = {
  id: null,
  area: AREA_OPTIONS[0],
  title: "",
  description: "",
  status: "active",
  priority: "medium",
  progress: "0",
  tracking_type: "manual",
  source: SOURCE_OPTIONS[0].value,
  target_value: "",
  target_date: "",
};

export default function GoalsPage() {
  const [summary, setSummary] = useState<GoalsSummary | null>(null);
  const [goals, setGoals] = useState<GoalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingGoal, setDeletingGoal] = useState<GoalItem | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumRes, listRes] = await Promise.all([
        fetch(apiUrl("/goals/summary")),
        fetch(apiUrl("/goals/list")),
      ]);
      if (!sumRes.ok || !listRes.ok) throw new Error();
      setSummary((await sumRes.json()) as GoalsSummary);
      setGoals((await listRes.json()) as GoalItem[]);
    } catch {
      setError("Nepodařilo se načíst cíle.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  function startEdit(g: GoalItem) {
    setDraft({
      id: g.id,
      area: AREA_OPTIONS.includes(g.area.toLowerCase()) ? g.area.toLowerCase() : AREA_OPTIONS[0],
      title: g.title,
      description: g.description,
      status: STATUS_OPTIONS.includes(g.status.toLowerCase())
        ? g.status.toLowerCase()
        : "active",
      priority: ["high", "medium", "low"].includes(g.priority.toLowerCase())
        ? g.priority.toLowerCase()
        : "medium",
      progress: String(g.progress ?? 0),
      tracking_type:
        g.tracking_type === "automatic" ? "automatic" : "manual",
      source:
        g.source && SOURCE_OPTIONS.some((o) => o.value === g.source)
          ? g.source
          : SOURCE_OPTIONS[0].value,
      target_value: g.target_value != null ? String(g.target_value) : "",
      target_date: g.target_date ?? "",
    });
    setShowForm(true);
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function resetForm() {
    setDraft(emptyDraft);
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.title.trim() || !draft.area) {
      setError("Vyplň název a zvol oblast cíle.");
      return;
    }
    const isAutomatic = draft.tracking_type === "automatic";
    if (isAutomatic && !draft.target_value.trim()) {
      setError("U automatického cíle vyplň cílovou hodnotu.");
      return;
    }
    const progressNum = parseInt(draft.progress, 10);
    const targetFloat = parseFloat(draft.target_value);
    const body = {
      id: draft.id ?? undefined,
      area: draft.area,
      title: draft.title.trim(),
      description: draft.description.trim(),
      status: draft.status,
      priority: draft.priority,
      tracking_type: isAutomatic ? "automatic" : "manual",
      source: isAutomatic ? draft.source : null,
      target_value: isAutomatic && isFinite(targetFloat) ? targetFloat : null,
      progress: isFinite(progressNum) ? clamp(progressNum) : 0,
      target_date: draft.target_date ? draft.target_date : null,
    };

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(apiUrl("/goal"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error();
      resetForm();
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit cíl.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteGoal() {
    if (!deletingGoal) return;
    try {
      const res = await fetch(apiUrl(`/goal/${deletingGoal.id}`), {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete goal");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat cíl.");
    } finally {
      setDeletingGoal(null);
    }
  }

  const activeGoals = goals.filter(
    (g) => ["active", "in_progress"].includes(g.status.toLowerCase()),
  );
  const completedGoals = goals.filter(
    (g) => g.status.toLowerCase() === "completed",
  );
  const otherGoals = goals.filter(
    (g) =>
      !["active", "in_progress", "completed"].includes(g.status.toLowerCase()),
  );

  return (
    <main className="p-4 md:p-8 max-w-5xl mx-auto">
      <header className="mb-6 md:mb-8">
        <h1 className="text-2xl md:text-4xl font-bold">Goals</h1>
        <p className="text-zinc-400 mt-2">
          Sledování cílů napříč všemi oblastmi s přehledem postupu.
        </p>
      </header>

      {error && (
        <div className="mb-6 bg-red-950/50 border border-red-900 text-red-200 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <section className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-8">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-semibold">Overview</h2>
          {!showForm ? (
            <button
              type="button"
              onClick={() => {
                setDraft({
                  ...emptyDraft,
                  area: AREA_OPTIONS[0],
                  status: "active",
                  priority: "medium",
                  target_date: "",
                  progress: "0",
                  tracking_type: "manual",
                  source: SOURCE_OPTIONS[0].value,
                  target_value: "",
                });
                setShowForm(true);
              }}
              className="bg-white text-black font-medium px-5 py-2.5 rounded-xl hover:bg-zinc-200 transition-colors"
            >
              + Add goal
            </button>
          ) : (
            <button
              type="button"
              onClick={resetForm}
              className="text-sm text-zinc-400 hover:text-zinc-200"
            >
              {draft.id ? "Zrušit editaci" : "Zavřít"}
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Active</div>
            <div className="text-2xl font-bold text-indigo-300">
              {loading && !summary ? "…" : summary?.active ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">In progress</div>
            <div className="text-2xl font-bold text-blue-300">
              {loading && !summary ? "…" : summary?.in_progress ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Completed</div>
            <div className="text-2xl font-bold text-green-400">
              {loading && !summary ? "…" : summary?.completed ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Total</div>
            <div className="text-2xl font-bold">
              {loading && !summary ? "…" : summary?.total ?? 0}
            </div>
          </div>
        </div>

        {showForm && (
          <form
            onSubmit={handleSubmit}
            className="border-t border-zinc-800 pt-5"
          >
            <div className="mb-3 text-sm text-zinc-400">
              {draft.id ? (
                <>
                  Editace cíle <strong className="text-zinc-200">#{draft.id}</strong>
                </>
              ) : (
                "Nový cíl"
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Title *
                </label>
                <input
                  type="text"
                  placeholder="např. Našetřit 150 000 Kč"
                  value={draft.title}
                  onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Area *
                </label>
                <select
                  value={draft.area}
                  onChange={(e) => setDraft({ ...draft, area: e.target.value })}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  {AREA_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt.charAt(0).toUpperCase() + opt.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Status
                </label>
                <select
                  value={draft.status}
                  onChange={(e) =>
                    setDraft({ ...draft, status: e.target.value })
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt.charAt(0).toUpperCase() + opt.slice(1).replace("_", " ")}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Priority
                </label>
                <select
                  value={draft.priority}
                  onChange={(e) =>
                    setDraft({ ...draft, priority: e.target.value })
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Tracking type
                </label>
                <select
                  value={draft.tracking_type}
                  onChange={(e) =>
                    setDraft({ ...draft, tracking_type: e.target.value })
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  {TRACKING_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Target date
                </label>
                <input
                  type="date"
                  value={draft.target_date}
                  min={todayIso()}
                  onChange={(e) =>
                    setDraft({ ...draft, target_date: e.target.value })
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              {draft.tracking_type === "automatic" ? (
                <>
                  <div>
                    <label className="block text-sm text-zinc-400 mb-1.5">
                      Zdroj dat
                    </label>
                    <select
                      value={draft.source}
                      onChange={(e) =>
                        setDraft({ ...draft, source: e.target.value })
                      }
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                    >
                      {SOURCE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm text-zinc-400 mb-1.5">
                      Cílová hodnota ({sourceUnit(draft.source)})
                    </label>
                    <input
                      type="number"
                      min={0}
                      step={
                        draft.source === "finance_balance" ? 1 : 0.25
                      }
                      placeholder={
                        SOURCE_OPTIONS.find((o) => o.value === draft.source)
                          ?.placeholder ?? ""
                      }
                      value={draft.target_value}
                      onChange={(e) =>
                        setDraft({ ...draft, target_value: e.target.value })
                      }
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                    />
                  </div>
                </>
              ) : (
                <div>
                  <label className="block text-sm text-zinc-400 mb-1.5">
                    Progress (%)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={draft.progress}
                    onChange={(e) =>
                      setDraft({ ...draft, progress: e.target.value })
                    }
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                  />
                </div>
              )}
              <div className="md:col-span-2">
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Description
                </label>
                <textarea
                  rows={2}
                  placeholder="Popis cíle, jak dosáhnout…"
                  value={draft.description}
                  onChange={(e) =>
                    setDraft({ ...draft, description: e.target.value })
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none resize-none focus:border-zinc-500"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={resetForm}
                className="px-4 py-2.5 rounded-xl border border-zinc-800 text-zinc-300 hover:bg-zinc-800 transition-colors"
              >
                Storno
              </button>
              <button
                type="submit"
                disabled={submitting || loading}
                className="bg-white text-black font-medium px-5 py-2.5 rounded-xl disabled:opacity-50 hover:bg-zinc-200 transition-colors"
              >
                {submitting
                  ? "Ukládám…"
                  : draft.id
                    ? "Uložit změny"
                    : "Vytvořit cíl"}
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-semibold mb-4">Active goals</h2>

        {loading && goals.length === 0 ? (
          <div className="text-zinc-500 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            Načítám…
          </div>
        ) : activeGoals.length === 0 ? (
          <div className="text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            Zatím žádné aktivní cíle. Přidej první!
          </div>
        ) : (
          <div className="space-y-4">
            {activeGoals.map((g) => {
              const pct = clamp(g.progress ?? 0);
              return (
                <article
                  key={g.id}
                  className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <span className={areaBadge(g.area)}>{g.area}</span>
                    <span className={statusClass(g.status)}>{g.status.replace("_", " ")}</span>
                    <span className={priorityClass(g.priority)}>
                      Priority: {g.priority}
                    </span>
                    {g.target_date && (
                      <span className="text-xs text-zinc-400 ml-auto">
                        Target:{" "}
                        {dateFormatter.format(
                          new Date(`${g.target_date}T00:00:00`),
                        )}
                      </span>
                    )}
                  </div>
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div className="min-w-0 flex-1">
                      <h3 className="text-lg font-semibold break-words">
                        {g.title}
                      </h3>
                      {g.description && (
                        <p className="text-sm text-zinc-400 mt-1 leading-relaxed whitespace-pre-wrap">
                          {g.description}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => startEdit(g)}
                        className="text-xs px-3 py-1.5 rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors"
                      >
                        Editovat
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeletingGoal(g)}
                        className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-3 py-1.5 rounded-lg transition-colors"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                  {g.tracking_type === "automatic" ? (
                    <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
                      <div className="text-xs flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 font-medium">
                          Automatic: {g.source}
                        </span>
                      </div>
                      <div className="text-sm font-semibold tabular-nums text-zinc-200">
                        <span
                          className={
                            g.current_value != null ? "text-zinc-100" : "text-zinc-500"
                          }
                        >
                          {g.current_value != null
                            ? formatNumber(g.current_value)
                            : "—"}
                        </span>
                        <span className="text-zinc-500 mx-1">/</span>
                        <span className="text-zinc-100">
                          {g.target_value != null
                            ? formatNumber(g.target_value)
                            : "—"}
                        </span>
                        <span className="ml-1 text-zinc-400">
                          {sourceUnit(g.source)}
                        </span>
                      </div>
                    </div>
                  ) : null}
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-3 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${progressColor(
                          pct,
                          g.status,
                        )} transition-[width] duration-500 ease-out`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="text-sm font-semibold tabular-nums shrink-0 w-12 text-right">
                      {pct} %
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {completedGoals.length > 0 && (
        <section className="mb-10">
          <h2 className="text-xl font-semibold mb-4 text-green-400">
            Completed
          </h2>
          <div className="space-y-3">
            {completedGoals.map((g) => {
              const pct = clamp(g.progress ?? 0);
              return (
                <article
                  key={g.id}
                  className="bg-zinc-900/60 border border-zinc-800 rounded-2xl p-4 opacity-90"
                >
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span className={areaBadge(g.area)}>{g.area}</span>
                    <span className={statusClass(g.status)}>completed</span>
                    <div className="ml-auto flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => startEdit(g)}
                        className="text-xs px-2.5 py-1 rounded-lg border border-zinc-700 text-zinc-400 hover:text-white"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeletingGoal(g)}
                        className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2.5 py-1 rounded-lg transition-colors"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <h3 className="font-medium line-through text-zinc-400 flex-1">
                      {g.title}
                    </h3>
                    <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden max-w-sm">
                      <div className="h-full bg-green-500 w-full" />
                    </div>
                    <span className="text-sm tabular-nums text-green-400">
                      {pct} %
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {otherGoals.length > 0 && (
        <section>
          <h2 className="text-xl font-semibold mb-4 text-zinc-400">
            Paused / Cancelled
          </h2>
          <div className="space-y-3">
            {otherGoals.map((g) => {
              const pct = clamp(g.progress ?? 0);
              return (
                <article
                  key={g.id}
                  className="bg-zinc-900/40 border border-zinc-800 rounded-2xl p-4 opacity-75"
                >
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span className={areaBadge(g.area)}>{g.area}</span>
                    <span className={statusClass(g.status)}>
                      {g.status.replace("_", " ")}
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => startEdit(g)}
                        className="text-xs px-2.5 py-1 rounded-lg border border-zinc-700 text-zinc-400 hover:text-white"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeletingGoal(g)}
                        className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2.5 py-1 rounded-lg transition-colors"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <h3 className="font-medium text-zinc-300 flex-1">
                      {g.title}
                    </h3>
                    <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden max-w-sm">
                      <div
                        className={`h-full ${progressColor(pct, g.status)}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-sm tabular-nums text-zinc-400">
                      {pct} %
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      <ConfirmDialog
        open={deletingGoal != null}
        title={`Smazat cíl ${deletingGoal?.title ?? ""}?`}
        message="Tato akce je nevratná. Cíl bude odstraněn ze Standa Hubu."
        onConfirm={confirmDeleteGoal}
        onCancel={() => setDeletingGoal(null)}
      />
    </main>
  );
}
