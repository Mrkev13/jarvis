"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { areaMeta } from "@/components/PlannerCards";

type NotificationPreview = {
  id: number;
  area: string;
  title: string;
  message: string;
  severity: string;
  action_url?: string | null;
};

type GoalQuick = {
  id: number;
  title: string;
  area: string;
  priority: string;
  progress: number;
  current_value: number | null;
  target_value: number | null;
  target_date: string | null;
  tracking_type: string;
};

type WorkQuick = {
  total_hours: number;
  total_earnings: number;
  this_month_hours: number;
  this_month_earnings: number;
  goal?: {
    title: string;
    current_value: number | null;
    target_value: number | null;
    progress: number;
    target_date: string | null;
  } | null;
};

type FinanceQuick = {
  balance: number;
  income: number;
  expenses: number;
  this_month_income: number;
  this_month_expenses: number;
  transactions_count: number;
  goal?: {
    title: string;
    current_value: number | null;
    target_value: number | null;
    progress: number;
    target_date: string | null;
  } | null;
};

type UpcomingItem = {
  type: "assignment" | "exam" | "goal_target";
  id: number;
  title: string;
  area: string;
  date: string;
  days_left: number;
  overdue: boolean;
};

type TodayAction = {
  priority: number;
  area: string;
  title: string;
  reason: string;
};

type DashboardPayload = {
  today: {
    summary: string;
    actions: TodayAction[];
    today_deadline?: TodayAction | null;
  };
  notifications: {
    unread: number;
    important: number;
    warning: number;
    info: number;
    preview: NotificationPreview[];
  };
  goals: { top: GoalQuick[]; count: number };
  work: WorkQuick;
  finance: FinanceQuick;
  upcoming: UpcomingItem[];
  wot: {
    top_grinds: Array<{
      id: number;
      tank: string;
      xp_remaining: number;
      priority: string;
      status: string;
    }>;
    credits?: number | null;
    free_xp?: number | null;
    bonds?: number | null;
  };
  mff: {
    tracked_characters: number;
    t4_count: number;
    priority_count: number;
    average_build_completeness: number;
  };
};

function formatNumber(value?: number | null) {
  if (value === undefined || value === null) return "-";
  return new Intl.NumberFormat("cs-CZ").format(value);
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()}. ${d.getMonth() + 1}. ${d.getFullYear()}`;
}

function progressGradient(pct: number) {
  if (pct >= 80) return "from-emerald-500/80 to-green-500/50";
  if (pct >= 45) return "from-amber-400/80 to-yellow-500/50";
  if (pct >= 15) return "from-orange-500/80 to-amber-500/40";
  return "from-rose-500/80 to-red-500/50";
}

function AreaBadge({ area }: { area: string }) {
  const meta = areaMeta(area);
  return (
    <span className={`text-[11px] uppercase tracking-wider px-2 py-0.5 rounded-full border ${meta.bg} ${meta.border} ${meta.text}`}>
      {meta.label}
    </span>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const s = String(severity || "info").toLowerCase();
  if (s === "important") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider px-2 py-0.5 rounded-full border bg-red-500/15 border-red-400/30 text-red-200">
        ● Important
      </span>
    );
  }
  if (s === "warning") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider px-2 py-0.5 rounded-full border bg-amber-500/15 border-amber-400/30 text-amber-200">
        ● Warning
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider px-2 py-0.5 rounded-full border bg-zinc-500/10 border-zinc-400/30 text-zinc-200">
      ● Info
    </span>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const p = String(priority || "medium").toLowerCase();
  if (p === "high") {
    return <span className="text-[11px] px-2 py-0.5 rounded-full border bg-amber-500/15 border-amber-400/30 text-amber-200">High</span>;
  }
  if (p === "low") {
    return <span className="text-[11px] px-2 py-0.5 rounded-full border bg-zinc-500/10 border-zinc-400/30 text-zinc-300">Low</span>;
  }
  return <span className="text-[11px] px-2 py-0.5 rounded-full border bg-indigo-500/10 border-indigo-400/30 text-indigo-200">Medium</span>;
}

function ProgressBar({ value, height = "h-2" }: { value: number; height?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  return (
    <div className={`w-full ${height} rounded-full bg-zinc-800 overflow-hidden`}>
      <div
        className={`${height} rounded-full bg-gradient-to-r ${progressGradient(pct)}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function Card({ title, children, actions, className = "" }: { title: React.ReactNode; children: React.ReactNode; actions?: React.ReactNode; className?: string }) {
  return (
    <section className={`bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-5 ${className}`}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <h2 className="text-lg md:text-xl font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

function ActionRow({ a }: { a: TodayAction }) {
  const meta = areaMeta(a.area);
  const isTop = Number(a.priority) === 1;
  return (
    <div className={`rounded-xl border ${meta.border} ${meta.bg} p-3 flex items-start gap-3`}>
      <div className={`shrink-0 w-9 h-9 rounded-full grid place-items-center font-bold text-sm border ${isTop ? "bg-amber-400/90 text-zinc-950 border-amber-300" : "bg-white/5 text-zinc-100 border-white/10"}`}>
        {a.priority}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <AreaBadge area={a.area} />
        </div>
        <div className="font-semibold text-[15px] leading-snug break-words">{a.title}</div>
        <div className="text-zinc-400 text-sm mt-1 break-words">{a.reason}</div>
      </div>
    </div>
  );
}

function GoalRow({ g }: { g: GoalQuick }) {
  const pct = Math.max(0, Math.min(100, Math.round(Number(g.progress) || 0)));
  const hasValue = g.current_value !== null && g.current_value !== undefined && g.target_value;
  const trackingBadge = g.tracking_type === "automatic"
    ? <span className="text-[11px] px-2 py-0.5 rounded-full border bg-emerald-500/10 border-emerald-400/30 text-emerald-200">Automatic</span>
    : <span className="text-[11px] px-2 py-0.5 rounded-full border bg-zinc-500/10 border-zinc-400/30 text-zinc-300">Manual</span>;
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-3 md:p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
        <div className="font-semibold break-words">{g.title}</div>
        <div className="flex items-center gap-1.5">
          <AreaBadge area={g.area} />
          <PriorityBadge priority={g.priority} />
          {trackingBadge}
        </div>
      </div>
      {hasValue ? (
        <div className="text-zinc-300 text-sm mb-2">
          {formatNumber(Number(g.current_value))} / {formatNumber(Number(g.target_value))}
          {g.area === "finance" ? " Kč" : g.area === "work" ? " h" : ""}
        </div>
      ) : null}
      <div className="flex items-center gap-3">
        <div className="flex-1"><ProgressBar value={pct} /></div>
        <div className="text-sm font-semibold text-zinc-100 w-12 text-right">{pct} %</div>
      </div>
      {g.target_date ? (
        <div className="text-xs text-zinc-500 mt-2">Target: {formatDate(g.target_date)}</div>
      ) : null}
    </div>
  );
}

export default function Home() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    void Promise.resolve()
      .then(() => apiFetch("/dashboard"))
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const payload = (await r.json()) as DashboardPayload;
        setData(payload);
      })
      .catch(() => {
        setError("Nepodařilo se načíst Dashboard data.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void Promise.resolve(load()).catch(() => {});
    });
  }, [load]);

  const today = data?.today;
  const notifications = data?.notifications;
  const goals = data?.goals;
  const work = data?.work;
  const finance = data?.finance;
  const upcoming = data?.upcoming ?? [];
  const wot = data?.wot;
  const mff = data?.mff;

  const showSkeleton = loading && !data;

  const workGoalProgress = useMemo(() => {
    const g = work?.goal;
    if (!g?.target_value || Number(g.target_value) <= 0) return null;
    return {
      title: g.title || "Měsíční hodinový cíl",
      current: g.current_value ?? work?.this_month_hours ?? 0,
      target: Number(g.target_value),
      progress: Math.max(0, Math.min(100, Math.round(Number(g.progress) || 0))),
      target_date: g.target_date,
    };
  }, [work]);

  const financeGoalProgress = useMemo(() => {
    const g = finance?.goal;
    if (!g?.target_value || Number(g.target_value) <= 0) return null;
    return {
      title: g.title || "Cíl bilance",
      current: g.current_value ?? finance?.balance ?? 0,
      target: Number(g.target_value),
      progress: Math.max(0, Math.min(100, Math.round(Number(g.progress) || 0))),
      target_date: g.target_date,
    };
  }, [finance]);

  return (
    <main className="p-4 md:p-8 max-w-7xl mx-auto space-y-4 md:space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-4xl font-bold">Command Center</h1>
          <p className="text-zinc-400 mt-2">Důležité věci dnes, cíle, finance, práce a co se blíží.</p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors disabled:opacity-50"
        >
          Obnovit
        </button>
      </header>

      {error ? (
        <div className="bg-red-500/10 border border-red-500/30 text-red-300 rounded-2xl p-4">
          {error}
        </div>
      ) : null}

      {/* TODAY */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-sky-500/15 border border-sky-400/30 text-sky-200">☀️</span>
            Dnes
          </div>
        }
        actions={<Link href="/planner" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Planner →</Link>}
        className="md:col-span-2 xl:col-span-3"
      >
        {showSkeleton ? (
          <div className="space-y-3">
            <div className="h-4 w-2/3 rounded bg-zinc-800 animate-pulse" />
            <div className="h-20 rounded-xl bg-zinc-800/60 animate-pulse" />
            <div className="h-20 rounded-xl bg-zinc-800/60 animate-pulse" />
          </div>
        ) : today ? (
          <>
            {today.summary ? <div className="text-zinc-300 mb-4">{today.summary}</div> : null}
            {today.actions && today.actions.length > 0 ? (
              <div className="space-y-2.5">
                {today.actions.slice(0, 3).map((a, i) => (
                  <ActionRow key={`${a.priority}-${i}-${a.title}`} a={a} />
                ))}
              </div>
            ) : (
              <div className="text-sm text-zinc-500 border border-dashed border-zinc-800 rounded-xl p-5 text-center">
                Dnes máš volno podle Planneru. Jdi na /goals a vytvoř si priority.
              </div>
            )}
            {notifications && notifications.unread > 0 ? (
              <div className="mt-4 flex items-center gap-2 text-sm text-zinc-300">
                <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-400/30 text-amber-200">
                  🔔 {notifications.unread} upozornění
                  {notifications.important > 0 ? ` · ${notifications.important} important` : null}
                  {notifications.warning > 0 ? ` · ${notifications.warning} warning` : null}
                </span>
              </div>
            ) : null}
          </>
        ) : null}
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 md:gap-6">
        {/* NOTIFICATIONS */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-amber-500/15 border border-amber-400/30 text-amber-200">🔔</span>
              Vyžaduje pozornost
            </div>
          }
          actions={<Link href="/planner" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Všechna upozornění →</Link>}
          className="md:col-span-1 xl:col-span-1 order-2 md:order-1"
        >
          {showSkeleton ? (
            <div className="space-y-3">
              <div className="h-16 rounded-xl bg-zinc-800/60 animate-pulse" />
              <div className="h-16 rounded-xl bg-zinc-800/60 animate-pulse" />
            </div>
          ) : notifications ? (
            <>
              {notifications.preview && notifications.preview.length > 0 ? (
                <ul className="space-y-3">
                  {notifications.preview.slice(0, 3).map((n) => {
                    const meta = areaMeta(n.area);
                    const maybeLink = n.action_url?.startsWith("/") || n.action_url?.startsWith("http");
                    const body = (
                      <div className={`rounded-xl border ${meta.border} ${meta.bg} p-3`}>
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <SeverityBadge severity={n.severity} />
                          <AreaBadge area={n.area} />
                        </div>
                        <div className="font-semibold text-[15px] break-words">{n.title}</div>
                        {n.message ? <div className="text-sm text-zinc-400 mt-1 break-words">{n.message}</div> : null}
                      </div>
                    );
                    return (
                      <li key={n.id}>
                        {maybeLink ? <Link href={String(n.action_url)}>{body}</Link> : body}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="text-sm text-zinc-500 border border-dashed border-zinc-800 rounded-xl p-5 text-center">
                  Žádná neřešená upozornění.
                </div>
              )}
            </>
          ) : null}
        </Card>

        {/* GOALS */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-emerald-500/15 border border-emerald-400/30 text-emerald-200">🎯</span>
              Cíle
            </div>
          }
          actions={<Link href="/goals" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Všechny cíle →</Link>}
          className="md:col-span-1 xl:col-span-1 order-3 md:order-2"
        >
          {showSkeleton ? (
            <div className="space-y-3">
              <div className="h-24 rounded-xl bg-zinc-800/60 animate-pulse" />
              <div className="h-24 rounded-xl bg-zinc-800/60 animate-pulse" />
            </div>
          ) : goals ? (
            <>
              {goals.top && goals.top.length > 0 ? (
                <div className="space-y-3">
                  {goals.top.map((g) => (
                    <GoalRow key={g.id} g={g} />
                  ))}
                </div>
              ) : (
                <div className="text-sm text-zinc-500 border border-dashed border-zinc-800 rounded-xl p-5 text-center">
                  Zatím nemáš žádný aktivní cíl.
                </div>
              )}
            </>
          ) : null}
        </Card>

        {/* UPCOMING */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-indigo-500/15 border border-indigo-400/30 text-indigo-200">📅</span>
              Nadcházející
            </div>
          }
          actions={
            <div className="flex items-center gap-3">
              <Link href="/school" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Škola →</Link>
            </div>
          }
          className="md:col-span-2 xl:col-span-1 order-4"
        >
          {showSkeleton ? (
            <div className="space-y-2">
              <div className="h-14 rounded-xl bg-zinc-800/60 animate-pulse" />
              <div className="h-14 rounded-xl bg-zinc-800/60 animate-pulse" />
              <div className="h-14 rounded-xl bg-zinc-800/60 animate-pulse" />
            </div>
          ) : upcoming.length > 0 ? (
            <ul className="space-y-2">
              {upcoming.map((u) => {
                const isOverdue = u.overdue;
                const days = Math.abs(Number(u.days_left) || 0);
                return (
                  <li
                    key={`${u.type}-${u.id}`}
                    className={`rounded-xl border p-3 ${isOverdue ? "bg-red-500/10 border-red-400/30" : "bg-zinc-950/40 border-zinc-800"}`}
                  >
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          {u.type === "assignment" ? <span className="text-[11px] uppercase tracking-wider px-2 py-0.5 rounded-full border bg-indigo-500/10 border-indigo-400/30 text-indigo-200">Assignment</span> : null}
                          {u.type === "exam" ? <span className="text-[11px] uppercase tracking-wider px-2 py-0.5 rounded-full border bg-rose-500/10 border-rose-400/30 text-rose-200">Zkouška</span> : null}
                          {u.type === "goal_target" ? <AreaBadge area={u.area} /> : null}
                        </div>
                        <div className="font-semibold mt-1 break-words">{u.title}</div>
                        <div className="text-xs text-zinc-400 mt-1">{formatDate(u.date)}</div>
                      </div>
                      <div className={`shrink-0 text-sm font-semibold ${isOverdue ? "text-red-300" : "text-zinc-200"}`}>
                        {isOverdue ? (
                          <>OVERDUE · {days} {days === 1 ? "den" : days < 5 ? "dny" : "dní"} po termínu</>
                        ) : days === 0 ? (
                          <>DNES</>
                        ) : days === 1 ? (
                          <>ZA 1 DEN</>
                        ) : (
                          <>ZA {days} DNY</>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="text-sm text-zinc-500 border border-dashed border-zinc-800 rounded-xl p-5 text-center">
              Žádné blížící se termíny.
            </div>
          )}
        </Card>

        {/* WORK */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-emerald-500/15 border border-emerald-400/30 text-emerald-200">💼</span>
              Práce
            </div>
          }
          actions={<Link href="/work" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Work →</Link>}
          className="order-5"
        >
          {showSkeleton ? (
            <div className="space-y-3">
              <div className="h-4 w-2/3 rounded bg-zinc-800 animate-pulse" />
              <div className="h-10 rounded bg-zinc-800 animate-pulse" />
            </div>
          ) : work ? (
            <>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="rounded-xl bg-zinc-950/60 border border-zinc-800 p-3">
                  <div className="text-xs uppercase tracking-wider text-zinc-500">Tento měsíc</div>
                  <div className="text-xl font-semibold mt-1">{formatNumber(work.this_month_hours)} h</div>
                </div>
                <div className="rounded-xl bg-zinc-950/60 border border-zinc-800 p-3">
                  <div className="text-xs uppercase tracking-wider text-zinc-500">Výdělek</div>
                  <div className="text-xl font-semibold text-emerald-300 mt-1">{formatNumber(work.this_month_earnings)} Kč</div>
                </div>
              </div>
              {workGoalProgress ? (
                <div className="rounded-xl border border-emerald-400/20 bg-emerald-500/5 p-3">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="text-sm font-medium truncate">{workGoalProgress.title}</div>
                    <div className="text-sm font-semibold text-right shrink-0">{workGoalProgress.progress} %</div>
                  </div>
                  <div className="text-xs text-zinc-400 mb-2">
                    {formatNumber(workGoalProgress.current)} / {formatNumber(workGoalProgress.target)} h
                    {workGoalProgress.target_date ? ` · target ${formatDate(workGoalProgress.target_date)}` : null}
                  </div>
                  <ProgressBar value={workGoalProgress.progress} />
                </div>
              ) : null}
            </>
          ) : null}
        </Card>

        {/* FINANCE */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-amber-500/15 border border-amber-400/30 text-amber-200">💰</span>
              Finance
            </div>
          }
          actions={<Link href="/finance" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">Finance →</Link>}
          className="order-6"
        >
          {showSkeleton ? (
            <div className="space-y-3">
              <div className="h-12 rounded bg-zinc-800 animate-pulse" />
              <div className="h-16 rounded-xl bg-zinc-800/60 animate-pulse" />
            </div>
          ) : finance ? (
            <>
              <div className="rounded-xl bg-zinc-950/60 border border-zinc-800 p-4 mb-4">
                <div className="text-xs uppercase tracking-wider text-zinc-500">Aktuální bilance</div>
                <div className="text-2xl font-bold mt-1 text-amber-200">{formatNumber(finance.balance)} Kč</div>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="rounded-xl bg-emerald-500/5 border border-emerald-400/20 p-3">
                  <div className="text-xs uppercase tracking-wider text-zinc-500">Příjem tento měsíc</div>
                  <div className="text-lg font-semibold text-emerald-300 mt-1">{formatNumber(finance.this_month_income)} Kč</div>
                </div>
                <div className="rounded-xl bg-rose-500/5 border border-rose-400/20 p-3">
                  <div className="text-xs uppercase tracking-wider text-zinc-500">Výdaje tento měsíc</div>
                  <div className="text-lg font-semibold text-rose-300 mt-1">{formatNumber(finance.this_month_expenses)} Kč</div>
                </div>
              </div>
              {financeGoalProgress ? (
                <div className="rounded-xl border border-amber-400/20 bg-amber-500/5 p-3">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="text-sm font-medium truncate">{financeGoalProgress.title}</div>
                    <div className="text-sm font-semibold text-right shrink-0">{financeGoalProgress.progress} %</div>
                  </div>
                  <div className="text-xs text-zinc-400 mb-2">
                    {formatNumber(financeGoalProgress.current)} / {formatNumber(financeGoalProgress.target)} Kč
                    {financeGoalProgress.target_date ? ` · target ${formatDate(financeGoalProgress.target_date)}` : null}
                  </div>
                  <ProgressBar value={financeGoalProgress.progress} />
                </div>
              ) : null}
            </>
          ) : null}
        </Card>

        {/* GAMES (WOT + MFF) */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-orange-500/15 border border-orange-400/30 text-orange-200">🎮</span>
              Hry
            </div>
          }
          actions={
            <div className="flex items-center gap-3">
              <Link href="/wot" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">WoT →</Link>
              <Link href="/mff" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">MFF →</Link>
            </div>
          }
          className="order-7"
        >
          {showSkeleton ? (
            <div className="space-y-3">
              <div className="h-20 rounded-xl bg-zinc-800/60 animate-pulse" />
              <div className="h-20 rounded-xl bg-zinc-800/60 animate-pulse" />
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="font-semibold text-sm">World of Tanks</div>
                  {wot?.credits !== undefined && wot.credits !== null ? (
                    <span className="text-xs text-zinc-400">{formatNumber(wot.credits)} ₵</span>
                  ) : null}
                </div>
                {wot?.top_grinds && wot.top_grinds.length > 0 ? (
                  <div className="space-y-2">
                    {wot.top_grinds.slice(0, 2).map((g) => (
                      <div key={g.id} className="flex items-center justify-between gap-2 text-sm">
                        <div className="min-w-0 truncate">{g.tank}</div>
                        <div className="text-zinc-300 shrink-0">{formatNumber(g.xp_remaining)} XP</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-zinc-500">Žádné aktivní grindy.</div>
                )}
              </div>

              <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="font-semibold text-sm">Marvel Future Fight</div>
                  {mff ? <span className="text-xs text-zinc-400">{mff.tracked_characters} tracked</span> : null}
                </div>
                {mff ? (
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between gap-2">
                      <span className="text-zinc-400">T4</span>
                      <span className="font-semibold text-amber-300">{mff.t4_count}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                      <span className="text-zinc-400">High priority</span>
                      <span className="font-semibold">{mff.priority_count}</span>
                    </div>
                    <div>
                      <div className="flex justify-between gap-2 text-xs mb-1">
                        <span className="text-zinc-400">Avg build completeness</span>
                        <span>{mff.average_build_completeness} %</span>
                      </div>
                      <ProgressBar value={mff.average_build_completeness} height="h-1.5" />
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-zinc-500">Žádné postavy.</div>
                )}
              </div>
            </div>
          )}
        </Card>

        {/* QUICK ACTIONS */}
        <section className="md:col-span-2 xl:col-span-3 bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-5 order-8">
          <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
            <h2 className="text-lg md:text-xl font-semibold flex items-center gap-2">
              <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-zinc-500/15 border border-zinc-400/30 text-zinc-200">⚡</span>
              Rychlé akce
            </h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <Link
              href="/work"
              className="group rounded-2xl border border-zinc-800 hover:border-emerald-400/40 hover:bg-emerald-500/5 transition-colors p-4 min-h-[96px] flex flex-col justify-between"
            >
              <div className="text-xl">💼</div>
              <div>
                <div className="font-semibold">+ Work session</div>
                <div className="text-xs text-zinc-400">Zapsat hodiny</div>
              </div>
            </Link>
            <Link
              href="/finance"
              className="group rounded-2xl border border-zinc-800 hover:border-amber-400/40 hover:bg-amber-500/5 transition-colors p-4 min-h-[96px] flex flex-col justify-between"
            >
              <div className="text-xl">💰</div>
              <div>
                <div className="font-semibold">+ Finance expense</div>
                <div className="text-xs text-zinc-400">Přidat výdaj</div>
              </div>
            </Link>
            <Link
              href="/goals"
              className="group rounded-2xl border border-zinc-800 hover:border-emerald-400/40 hover:bg-emerald-500/5 transition-colors p-4 min-h-[96px] flex flex-col justify-between"
            >
              <div className="text-xl">🎯</div>
              <div>
                <div className="font-semibold">+ Cíl</div>
                <div className="text-xs text-zinc-400">Nový goal</div>
              </div>
            </Link>
            <Link
              href="/ai"
              className="group rounded-2xl border border-zinc-800 hover:border-indigo-400/40 hover:bg-indigo-500/5 transition-colors p-4 min-h-[96px] flex flex-col justify-between"
            >
              <div className="text-xl">🤖</div>
              <div>
                <div className="font-semibold">Otevřít AI</div>
                <div className="text-xs text-zinc-400">Chat asistent</div>
              </div>
            </Link>
            <Link
              href="/planner"
              className="group rounded-2xl border border-zinc-800 hover:border-sky-400/40 hover:bg-sky-500/5 transition-colors p-4 min-h-[96px] flex flex-col justify-between col-span-2 sm:col-span-1"
            >
              <div className="text-xl">📋</div>
              <div>
                <div className="font-semibold">Planner</div>
                <div className="text-xs text-zinc-400">Celý den / týden</div>
              </div>
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
