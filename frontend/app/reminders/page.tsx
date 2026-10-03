"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
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

// Splatné připomínky se zazvoní i bez scheduleru při čtení – stránka se obnovuje jako zvonek.
const REFRESH_MS = 30000;

async function readError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    return typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export default function RemindersPage() {
  const [items, setItems] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ReminderForm>(() => emptyForm());
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDue, setEditDue] = useState("");
  const [cancelTarget, setCancelTarget] = useState<Reminder | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`/reminders?status=${showHistory ? "all" : "active"}`);
      if (!res.ok) throw new Error(await readError(res));
      setItems((await res.json()) as Reminder[]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nepodařilo se načíst připomínky.");
    } finally {
      setLoading(false);
    }
  }, [showHistory]);

  useEffect(() => {
    queueMicrotask(() => void load());
    const t = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const groups = useMemo(() => groupReminders(items), [items]);

  async function act(id: number, path: string, body?: unknown, method = "POST") {
    setBusyId(id);
    try {
      const res = await apiFetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await readError(res));
      await load();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Akce se nepovedla.");
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
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    setSaving(true);
    try {
      const res = await apiFetch("/reminders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await readError(res));
      setForm(emptyForm());
      setError(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Připomínku se nepodařilo uložit.");
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

  function renderCard(r: Reminder, idx: number) {
    const due = r.state === "due";
    const closed = r.status === "done" || r.status === "cancelled";
    const busy = busyId === r.id;
    const editing = editingId === r.id;
    return (
      <div
        key={r.id}
        style={staggerStyle(idx)}
        aria-busy={busy}
        className={`motion-card rounded-2xl border p-4 md:p-5 transition-colors ${
          due
            ? "motion-attention border-amber-500/50 bg-amber-500/10"
            : closed
              ? "border-zinc-800/60 bg-zinc-900/40 text-zinc-400"
              : "border-zinc-800 bg-zinc-900"
        }`}
      >
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap text-xs">
              <span
                className={`rounded-full border px-2 py-0.5 font-semibold uppercase tracking-wider ${
                  due ? "border-amber-400/50 text-amber-200" : "border-zinc-700 text-zinc-400"
                }`}
              >
                {stateLabel(r)}
              </span>
              <span className="text-zinc-500">{r.recurrence_label}</span>
            </div>
            {editing ? (
              <div className="mt-2 flex flex-col sm:flex-row gap-2">
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 outline-none focus:border-zinc-500"
                  aria-label="Text připomínky"
                />
                {r.recurrence === "none" && (
                  <input
                    type="datetime-local"
                    value={editDue}
                    onChange={(e) => setEditDue(e.target.value)}
                    className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 outline-none focus:border-zinc-500"
                    aria-label="Nový čas (Praha)"
                  />
                )}
              </div>
            ) : (
              <div className={`mt-1.5 text-base md:text-lg font-semibold ${closed ? "line-through" : "text-white"}`}>
                {r.title}
              </div>
            )}
            <div className="mt-1 text-sm text-zinc-400">
              {closed ? `Původně: ${r.due_label}` : due ? `Mělo zaznít: ${r.next_label}` : `Kdy: ${r.next_label}`}
              {r.snoozed_label ? ` · odloženo na ${r.snoozed_label}` : ""}
            </div>
            {r.note && <div className="mt-1 text-sm text-zinc-500 whitespace-pre-wrap">{r.note}</div>}
          </div>
          {!closed && (
            <div className="flex flex-wrap gap-2">
              {editing ? (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void saveEdit(r)}
                    className="motion-press rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 px-3 py-2 text-sm font-medium text-white"
                  >
                    Uložit
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    className="motion-press rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 px-3 py-2 text-sm"
                  >
                    Zpět
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act(r.id, `/reminders/${r.id}/done`)}
                    className="motion-press rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 px-3 py-2 text-sm font-medium text-white"
                  >
                    Hotovo
                  </button>
                  {snoozeOptions().map((o) => (
                    <button
                      key={o.label}
                      type="button"
                      disabled={busy}
                      onClick={() => void act(r.id, `/reminders/${r.id}/snooze`, o.body)}
                      className="motion-press rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-3 py-2 text-sm"
                    >
                      {o.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => startEdit(r)}
                    className="motion-press rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-3 py-2 text-sm"
                  >
                    Upravit
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setCancelTarget(r)}
                    className="motion-press rounded-xl border border-red-500/40 text-red-300 hover:bg-red-500/10 disabled:opacity-50 px-3 py-2 text-sm"
                  >
                    Zrušit
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <main className="motion-page p-4 md:p-8 max-w-4xl mx-auto space-y-8">
      <header>
        <h1 className="text-2xl md:text-4xl font-bold">⏰ Připomínky</h1>
        <p className="text-zinc-400 mt-2">
          Časy jsou v pražském čase. Zazněná připomínka se objeví i ve zvonku notifikací.
        </p>
      </header>

      {error && (
        <div role="alert" className="bg-red-500/10 border border-red-500/30 text-red-300 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <form onSubmit={create} className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6 space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="Co připomenout (např. fyzio)"
            aria-label="Text připomínky"
            className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
          />
          <select
            value={form.mode}
            onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value as ReminderForm["mode"] }))}
            aria-label="Opakování"
            className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
          >
            <option value="once">Jednorázově</option>
            <option value="daily">Denně</option>
            <option value="weekly">Každý týden</option>
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {form.mode === "once" ? (
            <input
              type="datetime-local"
              value={form.dueLocal}
              onChange={(e) => setForm((f) => ({ ...f, dueLocal: e.target.value }))}
              aria-label="Kdy (Praha)"
              className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
            />
          ) : (
            <input
              type="time"
              value={form.timeLocal}
              onChange={(e) => setForm((f) => ({ ...f, timeLocal: e.target.value }))}
              aria-label="Čas (Praha)"
              className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
            />
          )}
          {form.mode === "weekly" && (
            <div className="flex gap-1.5" role="group" aria-label="Dny v týdnu">
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
                    className={`motion-press h-9 w-9 rounded-lg border text-sm ${
                      on ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-100" : "border-zinc-700 bg-zinc-800"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}
          <input
            value={form.note}
            onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
            placeholder="Poznámka (nepovinné)"
            aria-label="Poznámka"
            className="flex-1 min-w-[180px] bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
          />
          <button
            type="submit"
            disabled={saving}
            className="motion-press rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 px-4 py-2.5 font-medium text-white"
          >
            {saving ? "Ukládám…" : "Přidat"}
          </button>
        </div>
      </form>

      {loading ? (
        <div className="text-zinc-500">Načítám…</div>
      ) : (
        <>
          {groups.due.length > 0 && (
            <section className="space-y-3" aria-live="polite">
              <h2 className="text-lg font-semibold text-amber-200">Teď ({groups.due.length})</h2>
              {groups.due.map(renderCard)}
            </section>
          )}
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">Nadcházející</h2>
            {groups.upcoming.length ? (
              groups.upcoming.map(renderCard)
            ) : (
              <div className="text-zinc-500 text-sm">Žádné naplánované připomínky.</div>
            )}
          </section>
          <section className="space-y-3">
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              className="motion-press text-sm text-zinc-400 hover:text-zinc-200"
            >
              {showHistory ? "Skrýt hotové a zrušené" : "Zobrazit hotové a zrušené"}
            </button>
            {showHistory && groups.history.map(renderCard)}
          </section>
        </>
      )}

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Zrušit připomínku?"
        message={cancelTarget ? `${cancelTarget.title} · ${cancelTarget.recurrence_label}` : undefined}
        confirmLabel="Zrušit připomínku"
        cancelLabel="Ponechat"
        onConfirm={() => {
          const target = cancelTarget;
          setCancelTarget(null);
          if (target) void act(target.id, `/reminders/${target.id}/cancel`);
        }}
        onCancel={() => setCancelTarget(null)}
      />
    </main>
  );
}
