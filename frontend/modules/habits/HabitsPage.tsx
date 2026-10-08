"use client";

import { useState } from "react";
import {
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
  PageHeader,
  PageSection,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { staggerStyle } from "@/lib/motion";
import { cx } from "@/lib/ui";
import {
  createBody,
  emptyHabitForm,
  entryBody,
  entryMeasure,
  KIND_OPTIONS,
  percent,
  shortDay,
  STATE_META,
  type Habit,
  type HabitForm,
  type HabitsPayload,
} from "./lib";

/**
 * Návyky (MRK-21, pilot rámce modulů): dnešní stav, posledních 7 dní (vynecháno = odvozené serverem), založení,
 * splnění / přeskočení a archivace. Archivace nic nemaže – historie se vrátí po obnovení.
 */
export default function HabitsPage() {
  const habits = useApiResource<HabitsPayload>("/habits");
  const [form, setForm] = useState<HabitForm>(() => emptyHabitForm());
  const [values, setValues] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Habit | null>(null);

  async function act(id: number, path: string, body?: unknown): Promise<void> {
    setBusyId(id);
    setActionError(null);
    try {
      await apiJson(path, jsonBody("POST", body ?? {}));
      await habits.reload();
    } catch (err) {
      setActionError(errorMessage(err, "Akce se nepovedla."));
    } finally {
      setBusyId(null);
    }
  }

  async function record(h: Habit, state: "done" | "skipped") {
    let body: Record<string, unknown>;
    try {
      body = entryBody(h.kind, state, values[h.id] ?? "");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
      return;
    }
    await act(h.id, `/habits/${h.id}/entries`, body);
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    let body: Record<string, unknown>;
    try {
      body = createBody(form);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await apiJson("/habits", jsonBody("POST", body));
      setForm(emptyHabitForm());
      await habits.reload();
    } catch (err) {
      setActionError(errorMessage(err, "Návyk se nepodařilo uložit."));
    } finally {
      setSaving(false);
    }
  }

  function renderHabit(h: Habit, idx: number) {
    const state = h.today.state;
    const meta = state ? STATE_META[state] : null;
    const busy = busyId === h.id;
    const measure = entryMeasure(h, h.today.entry);
    return (
      <EntityRow
        key={h.id}
        searchTarget={`habit-${h.id}`}
        style={staggerStyle(idx)}
        className="motion-card"
        tone={state === "done" ? "success" : "neutral"}
        busy={busy}
        title={<span data-testid="habit-name">{h.name}</span>}
        badges={
          <>
            {meta ? (
              <StatusBadge tone={meta.tone} dot>
                <span data-testid="habit-state">{meta.label}</span>
              </StatusBadge>
            ) : null}
            {h.target_label ? <StatusBadge tone="neutral">cíl {h.target_label}</StatusBadge> : null}
          </>
        }
        meta={measure ? `Dnes: ${measure}` : undefined}
        actions={
          <>
            {state === "open" ? (
              <>
                {h.kind !== "check" ? (
                  <span className="block w-20 shrink-0">
                    <input
                      aria-label={h.kind === "duration" ? `Minuty: ${h.name}` : `Hodnota: ${h.name}`}
                      inputMode="decimal"
                      placeholder={h.kind === "duration" ? "min" : h.unit ?? "počet"}
                      value={values[h.id] ?? ""}
                      onChange={(e) => setValues((v) => ({ ...v, [h.id]: e.target.value }))}
                      className={fieldClass}
                    />
                  </span>
                ) : null}
                <Button size="sm" variant="secondary" busy={busy} busyLabel="Ukládám…" onClick={() => void record(h, "done")}
                  aria-label={`Splnit návyk: ${h.name}`}>
                  <span aria-hidden="true">✓</span> Splněno
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void record(h, "skipped")} aria-label={`Přeskočit návyk: ${h.name}`}>
                  Přeskočit
                </Button>
              </>
            ) : null}
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setArchiveTarget(h)} aria-label={`Archivovat návyk: ${h.name}`}>
              Archivovat
            </Button>
          </>
        }
      >
        <ol className="mt-2 flex flex-wrap gap-1" aria-label={`Posledních 7 dní: ${h.name}`}>
          {h.history.map((d) => {
            const m = d.state ? STATE_META[d.state] : null;
            return (
              <li key={d.date} className="text-[11px]">
                <span
                  data-history-state={d.state ?? "none"}
                  className={cx(
                    "inline-flex min-w-[4.5rem] flex-col rounded-md border px-1.5 py-0.5",
                    d.state === "done" && "border-success/40 bg-success/10 text-success",
                    d.state === "missed" && "border-danger/40 bg-danger/10 text-danger",
                    (d.state === "skipped" || d.state === "open") && "border-line bg-surface-2 text-ink-2",
                    !d.state && "border-line-subtle text-ink-muted",
                  )}
                >
                  <span>{shortDay(d.date)}</span>
                  <span>{m ? m.label : "–"}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </EntityRow>
    );
  }

  const data = habits.data;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · návyky</HudLabel>}
        title="Návyky"
        subtitle="Dnešní stav a posledních 7 dní. Den bez záznamu se po půlnoci počítá jako vynechaný."
      />

      {actionError ? <ErrorState message={actionError} /> : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
        <div className="min-w-0 space-y-6">
          {habits.loading ? (
            <LoadingState lines={4} label="Načítám návyky…" />
          ) : habits.status === "error" || !data ? (
            <ErrorState message={habits.error} onRetry={() => void habits.reload()} />
          ) : (
            <>
              <PageSection
                labelledBy="habits-today"
                title={
                  <span>
                    Dnes ({data.summary.done}/{data.summary.total}
                    {data.summary.week_expected ? ` · 7 dní ${percent(data.summary.week_done, data.summary.week_expected)} %` : ""})
                  </span>
                }
              >
                {data.active.length ? (
                  <EntityList label="Aktivní návyky">{data.active.map(renderHabit)}</EntityList>
                ) : (
                  <EmptyState compact>Zatím žádné návyky – přidej první vpravo.</EmptyState>
                )}
              </PageSection>

              {data.archived.length ? (
                <PageSection labelledBy="habits-archived" title="Archivované">
                  <EntityList label="Archivované návyky">
                    {data.archived.map((h) => (
                      <EntityRow
                        key={h.id}
                        searchTarget={`habit-${h.id}`}
                        muted
                        busy={busyId === h.id}
                        title={h.name}
                        meta="Historie zůstává uložená."
                        actions={
                          <Button size="sm" variant="ghost" disabled={busyId === h.id} onClick={() => void act(h.id, `/habits/${h.id}/restore`)}
                            aria-label={`Obnovit návyk: ${h.name}`}>
                            Obnovit
                          </Button>
                        }
                      />
                    ))}
                  </EntityList>
                </PageSection>
              ) : null}
            </>
          )}
        </div>

        <Card as="section" aria-labelledby="new-habit">
          <CardHeader as="h2" title={<span id="new-habit">Nový návyk</span>} />
          <form onSubmit={create} className="space-y-3">
            <FormField label="Název">
              {(p) => (
                <input {...p} value={form.name} placeholder="Rehab koleno, pitný režim…" onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={fieldClass} />
              )}
            </FormField>
            <FormField label="Druh" hint={KIND_OPTIONS.find((k) => k.value === form.kind)?.hint}>
              {(p) => (
                <select {...p} value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value as HabitForm["kind"] }))} className={fieldClass}>
                  {KIND_OPTIONS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              )}
            </FormField>
            {form.kind !== "check" ? (
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Cíl" hint="Nepovinné">
                  {(p) => <input {...p} inputMode="decimal" value={form.target} onChange={(e) => setForm((f) => ({ ...f, target: e.target.value }))} className={fieldClass} />}
                </FormField>
                <FormField label="Jednotka">
                  {(p) => (
                    <input {...p} value={form.unit} placeholder={form.kind === "duration" ? "min" : "l"} onChange={(e) => setForm((f) => ({ ...f, unit: e.target.value }))} className={fieldClass} />
                  )}
                </FormField>
              </div>
            ) : null}
            <Button type="submit" variant="primary" busy={saving} busyLabel="Ukládám…" className="w-full">
              Přidat návyk
            </Button>
          </form>
        </Card>
      </div>

      <ConfirmDialog
        open={archiveTarget !== null}
        title="Archivovat návyk?"
        message={archiveTarget ? `${archiveTarget.name} zmizí z Dnes. Historie zůstane a návyk jde kdykoli obnovit.` : undefined}
        confirmLabel="Archivovat"
        cancelLabel="Ponechat"
        busyLabel="Archivuji…"
        onConfirm={async () => {
          const target = archiveTarget;
          if (target) await act(target.id, `/habits/${target.id}/archive`);
          setArchiveTarget(null);
        }}
        onCancel={() => setArchiveTarget(null)}
      />
    </ContentContainer>
  );
}
