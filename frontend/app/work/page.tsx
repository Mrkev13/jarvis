"use client";

import { useMemo, useState } from "react";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  StatGrid,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { formatCzkExact, formatDate, formatHours, plural } from "@/lib/format";
import { MAX_STAGGER, staggerStyle, useNewIds } from "@/lib/motion";
import { cx } from "@/lib/ui";
import {
  estimateEarnings,
  financeSyncMeta,
  groupSessionsByDay,
  type WorkSessionItem,
  type WorkSummary,
} from "@/lib/work";

const FORM_ID = "work-session-form";
const VALIDATION_MESSAGE = "Vyplň platné datum a kladný počet hodin.";

function todayIso() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function WorkPage() {
  const sessionsRes = useApiResource<WorkSessionItem[]>("/work/sessions");
  const summaryRes = useApiResource<WorkSummary>("/work/summary");
  const sessions = useMemo(() => sessionsRes.data ?? [], [sessionsRes.data]);
  const summary = summaryRes.data;
  const days = useMemo(() => groupSessionsByDay(sessions), [sessions]);
  const firstLoad = sessionsRes.loading || summaryRes.loading;
  const refreshing = sessionsRes.refreshing || summaryRes.refreshing;

  // Nově přidané záznamy krátce zvýraznit (ne při prvním načtení).
  const newSessionIds = useNewIds(
    sessions.map((s) => s.id),
    sessionsRes.data !== null && !firstLoad,
  );

  const [actionError, setActionError] = useState<string | null>(null);
  const [validationField, setValidationField] = useState<"date" | "hours" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingSession, setDeletingSession] = useState<WorkSessionItem | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [date, setDate] = useState(todayIso());
  const [hours, setHours] = useState("");
  const [project, setProject] = useState("");
  const [description, setDescription] = useState("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [syncToFinance, setSyncToFinance] = useState(true);

  const estimate = estimateEarnings(hours, hourlyRate);

  async function reloadAll() {
    await Promise.all([sessionsRes.reload(), summaryRes.reload()]);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const hoursNum = parseFloat(hours);
    if (!date || !isFinite(hoursNum) || hoursNum <= 0) {
      setValidationField(!date ? "date" : "hours");
      return;
    }
    setValidationField(null);
    const rate = hourlyRate ? parseFloat(hourlyRate) : 0;

    setSubmitting(true);
    setActionError(null);
    try {
      await apiJson(
        "/work/session",
        jsonBody("POST", {
          date,
          hours: hoursNum,
          project: project.trim(),
          description: description.trim(),
          hourly_rate: isFinite(rate) ? rate : 0,
          sync_to_finance: syncToFinance,
        }),
      );
      setHours("");
      setProject("");
      setDescription("");
      setHourlyRate("");
      setSyncToFinance(true);
      setShowForm(false);
      await reloadAll();
    } catch (err) {
      setActionError(errorMessage(err, "Nepodařilo se uložit záznam práce."));
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteSession() {
    if (!deletingSession) return;
    setActionError(null);
    try {
      await apiJson(`/work/session/${deletingSession.id}`, { method: "DELETE" });
      await reloadAll();
    } catch (err) {
      setActionError(errorMessage(err, "Nepodařilo se smazat záznam práce."));
    } finally {
      setDeletingSession(null);
    }
  }

  const loadError =
    sessionsRes.status === "error" || summaryRes.status === "error"
      ? sessionsRes.error || summaryRes.error || "Nepodařilo se načíst pracovní data."
      : null;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · práce</HudLabel>}
        title="Práce"
        subtitle="Odpracované hodiny, projekty a výdělek."
        actions={
          <Button
            variant={showForm ? "secondary" : "primary"}
            aria-expanded={showForm}
            aria-controls={FORM_ID}
            onClick={() => setShowForm((v) => !v)}
          >
            {showForm ? "Zavřít formulář" : "Přidat záznam"}
          </Button>
        }
      />

      {actionError ? <ErrorState message={actionError} /> : null}

      {showForm && (
        <Card as="section" aria-labelledby="work-form-title">
          <CardHeader title={<span id="work-form-title">Nový záznam práce</span>} />
          <form id={FORM_ID} onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField label="Datum" error={validationField === "date" ? VALIDATION_MESSAGE : undefined}>
                {(p) => (
                  <input
                    {...p}
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className={fieldClass}
                  />
                )}
              </FormField>
              <FormField label="Hodiny" error={validationField === "hours" ? VALIDATION_MESSAGE : undefined}>
                {(p) => (
                  <input
                    {...p}
                    type="number"
                    inputMode="decimal"
                    min="0.25"
                    step="0.25"
                    placeholder="např. 7.5"
                    value={hours}
                    onChange={(e) => setHours(e.target.value)}
                    className={fieldClass}
                  />
                )}
              </FormField>
              <FormField label="Projekt" hint="Nepovinné">
                {(p) => (
                  <input
                    {...p}
                    type="text"
                    placeholder="např. Servind"
                    value={project}
                    onChange={(e) => setProject(e.target.value)}
                    className={fieldClass}
                  />
                )}
              </FormField>
              <FormField label="Hodinová sazba (Kč)" hint="Nepovinné">
                {(p) => (
                  <input
                    {...p}
                    type="number"
                    inputMode="decimal"
                    min="0"
                    placeholder="např. 325"
                    value={hourlyRate}
                    onChange={(e) => setHourlyRate(e.target.value)}
                    className={fieldClass}
                  />
                )}
              </FormField>
              <FormField label="Popis" hint="Nepovinné" className="sm:col-span-2">
                {(p) => (
                  <textarea
                    {...p}
                    rows={2}
                    placeholder="Popis práce…"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className={cx(fieldClass, "resize-none")}
                  />
                )}
              </FormField>
              <div className="flex items-start gap-3 sm:col-span-2">
                <input
                  id="sync-finance"
                  type="checkbox"
                  checked={syncToFinance}
                  onChange={(e) => setSyncToFinance(e.target.checked)}
                  aria-describedby="sync-finance-hint"
                  className="mt-0.5 h-5 w-5 shrink-0 accent-accent [color-scheme:dark]"
                />
                <div className="min-w-0">
                  <label htmlFor="sync-finance" className="text-sm text-ink select-none">
                    Zapsat výdělek také do Financí
                  </label>
                  <p id="sync-finance-hint" className="text-xs text-ink-muted">
                    Vytvoří příjem v kategorii „work“.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-muted" aria-live="polite">
                {estimate !== null ? (
                  <>
                    Odhad výdělku: <span className="font-medium tabular-nums text-ink">{formatCzkExact(estimate)}</span>
                  </>
                ) : null}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button variant="ghost" onClick={() => setShowForm(false)}>
                  Storno
                </Button>
                <Button type="submit" variant="primary" busy={submitting} busyLabel="Ukládám…" disabled={firstLoad}>
                  Uložit
                </Button>
              </div>
            </div>
          </form>
        </Card>
      )}

      {firstLoad ? (
        <LoadingState lines={5} label="Načítám pracovní data…" />
      ) : loadError ? (
        <ErrorState message={loadError} onRetry={() => void reloadAll()} retrying={refreshing} />
      ) : (
        <>
          {sessionsRes.error || summaryRes.error ? (
            <ErrorState message={`Obnovení selhalo: ${sessionsRes.error || summaryRes.error}`} />
          ) : null}

          <PageSection title="Přehled" labelledBy="work-overview">
            <div aria-busy={refreshing || undefined}>
              <StatGrid cols={4}>
                <MetricCard
                  label="Hodiny · tento měsíc"
                  value={<AnimatedNumber value={summary?.this_month_hours} format={formatHours} fallback="–" />}
                />
                <MetricCard
                  label="Výdělek · tento měsíc"
                  value={<AnimatedNumber value={summary?.this_month_earnings} format={formatCzkExact} fallback="–" />}
                />
                <MetricCard
                  label="Hodiny · celkem"
                  value={<AnimatedNumber value={summary?.total_hours} format={formatHours} fallback="–" />}
                />
                <MetricCard
                  label="Výdělek · celkem"
                  value={<AnimatedNumber value={summary?.total_earnings} format={formatCzkExact} fallback="–" />}
                />
              </StatGrid>
            </div>
          </PageSection>

          <PageSection title="Historie práce" labelledBy="work-history" description="Nejnovější dny nahoře.">
            <div aria-busy={refreshing || undefined}>
              {days.length === 0 ? (
                <EmptyState
                  action={
                    showForm ? undefined : (
                      <Button variant="secondary" aria-controls={FORM_ID} aria-expanded={false} onClick={() => setShowForm(true)}>
                        Přidat záznam
                      </Button>
                    )
                  }
                >
                  Zatím žádná odpracovaná práce.
                </EmptyState>
              ) : (
                <ol className="space-y-5" aria-label="Záznamy práce po dnech">
                  {days.map((day, di) => (
                    <li key={day.date} className="min-w-0">
                      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                        <h3 className="text-sm font-semibold text-ink">{formatDate(day.date)}</h3>
                        <p className="text-xs text-ink-muted tabular-nums">
                          {day.sessions.length > 1
                            ? `${day.sessions.length} ${plural(day.sessions.length, "záznam", "záznamy", "záznamů")} · `
                            : null}
                          {formatHours(day.hours)} · <span data-day-total>{formatCzkExact(day.earnings)}</span>
                        </p>
                      </div>
                      <ul className="space-y-2 border-l border-line pl-3 md:pl-4">
                        {day.sessions.map((s) => (
                          <SessionRow
                            key={s.id}
                            session={s}
                            fresh={newSessionIds.has(String(s.id))}
                            staggerIndex={Math.min(di, MAX_STAGGER)}
                            onDelete={() => setDeletingSession(s)}
                          />
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </PageSection>
        </>
      )}

      <ConfirmDialog
        open={deletingSession != null}
        title={`Smazat záznam ${deletingSession?.project || (deletingSession ? formatDate(deletingSession.date) : "")}?`}
        message="Tato akce je nevratná. Změny se projeví ve statistikách práce."
        confirmLabel="Smazat"
        cancelLabel="Ponechat"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteSession}
        onCancel={() => setDeletingSession(null)}
      />
    </ContentContainer>
  );
}

function SessionRow({
  session: s,
  fresh,
  staggerIndex,
  onDelete,
}: {
  session: WorkSessionItem;
  fresh: boolean;
  staggerIndex: number;
  onDelete: () => void;
}) {
  const finance = financeSyncMeta(s);
  return (
    <li
      style={staggerStyle(staggerIndex)}
      className={cx(
        "motion-card relative rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-3 py-3 md:px-4",
        fresh && "motion-highlight",
      )}
    >
      <span
        aria-hidden="true"
        className="absolute top-5 -left-[calc(0.75rem+4.5px)] h-2 w-2 rounded-full border border-line bg-surface md:-left-[calc(1rem+4.5px)]"
      />
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-14 shrink-0 text-lg font-semibold tabular-nums text-ink">{formatHours(s.hours)}</div>
        <div className="min-w-0 flex-1 basis-40">
          <div className="break-words font-medium text-ink">{s.project || "Bez projektu"}</div>
          {s.description ? <p className="mt-0.5 break-words text-sm text-ink-2">{s.description}</p> : null}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
            {s.hourly_rate > 0 ? <span className="tabular-nums">{formatCzkExact(s.hourly_rate)}/h</span> : null}
            {finance ? <StatusBadge tone={finance.tone}>{finance.label}</StatusBadge> : null}
          </div>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-3">
          <span data-session-earnings className="text-base font-semibold tabular-nums text-ink">{formatCzkExact(s.earnings)}</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={onDelete}
            aria-label={`Smazat záznam ${s.project || ""} ${formatDate(s.date)}`.replace(/\s+/g, " ")}
          >
            Smazat
          </Button>
        </div>
      </div>
    </li>
  );
}
