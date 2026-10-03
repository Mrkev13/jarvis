"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { MAX_STAGGER, staggerStyle, useNewIds } from "@/lib/motion";

type WorkSummary = {
  total_hours: number;
  total_earnings: number;
  this_month_hours: number;
  this_month_earnings: number;
};

type WorkSessionItem = {
  id: number;
  date: string;
  hours: number;
  project: string;
  description: string;
  hourly_rate: number;
  earnings: number;
  finance_transaction_id?: number | null;
  sync_to_finance?: boolean | null;
};

const dateFormatter = new Intl.DateTimeFormat("cs-CZ", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

function formatNumber(value: number) {
  return new Intl.NumberFormat("cs-CZ", {
    maximumFractionDigits: 2,
  }).format(value);
}

function formatHours(value: number) {
  const fixed = value % 1 === 0 ? value.toFixed(0) : value.toFixed(1);
  return `${fixed} h`;
}

function todayIso() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function WorkPage() {
  const [summary, setSummary] = useState<WorkSummary | null>(null);
  const [sessions, setSessions] = useState<WorkSessionItem[]>([]);
  const [loading, setLoading] = useState(false);
  // Nově přidané session krátce zvýraznit (ne při prvním načtení).
  const newSessionIds = useNewIds(
    sessions.map((s) => s.id),
    summary !== null && !loading,
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingSession, setDeletingSession] = useState<WorkSessionItem | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [date, setDate] = useState(todayIso());
  const [hours, setHours] = useState("");
  const [project, setProject] = useState("");
  const [description, setDescription] = useState("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [syncToFinance, setSyncToFinance] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sRes, sumRes] = await Promise.all([
        apiFetch("/work/sessions"),
        apiFetch("/work/summary"),
      ]);
      if (!sRes.ok || !sumRes.ok) throw new Error();
      const s = (await sRes.json()) as WorkSessionItem[];
      const sum = (await sumRes.json()) as WorkSummary;
      setSessions(s);
      setSummary(sum);
    } catch {
      setError("Nepodařilo se načíst pracovní data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const hoursNum = parseFloat(hours);
    if (!date || !isFinite(hoursNum) || hoursNum <= 0) {
      setError("Vyplň platné datum a kladný počet hodin.");
      return;
    }
    const rate = hourlyRate ? parseFloat(hourlyRate) : 0;

    setSubmitting(true);
    setError(null);
    try {
      const res = await apiFetch("/work/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date,
          hours: hoursNum,
          project: project.trim(),
          description: description.trim(),
          hourly_rate: isFinite(rate) ? rate : 0,
          sync_to_finance: syncToFinance,
        }),
      });
      if (!res.ok) throw new Error();
      setHours("");
      setProject("");
      setDescription("");
      setHourlyRate("");
      setSyncToFinance(true);
      setShowForm(false);
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit session.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteSession() {
    if (!deletingSession) return;
    try {
      const res = await apiFetch(`/work/session/${deletingSession.id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete session");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat pracovní session.");
    } finally {
      setDeletingSession(null);
    }
  }

  return (
    <main className="p-4 md:p-8 max-w-5xl mx-auto">
      <header className="mb-6 md:mb-8">
        <h1 className="text-2xl md:text-4xl font-bold">Work</h1>
        <p className="text-zinc-400 mt-2">
          Sledování odpracovaných hodin, projektů a výdělku.
        </p>
      </header>

      {error && (
        <div className="mb-6 bg-red-950/50 border border-red-900 text-red-200 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <section className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-8">
        <div className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
          <div className="text-sm text-zinc-400 mb-4">This month</div>
          <div className="space-y-3">
            <div className="flex justify-between items-baseline gap-4">
              <span className="text-zinc-400">Hodiny</span>
              <span className="text-3xl font-bold">
                {loading && !summary
                  ? "…"
                  : <AnimatedNumber value={summary?.this_month_hours ?? 0} format={formatHours} />}
              </span>
            </div>
            <div className="flex justify-between items-baseline gap-4">
              <span className="text-zinc-400">Výdělek</span>
              <span className="text-2xl font-semibold text-green-400">
                {loading && !summary
                  ? "…"
                  : <><AnimatedNumber value={summary?.this_month_earnings ?? 0} format={formatNumber} /> Kč</>}
              </span>
            </div>
          </div>
        </div>

        <div className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-6" style={staggerStyle(1)}>
          <div className="text-sm text-zinc-400 mb-4">Total</div>
          <div className="space-y-3">
            <div className="flex justify-between items-baseline gap-4">
              <span className="text-zinc-400">Hodiny</span>
              <span className="text-3xl font-bold">
                {loading && !summary
                  ? "…"
                  : <AnimatedNumber value={summary?.total_hours ?? 0} format={formatHours} />}
              </span>
            </div>
            <div className="flex justify-between items-baseline gap-4">
              <span className="text-zinc-400">Výdělek</span>
              <span className="text-2xl font-semibold text-green-400">
                {loading && !summary
                  ? "…"
                  : <><AnimatedNumber value={summary?.total_earnings ?? 0} format={formatNumber} /> Kč</>}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">Add work session</h2>
          {!showForm ? (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="bg-white text-black font-medium px-5 py-2.5 rounded-xl hover:bg-zinc-200 transition-colors"
            >
              + Add work session
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="text-sm text-zinc-400 hover:text-zinc-200"
            >
              Zavřít
            </button>
          )}
        </div>

        {showForm && (
          <form
            onSubmit={handleSubmit}
            className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 md:p-6"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Date
                </label>
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Hours
                </label>
                <input
                  type="number"
                  min="0.25"
                  step="0.25"
                  placeholder="např. 7.5"
                  value={hours}
                  onChange={(e) => setHours(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Project
                </label>
                <input
                  type="text"
                  placeholder="např. Servind"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Hourly rate (Kč)
                </label>
                <input
                  type="number"
                  min="0"
                  placeholder="např. 325"
                  value={hourlyRate}
                  onChange={(e) => setHourlyRate(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Description
                </label>
                <textarea
                  rows={2}
                  placeholder="Popis práce…"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none resize-none focus:border-zinc-500"
                />
              </div>
              <div className="md:col-span-2 flex items-start gap-2">
                <input
                  id="sync-finance"
                  type="checkbox"
                  checked={syncToFinance}
                  onChange={(e) => setSyncToFinance(e.target.checked)}
                  className="mt-1 w-4 h-4 rounded bg-zinc-800 border-zinc-700"
                />
                <label htmlFor="sync-finance" className="text-sm text-zinc-300 select-none">
                  ☑ Zapsat výdělek také do Finance (vytvoří záznam <code className="text-green-400">income / work</code>)
                </label>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3">
              <div className="text-sm text-zinc-400">
                {hours && hourlyRate && !isNaN(parseFloat(hours)) && !isNaN(parseFloat(hourlyRate)) && (
                  <>
                    Odhad výdělku:{" "}
                    <span className="text-green-400 font-medium">
                      {formatNumber(parseFloat(hours) * parseFloat(hourlyRate))} Kč
                    </span>
                  </>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2.5 rounded-xl border border-zinc-800 text-zinc-300 hover:bg-zinc-800 transition-colors"
                >
                  Storno
                </button>
                <button
                  type="submit"
                  disabled={submitting || loading}
                  className="bg-white text-black font-medium px-5 py-2.5 rounded-xl disabled:opacity-50 hover:bg-zinc-200 transition-colors"
                >
                  {submitting ? "Ukládám…" : "Uložit"}
                </button>
              </div>
            </div>
          </form>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold mb-4">Recent sessions</h2>

        {loading && sessions.length === 0 ? (
          <div className="text-zinc-500 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            Načítám…
          </div>
        ) : sessions.length === 0 ? (
          <div className="text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            Zatím žádné pracovní session. Přidej první!
          </div>
        ) : (
          <div className="space-y-3">
            {sessions.map((s, si) => (
              <div
                key={s.id}
                className={`motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex flex-col md:flex-row md:items-center gap-4 md:justify-between ${
                  newSessionIds.has(String(s.id)) ? "motion-highlight" : ""
                }`}
                style={staggerStyle(Math.min(si + 2, MAX_STAGGER))}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span className="text-sm text-zinc-400">
                      {dateFormatter.format(new Date(`${s.date}T00:00:00`))}
                    </span>
                    {s.project && (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-200">
                        {s.project}
                      </span>
                    )}
                    {s.finance_transaction_id ? (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-green-500/10 border border-green-500/30 text-green-400">
                        💰 Finance
                      </span>
                    ) : s.sync_to_finance && s.earnings > 0 ? (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400">
                        Finance: nevyužito
                      </span>
                    ) : null}
                  </div>
                  {s.description && (
                    <p className="text-zinc-300 leading-relaxed break-words">
                      {s.description}
                    </p>
                  )}
                </div>
                <div className="flex flex-col items-end gap-3 shrink-0">
                  <button
                    type="button"
                    onClick={() => setDeletingSession(s)}
                    className="self-end text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2.5 py-1 rounded transition-colors"
                  >
                    🗑️
                  </button>
                  <div className="flex md:flex-col items-end gap-4">
                    <div className="text-right">
                      <div className="text-sm text-zinc-500">Hodiny</div>
                      <div className="text-xl font-semibold">
                        {formatHours(s.hours)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm text-zinc-500">Výdělek</div>
                      <div className="text-xl font-semibold text-green-400">
                        {formatNumber(s.earnings)} Kč
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <ConfirmDialog
        open={deletingSession != null}
        title={`Smazat session ${deletingSession?.project || deletingSession?.date || ""}?`}
        message="Tato akce je nevratná. Změny se projeví v Work statistikách."
        onConfirm={confirmDeleteSession}
        onCancel={() => setDeletingSession(null)}
      />
    </main>
  );
}
