"use client";

import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "@/lib/api";
import {
  DailyPlanCard,
  WeeklyPlanCard,
  GoalReviewCard,
  type PlannerPlan,
  type GoalReview,
} from "@/components/PlannerCards";

export default function PlannerPage() {
  const [mode, setMode] = useState<"daily" | "weekly" | "goal_review">("daily");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlannerPlan | GoalReview | null>(null);

  async function load(nextMode: "daily" | "weekly" | "goal_review") {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(apiUrl(`/planner?mode=${encodeURIComponent(nextMode)}`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as PlannerPlan | GoalReview;
      setPlan(data);
    } catch {
      setError("Nepodařilo se načíst Planner z backendu.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    queueMicrotask(() => {
      void load(mode).catch(() => {});
    });
  }, [mode]);

  const isGoalReview = useMemo(
    () => Boolean(plan && (plan as GoalReview).mode === "goal_review"),
    [plan],
  );

  const dailyPlan = plan && !isGoalReview && (plan as PlannerPlan).mode === "daily"
    ? (plan as PlannerPlan)
    : null;
  const weeklyPlan = plan && !isGoalReview && (plan as PlannerPlan).mode === "weekly"
    ? (plan as PlannerPlan)
    : null;
  const goalReview = plan && isGoalReview ? (plan as GoalReview) : null;

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto space-y-6 md:space-y-8">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-4xl font-bold">Planner 2.0</h1>
          <p className="text-zinc-400 mt-2">
            Doporučení vychází pouze z uložených dat (deadliny, goals, work/finance).
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {([
            ["daily", "Daily"],
            ["weekly", "Weekly"],
            ["goal_review", "Goal review"],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setMode(k)}
              className={`px-4 py-2.5 rounded-xl border transition-colors text-sm ${
                mode === k
                  ? "bg-white text-black border-white"
                  : "border-zinc-800 text-zinc-300 hover:bg-zinc-800 hover:border-zinc-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <section className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-zinc-400">Summary</div>
          <button
            type="button"
            onClick={() => void load(mode)}
            disabled={loading}
            className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors disabled:opacity-50"
          >
            Obnovit
          </button>
        </div>
        <div className="text-lg font-semibold mt-2">
          {loading ? "Načítám…" : plan ? plan.summary : "—"}
        </div>
      </section>

      {loading && !plan && (
        <div className="text-sm text-zinc-500 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
          Načítám plán…
        </div>
      )}

      {dailyPlan && !loading && <DailyPlanCard plan={dailyPlan} />}
      {weeklyPlan && !loading && <WeeklyPlanCard plan={weeklyPlan} />}
      {goalReview && !loading && <GoalReviewCard plan={goalReview} />}
    </main>
  );
}
