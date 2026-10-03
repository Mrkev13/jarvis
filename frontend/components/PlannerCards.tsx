// Barvy oblastí žijí v lib/areas.ts (sdílené s dashboardem, zvonkem a cíli).
import { areaMeta } from "@/lib/areas";
import { formatDate, formatNumber, formatPercent, formatRelativeDays } from "@/lib/format";
import { goalPaceMeta, goalTrackingLabel } from "@/lib/goals";
import { clampPercent, cx, priorityTone } from "@/lib/ui";
import { AreaBadge, Card, EmptyState, HudLabel, Progress, StatusBadge } from "@/components/ui";

export { areaMeta };

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


/**
 * Karty Planneru (Roadmap 4B): klidná karta systému, oblast jako štítek, priorita číslem.
 * Používá je stránka /planner i chat AI (compact). `headingLevel` drží správnou hierarchii nadpisů.
 */
function PlanCardShell(props: {
  label: string;
  summary: string;
  children: React.ReactNode;
  compact?: boolean;
  headingLevel?: "h2" | "h3";
}) {
  const Heading = props.headingLevel ?? "h3";
  return (
    <Card as="article" flush className={cx("overflow-hidden", props.compact ? "my-2" : null)}>
      <div className={cx("border-b border-line-subtle", props.compact ? "px-3 py-2.5" : "px-4 py-3 md:px-5 md:py-4")}>
        <HudLabel>{props.label}</HudLabel>
        <Heading className="mt-1 break-words font-semibold leading-snug text-ink">{props.summary}</Heading>
      </div>
      <div className={props.compact ? "p-3" : "p-4 md:p-5"}>{props.children}</div>
    </Card>
  );
}

function ActionItem(props: { action: PlannerAction; idx: number; compact?: boolean }) {
  const { action, idx, compact } = props;
  const priority = Number.isFinite(action.priority) ? action.priority : idx + 1;
  const isTop = priority === 1;
  return (
    <li className="flex items-start gap-3 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
      <span
        aria-label={`Priorita ${priority}`}
        className={cx(
          "grid h-8 w-8 shrink-0 place-items-center rounded-full border font-mono text-sm font-semibold tabular-nums",
          isTop ? "border-accent/50 bg-accent/10 text-accent-strong" : "border-line bg-surface text-ink-2",
        )}
      >
        {priority}
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <AreaBadge area={action.area} />
          {isTop ? <StatusBadge tone="accent">Nejvyšší priorita</StatusBadge> : null}
        </div>
        <div className="break-words font-medium leading-snug text-ink">{action.title}</div>
        {action.reason ? (
          <p className={cx("mt-1 break-words leading-snug text-ink-muted", compact ? "text-xs" : "text-sm")}>{action.reason}</p>
        ) : null}
      </div>
    </li>
  );
}

function ActionList({ plan, compact, empty }: { plan: PlannerPlan; compact?: boolean; empty: string }) {
  const sorted = [...(plan.actions || [])].sort((a, b) => a.priority - b.priority);
  if (!sorted.length) return <EmptyState compact={compact}>{empty}</EmptyState>;
  return (
    <ol className="space-y-2" aria-label="Doporučené kroky">
      {sorted.map((a, i) => (
        <ActionItem key={`${a.priority}-${a.title}-${i}`} action={a} idx={i} compact={compact} />
      ))}
    </ol>
  );
}

export function DailyPlanCard({ plan, compact, headingLevel }: { plan: PlannerPlan; compact?: boolean; headingLevel?: "h2" | "h3" }) {
  return (
    <PlanCardShell label="Denní plán" summary={plan.summary} compact={compact} headingLevel={headingLevel}>
      <ActionList plan={plan} compact={compact} empty="Na dnes nic nového k doporučení." />
    </PlanCardShell>
  );
}

export function WeeklyPlanCard({ plan, compact, headingLevel }: { plan: PlannerPlan; compact?: boolean; headingLevel?: "h2" | "h3" }) {
  return (
    <PlanCardShell label="Týdenní plán" summary={plan.summary} compact={compact} headingLevel={headingLevel}>
      <ActionList plan={plan} compact={compact} empty="Na tento týden nic nového k doporučení." />
    </PlanCardShell>
  );
}

function GoalReviewRow({ goal: g }: { goal: GoalReviewItem }) {
  const pct = clampPercent(g.progress);
  const pace = goalPaceMeta(g.stagnating, g.on_track);
  const prio = priorityTone(g.priority);
  const sinceDays = g.days_since_last_positive == null ? null : Math.max(0, g.days_since_last_positive);
  return (
    <li className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3 md:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <AreaBadge area={g.area} />
            {prio.tone !== "neutral" ? <StatusBadge tone={prio.tone}>Priorita: {prio.label.toLowerCase()}</StatusBadge> : null}
            {pace ? <StatusBadge tone={pace.tone} dot>{pace.label}</StatusBadge> : null}
          </div>
          <div className="break-words font-medium text-ink">{g.title}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-xl font-semibold tabular-nums text-ink">{formatPercent(pct)}</div>
          {g.current_value != null || g.target_value != null ? (
            <div className="text-xs tabular-nums text-ink-muted">
              {formatNumber(g.current_value)} / {formatNumber(g.target_value)}
            </div>
          ) : null}
        </div>
      </div>
      <Progress
        className="mt-3"
        value={pct}
        label={`Průběh cíle ${g.title}`}
        tone={pace?.tone === "danger" || pace?.tone === "warning" ? pace.tone : undefined}
      />
      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted">
        {g.target_date ? (
          <div className="flex gap-1.5">
            <dt>Cíl do</dt>
            <dd className="tabular-nums text-ink-2">{formatDate(g.target_date)}</dd>
          </div>
        ) : null}
        {sinceDays != null ? (
          <div className="flex gap-1.5">
            <dt>Poslední pokrok</dt>
            <dd className={g.stagnating ? "text-danger" : "text-ink-2"}>{formatRelativeDays(-sinceDays)}</dd>
          </div>
        ) : null}
        <div className="flex gap-1.5">
          <dt>Sledování</dt>
          <dd className="text-ink-2">{goalTrackingLabel(g.tracking_type, g.source)}</dd>
        </div>
      </dl>
    </li>
  );
}

export function GoalReviewCard({ plan, compact, headingLevel }: { plan: GoalReview; compact?: boolean; headingLevel?: "h2" | "h3" }) {
  const goals = plan.goals || [];
  return (
    <PlanCardShell label="Přehled cílů" summary={plan.summary} compact={compact} headingLevel={headingLevel}>
      {goals.length === 0 ? (
        <EmptyState compact={compact}>Žádné aktivní cíle k přehledu.</EmptyState>
      ) : (
        <ul className="space-y-2.5" aria-label="Cíle">
          {goals.map((g) => (
            <GoalReviewRow key={g.id} goal={g} />
          ))}
        </ul>
      )}
    </PlanCardShell>
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
