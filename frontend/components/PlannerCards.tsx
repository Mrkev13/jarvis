import React from "react";

export type PlannerAction = {
  priority: number;
  area: string;
  title: string;
  reason: string;
};

export type PlannerPlan = {
  mode: "daily" | "weekly";
  summary: string;
  actions: PlannerAction[];
  meta?: {
    memories?: Array<{
      id: number;
      area: string;
      category: string;
      content: string;
      importance: number;
    }>;
  };
};

export type GoalReviewItem = {
  id: number;
  area: string;
  title: string;
  status: string;
  priority: string;
  tracking_type: string;
  progress: number;
  current_value: number | null;
  target_value: number | null;
  source: string | null;
  target_date: string | null;
  days_since_last_positive: number | null;
  stagnating: boolean;
  on_track: string;
  trend: string;
};

export type GoalReview = {
  mode: "goal_review";
  summary: string;
  goals: GoalReviewItem[];
};

export type PlannerCard =
  | { card_type: "daily" | "weekly"; payload: PlannerPlan }
  | { card_type: "goal_review"; payload: GoalReview };

const AREA_STYLES: Record<string, { bg: string; border: string; text: string; label: string }> = {
  school:   { bg: "bg-indigo-500/10",    border: "border-indigo-400/30",    text: "text-indigo-200",    label: "Škola" },
  work:     { bg: "bg-emerald-500/10",  border: "border-emerald-400/30",  text: "text-emerald-200",  label: "Práce" },
  finance:  { bg: "bg-amber-500/10",    border: "border-amber-400/30",    text: "text-amber-200",    label: "Finance" },
  wot:      { bg: "bg-orange-500/10",   border: "border-orange-400/30",   text: "text-orange-200",   label: "World of Tanks" },
  mff:      { bg: "bg-purple-500/10",   border: "border-purple-400/30",   text: "text-purple-200",   label: "Marvel FF" },
  personal: { bg: "bg-pink-500/10",     border: "border-pink-400/30",     text: "text-pink-200",     label: "Osobní" },
  fitness:  { bg: "bg-green-500/10",    border: "border-green-400/30",    text: "text-green-200",    label: "Fitness" },
  hobby:    { bg: "bg-rose-500/10",     border: "border-rose-400/30",     text: "text-rose-200",     label: "Hobby" },
  travel:   { bg: "bg-teal-500/10",     border: "border-teal-400/30",     text: "text-teal-200",     label: "Cestování" },
  general:  { bg: "bg-zinc-500/10",     border: "border-zinc-400/30",     text: "text-zinc-200",     label: "Obecné" },
  reminders: { bg: "bg-sky-500/10",     border: "border-sky-400/30",      text: "text-sky-200",      label: "Připomínky" },
  briefing: { bg: "bg-cyan-500/10",     border: "border-cyan-400/30",     text: "text-cyan-200",     label: "Přehled" },
  review:   { bg: "bg-violet-500/10",   border: "border-violet-400/30",   text: "text-violet-200",   label: "Týdenní přehled" },
};

export function areaMeta(area: string | undefined | null) {
  return (
    AREA_STYLES[String(area ?? "").toLowerCase()] ?? {
      bg: "bg-zinc-500/10",
      border: "border-zinc-400/30",
      text: "text-zinc-200",
      label: String(area ?? "Obecné"),
    }
  );
}

function progressBarColor(progress: number, stagnating: boolean, on_track: string) {
  if (stagnating) return "from-rose-500/40 to-red-500/30";
  if (on_track === "behind") return "from-amber-500/40 to-orange-500/30";
  if (progress >= 80) return "from-emerald-500/40 to-green-500/30";
  if (progress >= 50) return "from-lime-500/40 to-emerald-500/30";
  if (progress >= 20) return "from-yellow-500/40 to-amber-500/30";
  return "from-zinc-500/40 to-zinc-400/30";
}

function PlanCardShell(props: {
  icon: string;
  modeLabel: string;
  accent: string;
  summary: string;
  children: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div className="my-3 rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 overflow-hidden shadow">
      <div className={`px-4 md:px-5 py-3 md:py-4 bg-gradient-to-r ${props.accent} border-b border-zinc-800`}>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-white/10 grid place-items-center text-lg shrink-0">
            {props.icon}
          </div>
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.18em] text-white/70 font-semibold">
              {props.modeLabel}
            </div>
            <div className="mt-0.5 text-zinc-100 font-semibold leading-snug break-words">
              {props.summary}
            </div>
          </div>
        </div>
      </div>
      <div className={`${props.compact ? "px-3 py-2.5 space-y-2" : "px-4 py-3 md:px-5 md:py-4 space-y-2.5 md:space-y-3"}`}>
        {props.children}
      </div>
    </div>
  );
}

function ActionItem(props: { action: PlannerAction; idx: number; compact?: boolean }) {
  const { action, idx, compact } = props;
  const meta = areaMeta(action.area);
  const priority = Number.isFinite(action.priority) ? action.priority : idx + 1;
  const isTop = priority === 1;
  return (
    <div
      className={
        "group rounded-xl border p-3 transition-all " +
        meta.border +
        " " +
        meta.bg +
        (isTop ? " ring-1 ring-amber-400/30" : "")
      }
    >
      <div className="flex items-start gap-3">
        <div
          className={
            "shrink-0 w-9 h-9 rounded-full grid place-items-center font-bold text-sm border " +
            (isTop
              ? "bg-amber-400/90 text-zinc-950 border-amber-300"
              : "bg-white/5 text-zinc-100 border-white/10")
          }
        >
          {priority}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <span
              className={
                "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] uppercase tracking-wider font-semibold border " +
                meta.bg +
                " " +
                meta.border +
                " " +
                meta.text
              }
            >
              {meta.label}
            </span>
            {isTop && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-400/10 text-amber-300 border border-amber-400/25">
                🔥 Nejvyšší priorita
              </span>
            )}
          </div>
          <div className="text-zinc-100 font-semibold leading-snug break-words">
            {action.title}
          </div>
          {action.reason && (
            <div className={`mt-1 ${compact ? "text-xs" : "text-sm"} text-zinc-400 leading-snug break-words`}>
              <span className="text-zinc-500 mr-1">Důvod:</span>
              {action.reason}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function DailyPlanCard({ plan, compact }: { plan: PlannerPlan; compact?: boolean }) {
  const sorted = [...(plan.actions || [])].sort((a, b) => a.priority - b.priority);
  return (
    <PlanCardShell
      icon="☀️"
      modeLabel="Daily plan"
      accent="from-sky-600/25 via-blue-600/20 to-indigo-600/20"
      summary={plan.summary}
      compact={compact}
    >
      {sorted.length === 0 && (
        <div className="text-sm text-zinc-500 italic">Žádné akce k doporučení pro dnes.</div>
      )}
      {sorted.map((a, i) => (
        <ActionItem key={`${a.priority}-${a.title}-${i}`} action={a} idx={i} compact={compact} />
      ))}
    </PlanCardShell>
  );
}

export function WeeklyPlanCard({ plan, compact }: { plan: PlannerPlan; compact?: boolean }) {
  const sorted = [...(plan.actions || [])].sort((a, b) => a.priority - b.priority);
  return (
    <PlanCardShell
      icon="📅"
      modeLabel="Weekly plan"
      accent="from-indigo-600/30 via-violet-600/20 to-fuchsia-600/20"
      summary={plan.summary}
      compact={compact}
    >
      {sorted.length === 0 && (
        <div className="text-sm text-zinc-500 italic">Žádné akce k doporučení pro tento týden.</div>
      )}
      {sorted.map((a, i) => (
        <ActionItem key={`${a.priority}-${a.title}-${i}`} action={a} idx={i} compact={compact} />
      ))}
    </PlanCardShell>
  );
}

export function GoalReviewCard({ plan, compact }: { plan: GoalReview; compact?: boolean }) {
  const goals = plan.goals || [];
  return (
    <div className="my-3 rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 overflow-hidden shadow">
      <div className="px-4 md:px-5 py-3 md:py-4 bg-gradient-to-r from-emerald-600/25 via-teal-600/20 to-cyan-600/20 border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-white/10 grid place-items-center text-lg shrink-0">🎯</div>
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.18em] text-white/70 font-semibold">
              Goal review
            </div>
            <div className="mt-0.5 text-zinc-100 font-semibold leading-snug break-words">
              {plan.summary}
            </div>
          </div>
        </div>
      </div>
      <div className={`overflow-x-auto ${compact ? "px-2 py-2" : "px-4 py-4"}`}>
        {goals.length === 0 ? (
          <div className="text-sm text-zinc-500 italic px-2 py-4">Žádné relevantní cíle.</div>
        ) : (
          <div className="space-y-3">
            {goals.map((g) => {
              const meta = areaMeta(g.area);
              const pct = Math.max(0, Math.min(100, Number(g.progress) || 0));
              return (
                <div
                  key={g.id}
                  className={`rounded-xl border ${meta.border} ${meta.bg} p-3 md:p-4`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <span className={`px-2 py-0.5 rounded-md border text-[11px] font-semibold uppercase tracking-wider ${meta.bg} ${meta.border} ${meta.text}`}>
                          {meta.label}
                        </span>
                        <span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${
                          (g.priority || "").toLowerCase() === "high"
                            ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                            : (g.priority || "").toLowerCase() === "medium"
                              ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                              : "bg-zinc-500/15 text-zinc-300 border border-zinc-500/30"
                        } border`}>
                          {(g.priority || "medium").toUpperCase()}
                        </span>
                        {g.stagnating && (
                          <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-red-500/15 text-red-300 border border-red-500/30">
                            ⚠️ Stagnuje
                          </span>
                        )}
                        {g.on_track === "behind" && !g.stagnating && (
                          <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-orange-500/15 text-orange-300 border border-orange-500/30">
                            ⏳ Zaostává
                          </span>
                        )}
                        {g.on_track === "on_track" && (
                          <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                            ✓ Na cestě
                          </span>
                        )}
                      </div>
                      <div className="font-semibold text-zinc-100 break-words">
                        {g.title}
                      </div>
                    </div>
                    <div className="text-right shrink-0 min-w-[96px]">
                      <div className="text-xs text-zinc-500">Progress</div>
                      <div className="text-2xl font-bold text-white tabular-nums">{pct} %</div>
                      {(g.current_value != null || g.target_value != null) && (
                        <div className="text-xs text-zinc-400 tabular-nums mt-0.5">
                          {g.current_value ?? "–"} / {g.target_value ?? "–"}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="mt-3">
                    <div className="h-2 w-full rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        className={`h-full bg-gradient-to-r ${progressBarColor(pct, g.stagnating, g.on_track)} transition-[width] duration-500 rounded-full`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-zinc-400">
                    {g.target_date && (
                      <div>
                        <span className="text-zinc-500 mr-1.5">Cíl do:</span>
                        <span className="text-zinc-300 font-medium">{g.target_date}</span>
                      </div>
                    )}
                    {g.days_since_last_positive != null && (
                      <div>
                        <span className="text-zinc-500 mr-1.5">Poslední pokrok:</span>
                        <span className={g.stagnating ? "text-red-300 font-medium" : "text-zinc-300 font-medium"}>
                          {g.days_since_last_positive} dní zpět
                        </span>
                      </div>
                    )}
                    <div>
                      <span className="text-zinc-500 mr-1.5">Tracking:</span>
                      <span className="text-zinc-300 font-medium">
                        {(g.tracking_type || "manual").toLowerCase()}
                        {g.source ? ` · ${g.source}` : ""}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function PlannerCardRenderer(props: { card: PlannerCard; compact?: boolean }) {
  const { card, compact } = props;
  if (card.card_type === "daily") {
    return <DailyPlanCard plan={card.payload as PlannerPlan} compact={compact} />;
  }
  if (card.card_type === "weekly") {
    return <WeeklyPlanCard plan={card.payload as PlannerPlan} compact={compact} />;
  }
  if (card.card_type === "goal_review") {
    return <GoalReviewCard plan={card.payload as GoalReview} compact={compact} />;
  }
  return null;
}

export default PlannerCardRenderer;
