"use client";

import Link from "next/link";
import DailyBriefingCard from "@/components/DailyBriefingCard";
import WeeklyReviewCard from "@/components/WeeklyReviewCard";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import {
  AreaBadge,
  Button,
  Card,
  CardHeader,
  ContentContainer,
  EmptyState,
  EntityList,
  EntityRow,
  ErrorState,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  Progress,
  StatGrid,
  StatusBadge,
  StatusPulse,
  TextLink,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { formatDate, formatDays, formatNumber, formatRelativeDays } from "@/lib/format";
import { staggerStyle } from "@/lib/motion";
import { clampPercent, cx, priorityTone, severityTone, type Tone } from "@/lib/ui";

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

type GoalProgressInfo = {
  title: string;
  current_value: number | null;
  target_value: number | null;
  progress: number;
  target_date: string | null;
} | null;

type WorkQuick = {
  total_hours: number;
  total_earnings: number;
  this_month_hours: number;
  this_month_earnings: number;
  goal?: GoalProgressInfo;
};

type FinanceQuick = {
  balance: number;
  income: number;
  expenses: number;
  this_month_income: number;
  this_month_expenses: number;
  transactions_count: number;
  goal?: GoalProgressInfo;
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
    top_grinds: Array<{ id: number; tank: string; xp_remaining: number; priority: string; status: string }>;
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

const fmt0 = (v: number) => formatNumber(v, 0);
const fmt1 = (v: number) => formatNumber(v, 1);

function TodayRow({ a }: { a: TodayAction }) {
  const top = Number(a.priority) === 1;
  return (
    <EntityRow
      tone={top ? "accent" : "neutral"}
      badges={
        <>
          <span
            className={cx(
              "grid h-6 w-6 place-items-center rounded-full border font-mono text-[11px] font-semibold",
              top ? "border-accent/60 bg-accent/15 text-accent-strong" : "border-line text-ink-2",
            )}
            aria-label={`Priorita ${a.priority}`}
          >
            {a.priority}
          </span>
          <AreaBadge area={a.area} />
        </>
      }
      title={a.title}
      meta={a.reason}
    />
  );
}

function upcomingLabel(u: UpcomingItem): { tone: Tone; text: string } {
  const days = Number(u.days_left) || 0;
  if (u.overdue) return { tone: "danger", text: `po termínu · ${formatDays(Math.abs(days))}` };
  if (days === 0) return { tone: "warning", text: "dnes" };
  return { tone: days <= 3 ? "warning" : "neutral", text: formatRelativeDays(days) };
}

function GoalRow({ g }: { g: GoalQuick }) {
  const pct = clampPercent(g.progress);
  const hasValue = g.current_value !== null && g.current_value !== undefined && g.target_value;
  const unit = g.area === "finance" ? " Kč" : g.area === "work" ? " h" : "";
  const priority = priorityTone(g.priority);
  return (
    <li className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 break-words font-medium text-ink">{g.title}</span>
        <span className="flex flex-wrap items-center gap-1.5">
          <AreaBadge area={g.area} />
          {priority.tone !== "neutral" ? <StatusBadge tone={priority.tone}>{priority.label}</StatusBadge> : null}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Progress value={pct} label={`${g.title}: splněno ${pct} %`} className="flex-1" />
        <span className="w-11 text-right text-sm font-semibold tabular-nums text-ink">{pct} %</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-ink-muted">
        {hasValue ? (
          <span>
            {formatNumber(Number(g.current_value))} / {formatNumber(Number(g.target_value))}
            {unit}
          </span>
        ) : null}
        <span>{g.tracking_type === "automatic" ? "automaticky" : "ručně"}</span>
        {g.target_date ? <span>termín {formatDate(g.target_date)}</span> : null}
      </div>
    </li>
  );
}

function GoalProgressBlock({ goal, unit, fallbackTitle, current }: { goal: GoalProgressInfo | undefined; unit: string; fallbackTitle: string; current: number }) {
  if (!goal?.target_value || Number(goal.target_value) <= 0) return null;
  const pct = clampPercent(goal.progress);
  const title = goal.title || fallbackTitle;
  return (
    <div className="mt-3 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
      <div className="mb-2 flex items-center justify-between gap-2 text-sm">
        <span className="truncate font-medium text-ink">{title}</span>
        <span className="shrink-0 font-semibold tabular-nums">{pct} %</span>
      </div>
      <Progress value={pct} label={`${title}: splněno ${pct} %`} />
      <div className="mt-1.5 text-xs text-ink-muted">
        {formatNumber(goal.current_value ?? current)} / {formatNumber(Number(goal.target_value))} {unit}
        {goal.target_date ? ` · termín ${formatDate(goal.target_date)}` : null}
      </div>
    </div>
  );
}

const QUICK_ACTIONS = [
  { href: "/work", icon: "💼", title: "Zapsat práci", hint: "Odpracované hodiny" },
  { href: "/finance", icon: "💰", title: "Přidat výdaj", hint: "Finance" },
  { href: "/goals", icon: "🎯", title: "Nový cíl", hint: "Cíle" },
  { href: "/ai", icon: "🤖", title: "AI asistent", hint: "Chat" },
  { href: "/planner", icon: "📋", title: "Plánovač", hint: "Den / týden" },
];

export default function Home() {
  const dashboard = useApiResource<DashboardPayload>("/dashboard");
  const data = dashboard.data;
  const loading = dashboard.loading;
  const today = data?.today;
  const notifications = data?.notifications;
  const goals = data?.goals;
  const work = data?.work;
  const finance = data?.finance;
  const upcoming = data?.upcoming ?? [];
  const wot = data?.wot;
  const mff = data?.mff;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={
          <HudLabel className="flex items-center gap-2">
            <StatusPulse tone="success" live={!loading && !dashboard.error} /> Standa Hub · řídicí centrum
          </HudLabel>
        }
        title="Řídicí centrum"
        subtitle="Dnešní priority, přehledy, cíle, práce a finance na jednom místě."
        actions={
          <Button variant="secondary" onClick={() => void dashboard.reload()} busy={dashboard.refreshing} busyLabel="Obnovuji…">
            Obnovit
          </Button>
        }
      />

      {dashboard.status === "error" ? (
        <ErrorState message={dashboard.error} onRetry={() => void dashboard.reload()} retrying={dashboard.refreshing} />
      ) : dashboard.error ? (
        <ErrorState message={`Obnovení selhalo: ${dashboard.error}`} />
      ) : null}

      {/*
        Přehledy + čísla + Dnes v jedné mřížce. Na mobilu/tabletu v pořadí DOM (přehled, týden + pozornost,
        čísla, Dnes); na širokém displeji je „Dnes" pod denním přehledem vlevo a sloupec vpravo (týden +
        pozornost) se tak vyrovná s levým bez prázdného místa. Čísla jsou pod tím přes celou šířku.
      */}
      <div className="grid gap-4 md:gap-6 xl:grid-cols-3 xl:items-start">
        <div className="min-w-0 xl:col-span-2 xl:col-start-1 xl:row-start-1">
          <DailyBriefingCard index={0} />
        </div>
        <div className="grid min-w-0 items-start gap-4 md:grid-cols-2 md:gap-6 xl:col-start-3 xl:row-span-2 xl:row-start-1 xl:grid-cols-1">
          <WeeklyReviewCard index={1} />
          <Card index={2} aria-labelledby="attention-title">
            <CardHeader
              title={<span id="attention-title">Vyžaduje pozornost</span>}
              icon="🔔"
              actions={
                notifications && notifications.unread > 0 ? (
                  <StatusBadge tone={notifications.important > 0 ? "danger" : "warning"}>
                    {notifications.unread} nepřečtených
                  </StatusBadge>
                ) : undefined
              }
            />
            {loading ? (
              <LoadingState lines={2} />
            ) : notifications?.preview?.length ? (
              <ul className="space-y-2">
                {notifications.preview.slice(0, 3).map((n) => {
                  const sev = severityTone(n.severity);
                  const href = n.action_url && n.action_url.startsWith("/") ? n.action_url : null;
                  const body = (
                    <div className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
                      <div className="mb-1 flex flex-wrap items-center gap-1.5">
                        <StatusBadge tone={sev.tone} dot>
                          {sev.label}
                        </StatusBadge>
                        <AreaBadge area={n.area} />
                      </div>
                      <div className="break-words text-sm font-medium text-ink">{n.title}</div>
                      {n.message ? <div className="mt-0.5 line-clamp-2 break-words text-xs text-ink-muted">{n.message}</div> : null}
                    </div>
                  );
                  return (
                    <li key={n.id}>
                      {href ? (
                        <Link
                          href={href}
                          className="block rounded-[var(--radius-control)] motion-hover-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
                        >
                          {body}
                        </Link>
                      ) : (
                        body
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : data ? (
              <EmptyState compact>Žádná neřešená upozornění.</EmptyState>
            ) : null}
          </Card>

        </div>

        {/* Klíčová čísla */}
        <section aria-label="Klíčová čísla" className="motion-card min-w-0 xl:col-span-3 xl:row-start-3" style={staggerStyle(3)}>
          {loading ? (
            <StatGrid>
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-[92px] animate-pulse rounded-[var(--radius-control)] bg-surface" aria-hidden="true" />
              ))}
            </StatGrid>
          ) : data ? (
            <StatGrid>
              <MetricCard label="Odpracováno · měsíc" value={<AnimatedNumber value={work?.this_month_hours} format={fmt1} />} unit="h" />
              <MetricCard
                label="Výdělek · měsíc"
                value={<AnimatedNumber value={work?.this_month_earnings} format={fmt0} />}
                unit="Kč"
              />
              <MetricCard
                label="Bilance"
                value={<AnimatedNumber value={finance?.balance} format={fmt0} />}
                unit="Kč"
                tone={(finance?.balance ?? 0) < 0 ? "danger" : "neutral"}
                hint={`${finance?.transactions_count ?? 0} transakcí`}
              />
              <MetricCard
                label="Výdaje · měsíc"
                value={<AnimatedNumber value={finance?.this_month_expenses} format={fmt0} />}
                unit="Kč"
                hint={`příjem ${formatNumber(finance?.this_month_income, 0)} Kč`}
              />
            </StatGrid>
          ) : null}
        </section>

        {/* Dnes podle plánovače */}
        <Card index={4} aria-labelledby="today-title" className="min-w-0 xl:col-span-2 xl:col-start-1 xl:row-start-2">
          <CardHeader
            title={<span id="today-title">Dnes</span>}
            icon="☀️"
            description={today?.summary}
            actions={<TextLink href="/planner">Plánovač →</TextLink>}
          />
          {loading ? (
            <LoadingState lines={3} label="Načítám dnešní plán…" />
          ) : today && today.actions?.length ? (
            <EntityList label="Dnešní priority">
              {today.actions.slice(0, 3).map((a, i) => (
                <TodayRow key={`${a.priority}-${i}-${a.title}`} a={a} />
              ))}
            </EntityList>
          ) : data ? (
            <EmptyState action={<TextLink href="/goals">Nastavit cíle →</TextLink>}>Dnes podle plánovače nic nehoří.</EmptyState>
          ) : null}
        </Card>
      </div>

      {/* Cíle · Nadcházející · Práce/Finance; Hry jako široký pruh pod nimi (dřív třetí karta ve sloupci → sloupec o ~400 px vyšší) */}
      <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 md:gap-6 xl:grid-cols-3">
        {/* Cíle */}
        <Card index={5} aria-labelledby="goals-title">
          <CardHeader
            title={<span id="goals-title">Cíle</span>}
            icon="🎯"
            actions={<TextLink href="/goals">Všechny →</TextLink>}
          />
          {loading ? (
            <LoadingState lines={2} />
          ) : goals?.top?.length ? (
            <ul className="space-y-2">
              {goals.top.map((g) => (
                <GoalRow key={g.id} g={g} />
              ))}
            </ul>
          ) : data ? (
            <EmptyState compact>Zatím žádný aktivní cíl.</EmptyState>
          ) : null}
        </Card>

        {/* Nadcházející */}
        <Card index={6} aria-labelledby="upcoming-title">
          <CardHeader
            title={<span id="upcoming-title">Nadcházející</span>}
            icon="📅"
            actions={<TextLink href="/school">Škola →</TextLink>}
          />
          {loading ? (
            <LoadingState lines={3} />
          ) : upcoming.length ? (
            <EntityList label="Nadcházející termíny">
              {upcoming.map((u) => {
                const label = upcomingLabel(u);
                return (
                  <EntityRow
                    key={`${u.type}-${u.id}`}
                    tone={u.overdue ? "danger" : "neutral"}
                    badges={
                      <>
                        {u.type === "assignment" ? <StatusBadge>Úkol</StatusBadge> : null}
                        {u.type === "exam" ? <StatusBadge tone="info">Zkouška</StatusBadge> : null}
                        {u.type === "goal_target" ? <AreaBadge area={u.area} /> : null}
                        <StatusBadge tone={label.tone}>{label.text}</StatusBadge>
                      </>
                    }
                    title={u.title}
                    meta={formatDate(u.date)}
                  />
                );
              })}
            </EntityList>
          ) : data ? (
            <EmptyState compact>Žádné blížící se termíny.</EmptyState>
          ) : null}
        </Card>

        <div className="grid items-start gap-4 md:col-span-2 md:grid-cols-2 md:gap-6 xl:col-span-1 xl:grid-cols-1">
          {/* Práce */}
          <Card index={7} aria-labelledby="work-title">
            <CardHeader title={<span id="work-title">Práce</span>} icon="💼" actions={<TextLink href="/work">Práce →</TextLink>} />
            {loading ? (
              <LoadingState lines={2} />
            ) : work ? (
              <>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-ink-muted">Celkem odpracováno</dt>
                    <dd className="font-semibold tabular-nums text-ink">{formatNumber(work.total_hours, 1)} h</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Celkem vyděláno</dt>
                    <dd className="font-semibold tabular-nums text-ink">{formatNumber(work.total_earnings, 0)} Kč</dd>
                  </div>
                </dl>
                <GoalProgressBlock goal={work.goal} unit="h" fallbackTitle="Měsíční hodinový cíl" current={work.this_month_hours} />
              </>
            ) : null}
          </Card>

          {/* Finance */}
          <Card index={8} aria-labelledby="finance-title">
            <CardHeader
              title={<span id="finance-title">Finance</span>}
              icon="💰"
              actions={<TextLink href="/finance">Finance →</TextLink>}
            />
            {loading ? (
              <LoadingState lines={2} />
            ) : finance ? (
              <>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-ink-muted">Příjem tento měsíc</dt>
                    <dd className="font-semibold tabular-nums text-success">{formatNumber(finance.this_month_income, 0)} Kč</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Výdaje tento měsíc</dt>
                    <dd className="font-semibold tabular-nums text-ink">{formatNumber(finance.this_month_expenses, 0)} Kč</dd>
                  </div>
                </dl>
                <GoalProgressBlock goal={finance.goal} unit="Kč" fallbackTitle="Cíl bilance" current={finance.balance} />
              </>
            ) : null}
          </Card>

        </div>

        {/* Hry */}
        <Card index={9} aria-labelledby="games-title" className="md:col-span-2 xl:col-span-3">
          <CardHeader
            title={<span id="games-title">Hry</span>}
            icon="🎮"
            actions={
              <>
                <TextLink href="/wot">WoT →</TextLink>
                <TextLink href="/mff">MFF →</TextLink>
              </>
            }
          />
          {loading ? (
            <LoadingState lines={2} />
          ) : (
            <div className="grid gap-3 text-sm md:grid-cols-2">
              <div className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="font-medium text-ink">World of Tanks</span>
                  {wot?.credits !== undefined && wot.credits !== null ? (
                    <span className="text-xs tabular-nums text-ink-muted">{formatNumber(wot.credits, 0)} kreditů</span>
                  ) : null}
                </div>
                {wot?.top_grinds?.length ? (
                  wot.top_grinds.slice(0, 2).map((g) => (
                    <div key={g.id} className="flex justify-between gap-2">
                      <span className="min-w-0 truncate text-ink-2">{g.tank}</span>
                      <span className="shrink-0 tabular-nums text-ink-muted">{formatNumber(g.xp_remaining, 0)} XP</span>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-ink-muted">Žádné aktivní grindy.</p>
                )}
              </div>
              <div className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="font-medium text-ink">Marvel Future Fight</span>
                  {mff ? <span className="text-xs text-ink-muted">{mff.tracked_characters} sledovaných</span> : null}
                </div>
                {mff ? (
                  <>
                    <div className="flex justify-between gap-2">
                      <span className="text-ink-muted">T4 postavy</span>
                      <span className="tabular-nums text-ink">{mff.t4_count}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                      <span className="text-ink-muted">Vysoká priorita</span>
                      <span className="tabular-nums text-ink">{mff.priority_count}</span>
                    </div>
                    <div className="mt-2 flex items-center gap-3">
                      <Progress
                        size="sm"
                        value={mff.average_build_completeness}
                        label={`Průměrná rozpracovanost buildů ${mff.average_build_completeness} %`}
                        className="flex-1"
                      />
                      <span className="text-xs tabular-nums text-ink-muted">{mff.average_build_completeness} %</span>
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-ink-muted">Žádné postavy.</p>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Rychlé akce */}
      <Card index={10} aria-labelledby="quick-title">
        <CardHeader title={<span id="quick-title">Rychlé akce</span>} icon="⚡" />
        <nav aria-label="Rychlé akce" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {QUICK_ACTIONS.map((q) => (
            <Link
              key={q.href}
              href={q.href}
              className="motion-hover-lift flex min-h-[72px] items-center gap-3 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3 transition-colors hover:border-accent/40 hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              <span aria-hidden="true" className="text-lg">
                {q.icon}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-ink">{q.title}</span>
                <span className="block text-xs text-ink-muted">{q.hint}</span>
              </span>
            </Link>
          ))}
        </nav>
      </Card>
    </ContentContainer>
  );
}
