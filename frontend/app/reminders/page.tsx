"use client";

import { useMemo, useState } from "react";
import PushSettings from "@/components/PushSettings";
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
  StatusPulse,
  Tabs,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { staggerStyle } from "@/lib/motion";
import {
  createBody,
  emptyForm,
  groupReminders,
  snoozeOptions,
  stateLabel,
  WEEKDAY_LABELS,
  type Reminder,
  type ReminderForm,
} from "@/lib/reminders";
import { cx } from "@/lib/ui";

// Splatné připomínky se zazvoní i bez scheduleru při čtení – stránka se obnovuje jako zvonek.
const REFRESH_MS = 30000;

type View = "upcoming" | "history";

export default function RemindersPage() {
  const [view, setView] = useState<View>("upcoming");
  const reminders = useApiResource<Reminder[]>(`/reminders?status=${view === "history" ? "all" : "active"}`, {
    refreshMs: REFRESH_MS,
  });
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState<ReminderForm>(() => emptyForm());
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDue, setEditDue] = useState("");
  const [cancelTarget, setCancelTarget] = useState<Reminder | null>(null);

  const groups = useMemo(() => groupReminders(reminders.data ?? []), [reminders.data]);

  async function act(id: number, path: string, body?: unknown, method = "POST"): Promise<boolean> {
    setBusyId(id);
    setActionError(null);
    try {
      await apiJson(path, jsonBody(method, body));
      await reminders.reload();
      return true;
    } catch (err) {
      setActionError(errorMessage(err, "Akce se nepovedla."));
      return false;
    } finally {
      setBusyId(null);
    }
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
      await apiJson("/reminders", jsonBody("POST", body));
      setForm(emptyForm());
      await reminders.reload();
    } catch (err) {
      setActionError(errorMessage(err, "Připomínku se nepodařilo uložit."));
    } finally {
      setSaving(false);
    }
  }

  function startEdit(r: Reminder) {
    setEditingId(r.id);
    setEditTitle(r.title);
    setEditDue(r.recurrence === "none" ? r.due_local.slice(0, 16) : "");
  }

  async function saveEdit(r: Reminder) {
    const body: Record<string, unknown> = {};
    if (editTitle.trim() && editTitle.trim() !== r.title) body.title = editTitle.trim();
    if (r.recurrence === "none" && editDue && editDue !== r.due_local.slice(0, 16)) body.due_local = editDue;
    if (!Object.keys(body).length) {
      setEditingId(null);
      return;
    }
    if (await act(r.id, `/reminders/${r.id}`, body, "PATCH")) setEditingId(null);
  }

  function renderRow(r: Reminder, idx: number) {
    const due = r.state === "due";
    const closed = r.status === "done" || r.status === "cancelled";
    const busy = busyId === r.id;
    const editing = editingId === r.id;
    return (
      <EntityRow
        key={r.id}
        searchTarget={`reminder-${r.id}`}
        style={staggerStyle(idx)}
        className={cx("motion-card", due && "motion-attention")}
        tone={due ? "warning" : "neutral"}
        muted={closed}
        busy={busy}
        badges={
          <>
            <StatusBadge tone={due ? "warning" : closed ? "neutral" : "accent"} dot={due}>
              {stateLabel(r)}
            </StatusBadge>
            <span className="text-xs text-ink-muted">{r.recurrence_label}</span>
          </>
        }
        title={
          editing ? (
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className={fieldClass}
                aria-label="Text připomínky"
              />
              {r.recurrence === "none" && (
                <input
                  type="datetime-local"
                  value={editDue}
                  onChange={(e) => setEditDue(e.target.value)}
                  className={cx(fieldClass, "sm:w-auto")}
                  aria-label="Nový čas (Praha)"
                />
              )}
            </div>
          ) : (
            r.title
          )
        }
        meta={
          <>
            {closed ? `Původně: ${r.due_label}` : due ? `Mělo zaznít: ${r.next_label}` : `Kdy: ${r.next_label}`}
            {r.snoozed_label ? ` · odloženo na ${r.snoozed_label}` : ""}
          </>
        }
        actions={
          closed ? undefined : editing ? (
            <>
              <Button size="sm" variant="primary" busy={busy} busyLabel="Ukládám…" onClick={() => void saveEdit(r)}>
                Uložit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                Zpět
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant={due ? "success" : "secondary"}
                disabled={busy}
                onClick={() => void act(r.id, `/reminders/${r.id}/done`)}
              >
                Hotovo
              </Button>
              {snoozeOptions().map((o) => (
                <Button
                  key={o.label}
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void act(r.id, `/reminders/${r.id}/snooze`, o.body)}
                >
                  {o.label}
                </Button>
              ))}
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => startEdit(r)}>
                Upravit
              </Button>
              <Button size="sm" variant="danger" disabled={busy} onClick={() => setCancelTarget(r)}>
                Zrušit
              </Button>
            </>
          )
        }
      >
        {r.note ? <p className="mt-1 whitespace-pre-wrap text-sm text-ink-2">{r.note}</p> : null}
      </EntityRow>
    );
  }

  const listItems = view === "history" ? groups.history : groups.upcoming;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · připomínky</HudLabel>}
        title="Připomínky"
        subtitle="Časy jsou v pražském čase. Zazněná připomínka se objeví i ve zvonku notifikací."
      />

      {actionError ? <ErrorState message={actionError} /> : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
        <div className="min-w-0 space-y-6">
          {reminders.loading ? (
            <LoadingState lines={4} label="Načítám připomínky…" />
          ) : reminders.status === "error" ? (
            <ErrorState message={reminders.error} onRetry={() => void reminders.reload()} />
          ) : (
            <>
              {reminders.error ? <ErrorState message={`Obnovení selhalo: ${reminders.error}`} /> : null}
              {groups.due.length > 0 && (
                <PageSection
                  labelledBy="reminders-now"
                  title={
                    <span className="flex items-center gap-2 text-warning">
                      <StatusPulse tone="warning" live /> Teď ({groups.due.length})
                    </span>
                  }
                >
                  <EntityList label="Splatné připomínky">{groups.due.map(renderRow)}</EntityList>
                </PageSection>
              )}

              <section className="space-y-3" aria-label="Seznam připomínek">
                <Tabs
                  id="reminders-view"
                  label="Zobrazení připomínek"
                  value={view}
                  onChange={setView}
                  items={[
                    { value: "upcoming", label: "Nadcházející", count: view === "upcoming" ? groups.upcoming.length : undefined },
                    { value: "history", label: "Hotové a zrušené" },
                  ]}
                />
                <div role="tabpanel" id="reminders-view-panel" aria-labelledby={`reminders-view-${view}`} aria-busy={reminders.refreshing}>
                  {listItems.length ? (
                    <EntityList>{listItems.map(renderRow)}</EntityList>
                  ) : (
                    <EmptyState compact>
                      {view === "history" ? "Zatím žádné hotové ani zrušené připomínky." : "Žádné naplánované připomínky."}
                    </EmptyState>
                  )}
                </div>
              </section>
            </>
          )}
        </div>

        <div className="space-y-6">
          <Card as="section" aria-labelledby="new-reminder">
            <CardHeader as="h2" title={<span id="new-reminder">Nová připomínka</span>} />
            <form onSubmit={create} className="space-y-3">
              <FormField label="Co připomenout">
                {(p) => (
                  <input
                    {...p}
                    value={form.title}
                    onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                    placeholder="např. fyzio"
                    className={fieldClass}
                  />
                )}
              </FormField>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Opakování">
                  {(p) => (
                    <select
                      {...p}
                      value={form.mode}
                      onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value as ReminderForm["mode"] }))}
                      className={fieldClass}
                    >
                      <option value="once">Jednorázově</option>
                      <option value="daily">Denně</option>
                      <option value="weekly">Každý týden</option>
                    </select>
                  )}
                </FormField>
                {form.mode === "once" ? (
                  <FormField label="Kdy (Praha)" className="col-span-2 sm:col-span-1 lg:col-span-2">
                    {(p) => (
                      <input
                        {...p}
                        type="datetime-local"
                        value={form.dueLocal}
                        onChange={(e) => setForm((f) => ({ ...f, dueLocal: e.target.value }))}
                        className={fieldClass}
                      />
                    )}
                  </FormField>
                ) : (
                  <FormField label="Čas (Praha)">
                    {(p) => (
                      <input
                        {...p}
                        type="time"
                        value={form.timeLocal}
                        onChange={(e) => setForm((f) => ({ ...f, timeLocal: e.target.value }))}
                        className={fieldClass}
                      />
                    )}
                  </FormField>
                )}
              </div>
              {form.mode === "weekly" && (
                <div className="flex flex-wrap gap-1.5" role="group" aria-label="Dny v týdnu">
                  {WEEKDAY_LABELS.map((label, day) => {
                    const on = form.weekdays.includes(day);
                    return (
                      <button
                        key={label}
                        type="button"
                        aria-pressed={on}
                        onClick={() =>
                          setForm((f) => ({
                            ...f,
                            weekdays: on ? f.weekdays.filter((d) => d !== day) : [...f.weekdays, day],
                          }))
                        }
                        className={cx(
                          "motion-press h-10 w-10 rounded-lg border text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                          on ? "border-accent/60 bg-accent/15 text-accent-strong" : "border-line bg-surface-2 text-ink-2",
                        )}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              )}
              <FormField label="Poznámka" hint="Nepovinné">
                {(p) => (
                  <input
                    {...p}
                    value={form.note}
                    onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                    className={fieldClass}
                  />
                )}
              </FormField>
              <Button type="submit" variant="primary" busy={saving} busyLabel="Ukládám…" className="w-full">
                Přidat připomínku
              </Button>
            </form>
          </Card>

          <PushSettings />
        </div>
      </div>

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Zrušit připomínku?"
        message={cancelTarget ? `${cancelTarget.title} · ${cancelTarget.recurrence_label}` : undefined}
        confirmLabel="Zrušit připomínku"
        cancelLabel="Ponechat"
        busyLabel="Ruším…"
        onConfirm={async () => {
          const target = cancelTarget;
          // Dialog drží busy stav do odpovědi; chyba se pak ukáže na stránce.
          if (target) await act(target.id, `/reminders/${target.id}/cancel`);
          setCancelTarget(null);
        }}
        onCancel={() => setCancelTarget(null)}
      />
    </ContentContainer>
  );
}
