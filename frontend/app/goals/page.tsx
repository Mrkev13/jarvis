"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { areaMeta } from "@/lib/areas";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { GOAL_SOURCES, GOAL_STATUSES, goalSourceMeta, goalStatusMeta, goalTrackingLabel } from "@/lib/goals";
import { MAX_STAGGER, staggerStyle, useCompletionSignal } from "@/lib/motion";
import { cx, priorityTone } from "@/lib/ui";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import {
  AreaBadge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  EntityList,
  EntityRow,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  Progress,
  SectionHeader,
  StatGrid,
  StatusBadge,
} from "@/components/ui";

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

// Hodnoty beze změny (active, in_progress, completed, paused, cancelled) – jen české popisky.
const STATUS_OPTIONS: readonly string[] = GOAL_STATUSES;

const PRIORITY_OPTIONS = ["high", "medium", "low"] as const;

const TRACKING_OPTIONS = [
  { value: "manual", label: "Ručně (průběh v %)" },
  { value: "automatic", label: "Automaticky (napojeno na modul)" },
] as const;

function sourceUnit(source: string | null | undefined): string {
  return goalSourceMeta(source)?.unit ?? "";
}

function clamp(v: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, v));
}

const formatPct = (value: number) => formatPercent(value);

/**
 * Průběh cíle: pruh (Progress) + procento, které se při změně plynule „dopočítá"
 * a při dosažení 100 % krátce „pukne" (motion-complete) – jen při přechodu na 100, ne při načtení.
 */
function GoalProgress({
  pct,
  status,
  title,
  size,
  barValue,
}: {
  pct: number;
  status: string;
  title: string;
  size: "md" | "sm";
  /** Hodnota pruhu, pokud se liší od zobrazeného procenta (splněné cíle mají plný pruh). */
  barValue?: number;
}) {
  const completion = useCompletionSignal(pct);
  const completed = status.trim().toLowerCase() === "completed";
  return (
    <div className="flex items-center gap-3">
      <Progress
        value={barValue ?? pct}
        label={`Průběh cíle ${title}`}
        tone={completed ? "success" : undefined}
        size={size}
        className="flex-1"
      />
      <span
        key={completion}
        className={cx(
          "shrink-0 rounded-md text-right text-sm tabular-nums",
          size === "md" ? "w-14 font-semibold text-ink" : "w-12 text-ink-muted",
          completion > 0 && "motion-complete",
        )}
      >
        <AnimatedNumber value={pct} format={formatPct} />
      </span>
    </div>
  );
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
  source: GOAL_SOURCES[0].value,
  target_value: "",
  target_date: "",
};

type FieldError = { field: "title" | "target_value"; message: string } | null;

export default function GoalsPage() {
  const [summary, setSummary] = useState<GoalsSummary | null>(null);
  const [goals, setGoals] = useState<GoalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<FieldError>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingGoal, setDeletingGoal] = useState<GoalItem | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [sumRes, listRes] = await Promise.all([
        apiFetch("/goals/summary"),
        apiFetch("/goals/list"),
      ]);
      if (!sumRes.ok || !listRes.ok) throw new Error();
      setSummary((await sumRes.json()) as GoalsSummary);
      setGoals((await listRes.json()) as GoalItem[]);
      setLoaded(true);
    } catch {
      setLoadError("Nepodařilo se načíst cíle.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  function clearFormErrors() {
    setFormError(null);
    setFieldError(null);
  }

  function openNewForm() {
    setDraft(emptyDraft);
    clearFormErrors();
    setShowForm(true);
  }

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
        g.source && GOAL_SOURCES.some((o) => o.value === g.source)
          ? g.source
          : GOAL_SOURCES[0].value,
      target_value: g.target_value != null ? String(g.target_value) : "",
      target_date: g.target_date ?? "",
    });
    clearFormErrors();
    setShowForm(true);
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function resetForm() {
    setDraft(emptyDraft);
    clearFormErrors();
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.title.trim() || !draft.area) {
      setFieldError({ field: "title", message: "Vyplň název a zvol oblast cíle." });
      return;
    }
    const isAutomatic = draft.tracking_type === "automatic";
    if (isAutomatic && !draft.target_value.trim()) {
      setFieldError({ field: "target_value", message: "U automatického cíle vyplň cílovou hodnotu." });
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
    clearFormErrors();
    try {
      const res = await apiFetch("/goal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error();
      resetForm();
      await loadData();
    } catch (err) {
      console.error(err);
      setFormError("Nepodařilo se uložit cíl.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteGoal() {
    if (!deletingGoal) return;
    setActionError(null);
    try {
      const res = await apiFetch(`/goal/${deletingGoal.id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete goal");
      await loadData();
    } catch (err) {
      console.error(err);
      setActionError("Nepodařilo se smazat cíl.");
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

  const firstLoad = loading && !loaded;
  const isAutomaticDraft = draft.tracking_type === "automatic";
  const draftSource = goalSourceMeta(draft.source);
  const statValue = (n: number | undefined) => (firstLoad && !summary ? "…" : formatNumber(n ?? 0));

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · cíle</HudLabel>}
        title="Cíle"
        subtitle="Sledování cílů napříč všemi oblastmi s přehledem postupu."
        actions={
          !showForm ? (
            <Button variant="primary" onClick={openNewForm} aria-expanded={false}>
              Přidat cíl
            </Button>
          ) : null
        }
      />

      {loadError && loaded ? (
        <ErrorState message={loadError} onRetry={() => void loadData()} retrying={loading} />
      ) : null}
      {actionError ? <ErrorState message={actionError} /> : null}

      {showForm && (
        <Card as="section" aria-labelledby="goal-form-title">
          <CardHeader
            as="h2"
            title={
              <span id="goal-form-title">
                {draft.id ? `Úprava cíle #${draft.id}` : "Nový cíl"}
              </span>
            }
            actions={
              <Button size="sm" variant="ghost" onClick={resetForm} aria-expanded={true} aria-controls="goal-form">
                {draft.id ? "Zrušit úpravu" : "Zavřít"}
              </Button>
            }
          />
          <form id="goal-form" onSubmit={handleSubmit} className="space-y-4">
            {formError ? <ErrorState message={formError} /> : null}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <FormField
                label="Název *"
                error={fieldError?.field === "title" ? fieldError.message : undefined}
              >
                {(p) => (
                  <input
                    {...p}
                    type="text"
                    placeholder="např. Našetřit 150 000 Kč"
                    value={draft.title}
                    onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                    className={fieldClass}
                  />
                )}
              </FormField>
              <FormField label="Oblast *">
                {(p) => (
                  <select
                    {...p}
                    value={draft.area}
                    onChange={(e) => setDraft({ ...draft, area: e.target.value })}
                    className={fieldClass}
                  >
                    {AREA_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {areaMeta(opt).label}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>
              <FormField label="Stav">
                {(p) => (
                  <select
                    {...p}
                    value={draft.status}
                    onChange={(e) => setDraft({ ...draft, status: e.target.value })}
                    className={fieldClass}
                  >
                    {STATUS_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {goalStatusMeta(opt).label}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>
              <FormField label="Priorita">
                {(p) => (
                  <select
                    {...p}
                    value={draft.priority}
                    onChange={(e) => setDraft({ ...draft, priority: e.target.value })}
                    className={fieldClass}
                  >
                    {PRIORITY_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {priorityTone(opt).label}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>
              <FormField label="Sledování">
                {(p) => (
                  <select
                    {...p}
                    value={draft.tracking_type}
                    onChange={(e) => setDraft({ ...draft, tracking_type: e.target.value })}
                    className={fieldClass}
                  >
                    {TRACKING_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>
              <FormField label="Termín" hint="Nepovinné">
                {(p) => (
                  <input
                    {...p}
                    type="date"
                    value={draft.target_date}
                    min={todayIso()}
                    onChange={(e) => setDraft({ ...draft, target_date: e.target.value })}
                    className={fieldClass}
                  />
                )}
              </FormField>
              {isAutomaticDraft ? (
                <>
                  <FormField label="Zdroj dat">
                    {(p) => (
                      <select
                        {...p}
                        value={draft.source}
                        onChange={(e) => setDraft({ ...draft, source: e.target.value })}
                        className={fieldClass}
                      >
                        {GOAL_SOURCES.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label} ({opt.unit})
                          </option>
                        ))}
                      </select>
                    )}
                  </FormField>
                  <FormField
                    label={`Cílová hodnota${draftSource ? ` (${draftSource.unit})` : ""} *`}
                    error={fieldError?.field === "target_value" ? fieldError.message : undefined}
                  >
                    {(p) => (
                      <input
                        {...p}
                        type="number"
                        inputMode="decimal"
                        min={0}
                        step={draft.source === "finance_balance" ? 1 : 0.25}
                        placeholder={draftSource?.placeholder ?? ""}
                        value={draft.target_value}
                        onChange={(e) => setDraft({ ...draft, target_value: e.target.value })}
                        className={fieldClass}
                      />
                    )}
                  </FormField>
                </>
              ) : (
                <FormField label="Průběh (%)" hint="0–100">
                  {(p) => (
                    <input
                      {...p}
                      type="number"
                      inputMode="numeric"
                      min={0}
                      max={100}
                      value={draft.progress}
                      onChange={(e) => setDraft({ ...draft, progress: e.target.value })}
                      className={fieldClass}
                    />
                  )}
                </FormField>
              )}
              <FormField label="Popis" hint="Nepovinné" className="md:col-span-2">
                {(p) => (
                  <textarea
                    {...p}
                    rows={2}
                    placeholder="Popis cíle, jak dosáhnout…"
                    value={draft.description}
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                    className={cx(fieldClass, "resize-none")}
                  />
                )}
              </FormField>
            </div>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="secondary" onClick={resetForm}>
                Storno
              </Button>
              <Button type="submit" variant="primary" busy={submitting} busyLabel="Ukládám…" disabled={loading}>
                {draft.id ? "Uložit změny" : "Vytvořit cíl"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      <section aria-labelledby="goals-overview" className="space-y-3">
        <h2 id="goals-overview" className="sr-only">
          Přehled
        </h2>
        <StatGrid cols={4}>
          <MetricCard label="Aktivní" value={statValue(summary?.active)} />
          <MetricCard label="Rozpracované" value={statValue(summary?.in_progress)} />
          <MetricCard label="Splněné" value={statValue(summary?.completed)} />
          <MetricCard label="Celkem" value={statValue(summary?.total)} />
        </StatGrid>
      </section>

      {firstLoad ? (
        <LoadingState lines={4} label="Načítám cíle…" />
      ) : loadError && !loaded ? (
        <ErrorState message={loadError} onRetry={() => void loadData()} retrying={loading} />
      ) : (
        <>
          <PageSection
            labelledBy="goals-active"
            title={`Aktivní cíle${activeGoals.length ? ` (${activeGoals.length})` : ""}`}
          >
            <div aria-busy={loading || undefined}>
              {activeGoals.length === 0 ? (
                <EmptyState
                  action={
                    !showForm ? (
                      <Button size="sm" variant="secondary" onClick={openNewForm}>
                        Přidat cíl
                      </Button>
                    ) : undefined
                  }
                >
                  Zatím žádné aktivní cíle.
                </EmptyState>
              ) : (
                <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  {activeGoals.map((g, gi) => (
                    <ActiveGoalCard
                      key={g.id}
                      goal={g}
                      index={Math.min(gi, MAX_STAGGER)}
                      onEdit={() => startEdit(g)}
                      onDelete={() => setDeletingGoal(g)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </PageSection>

          {completedGoals.length > 0 || otherGoals.length > 0 ? (
            <PageSection
              labelledBy="goals-closed"
              title="Splněné, pozastavené a zrušené"
              description="Cíle, na kterých se teď nepracuje."
            >
              <div className="space-y-5" aria-busy={loading || undefined}>
                {completedGoals.length > 0 && (
                  <div className="space-y-2">
                    <SectionHeader as="h3" title={`Splněné (${completedGoals.length})`} />
                    <EntityList label="Splněné cíle">
                      {completedGoals.map((g, gi) => (
                        <SecondaryGoalRow
                          key={g.id}
                          goal={g}
                          index={Math.min(gi, MAX_STAGGER)}
                          onEdit={() => startEdit(g)}
                          onDelete={() => setDeletingGoal(g)}
                        />
                      ))}
                    </EntityList>
                  </div>
                )}
                {otherGoals.length > 0 && (
                  <div className="space-y-2">
                    <SectionHeader as="h3" title={`Pozastavené a zrušené (${otherGoals.length})`} />
                    <EntityList label="Pozastavené a zrušené cíle">
                      {otherGoals.map((g, gi) => (
                        <SecondaryGoalRow
                          key={g.id}
                          goal={g}
                          index={Math.min(gi, MAX_STAGGER)}
                          onEdit={() => startEdit(g)}
                          onDelete={() => setDeletingGoal(g)}
                        />
                      ))}
                    </EntityList>
                  </div>
                )}
              </div>
            </PageSection>
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={deletingGoal != null}
        title={`Smazat cíl „${deletingGoal?.title ?? ""}“?`}
        message="Tato akce je nevratná. Cíl bude odstraněn ze Standa Hubu."
        confirmLabel="Smazat cíl"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteGoal}
        onCancel={() => setDeletingGoal(null)}
      />
    </ContentContainer>
  );
}

/** Aktuální / cílová hodnota automatického cíle s jednotkou zdroje. */
function GoalValues({ goal }: { goal: GoalItem }) {
  return (
    <span className="text-sm tabular-nums">
      <span className={goal.current_value != null ? "font-semibold text-ink" : "text-ink-faint"}>
        {formatNumber(goal.current_value)}
      </span>
      <span className="mx-1 text-ink-faint">/</span>
      <span className="font-semibold text-ink">{formatNumber(goal.target_value)}</span>
      {sourceUnit(goal.source) ? <span className="ml-1 text-ink-muted">{sourceUnit(goal.source)}</span> : null}
    </span>
  );
}

function ActiveGoalCard({
  goal: g,
  index,
  onEdit,
  onDelete,
}: {
  goal: GoalItem;
  index: number;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const status = goalStatusMeta(g.status);
  const priority = priorityTone(g.priority);
  const pct = clamp(g.progress ?? 0);
  return (
    <Card as="li" index={index} data-search-target={`goal-${g.id}`} className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <AreaBadge area={g.area} />
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        <StatusBadge tone={priority.tone}>Priorita: {priority.label}</StatusBadge>
      </div>
      <div className="min-w-0">
        <h3 className="break-words text-base font-semibold text-ink md:text-lg">{g.title}</h3>
        {g.description && (
          <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink-2">{g.description}</p>
        )}
      </div>
      <div className="mt-auto space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs text-ink-muted">
          <span className="min-w-0 break-words">{goalTrackingLabel(g.tracking_type, g.source)}</span>
          {g.tracking_type === "automatic" ? <GoalValues goal={g} /> : null}
        </div>
        <GoalProgress pct={pct} status={g.status} title={g.title} size="md" />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-subtle pt-3">
        <span className="text-xs text-ink-muted">
          {g.target_date ? (
            <>
              Termín: <span className="tabular-nums text-ink-2">{formatDate(g.target_date)}</span>
            </>
          ) : (
            "Bez termínu"
          )}
        </span>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={onEdit} aria-label={`Upravit cíl ${g.title}`}>
            Upravit
          </Button>
          <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Smazat cíl ${g.title}`}>
            Smazat
          </Button>
        </div>
      </div>
    </Card>
  );
}

function SecondaryGoalRow({
  goal: g,
  index,
  onEdit,
  onDelete,
}: {
  goal: GoalItem;
  index: number;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const status = goalStatusMeta(g.status);
  const completed = g.status.toLowerCase() === "completed";
  const pct = clamp(g.progress ?? 0);
  return (
    <EntityRow
      searchTarget={`goal-${g.id}`}
      className={cx("motion-card", !completed && "opacity-80")}
      style={staggerStyle(index)}
      muted={completed}
      badges={
        <>
          <AreaBadge area={g.area} />
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        </>
      }
      title={g.title}
      meta={
        <>
          {goalTrackingLabel(g.tracking_type, g.source)}
          {g.target_date ? ` · termín ${formatDate(g.target_date)}` : ""}
        </>
      }
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Upravit cíl ${g.title}`}>
            Upravit
          </Button>
          <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Smazat cíl ${g.title}`}>
            Smazat
          </Button>
        </>
      }
    >
      <div className="mt-2 max-w-md">
        <GoalProgress pct={pct} status={g.status} title={g.title} size="sm" barValue={completed ? 100 : undefined} />
      </div>
    </EntityRow>
  );
}
