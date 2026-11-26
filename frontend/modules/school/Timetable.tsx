"use client";

import { useState } from "react";
import { Button, Card, CardHeader, EmptyState, ErrorState, FormField, LoadingState, StatusBadge, fieldClass } from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { pragueDayKey } from "@/lib/format";
import { cx } from "@/lib/ui";
import {
  KIND_OPTIONS, WEEKDAYS, byWeekday, draftFrom, draftPayload, emptyDraft, exceptionLabel, nextWeekday, validateDraft,
  type TimetableDraft, type TimetableEntry, type TimetableResponse,
} from "./timetableLib";

type SubjectOption = { id: number; name: string };

/**
 * MRK-41: ruční týdenní rozvrh. Hodiny se zadají jednou za semestr (předmět, den, čas, místnost, druh, platnost)
 * a backend z nich udělá opakované události Kalendáře – Kalendář, denní osa i Dnes je ukážou samy. Jednotlivou
 * hodinu jde zrušit nebo přesunout (výjimka) a zase vrátit podle rozvrhu.
 */
export function Timetable({ subjects }: { subjects: SubjectOption[] }) {
  const res = useApiResource<TimetableResponse>("/calendar/timetable");
  const today = pragueDayKey(new Date());
  const [draft, setDraft] = useState<TimetableDraft>(() => emptyDraft(today, subjects[0] ? String(subjects[0].id) : ""));
  const [editing, setEditing] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exceptionFor, setExceptionFor] = useState<TimetableEntry | null>(null);

  const set = (patch: Partial<TimetableDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const subjectId = draft.subject_id || (subjects[0] ? String(subjects[0].id) : "");

  async function act(key: string, fn: () => Promise<string>) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const msg = await fn();
      await res.reload();
      setNotice(msg);
      return true;
    } catch (err) {
      setError(errorMessage(err, "Akce se nepovedla."));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const d = { ...draft, subject_id: subjectId };
    const invalid = validateDraft(d);
    setFormError(invalid);
    if (invalid) return;
    const ok = await act("save", async () => {
      if (editing != null) {
        await apiJson(`/calendar/timetable/${editing}`, jsonBody("PUT", draftPayload(d)));
        return "Hodina upravena – kalendář se posunul.";
      }
      await apiJson("/calendar/timetable", jsonBody("POST", draftPayload(d)));
      return "Hodina přidána do rozvrhu a kalendáře.";
    });
    if (ok) {
      setEditing(null);
      setDraft((cur) => ({ ...emptyDraft(today, cur.subject_id), valid_from: cur.valid_from, valid_until: cur.valid_until }));
    }
  }

  const entries = res.data?.entries ?? [];
  const days = byWeekday(entries);

  return (
    <div className="space-y-4" data-school-timetable="">
      {error ? <ErrorState message={error} /> : null}
      {notice ? <p role="status" className="text-sm text-ink-2">{notice}</p> : null}

      {res.loading && !res.data ? (
        <LoadingState lines={2} label="Načítám rozvrh…" />
      ) : res.status === "error" ? (
        <ErrorState message="Rozvrh se nepodařilo načíst." onRetry={() => void res.reload()} />
      ) : days.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {days.map((day) => (
            <Card key={day.weekday} as="section" aria-label={`Rozvrh – ${day.label}`} data-timetable-day={day.weekday}>
              <h3 className="font-display text-sm font-semibold uppercase tracking-[0.12em] text-ink-2">{day.label}</h3>
              <ul className="mt-2 divide-y divide-line-subtle">
                {day.entries.map((e) => (
                  <li key={e.id} className="py-2" data-timetable-entry={e.id}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-ink"><span className="tabular-nums">{e.start}–{e.end}</span> · {e.subject_name ?? e.title}</p>
                        <p className="text-xs text-ink-muted">{[e.kind_label, e.room].filter(Boolean).join(" · ")}</p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <Button size="sm" variant="ghost" aria-label={`Upravit: ${e.subject_name ?? e.title} ${day.label} ${e.start}`}
                          onClick={() => { setEditing(e.id); setDraft(draftFrom(e)); setFormError(null); }}>Upravit</Button>
                        <Button size="sm" variant="ghost" aria-label={`Zrušit nebo přesunout jednu hodinu: ${e.subject_name ?? e.title} ${day.label} ${e.start}`}
                          onClick={() => setExceptionFor(e)}>Výjimka</Button>
                      </div>
                    </div>
                    {e.exceptions.length ? (
                      <ul className="mt-1 flex flex-wrap gap-1.5" aria-label="Výjimky">
                        {e.exceptions.map((x) => (
                          <li key={x.date} className="flex items-center gap-1">
                            <StatusBadge tone={x.action === "cancel" ? "warning" : "info"}>{exceptionLabel(x)}</StatusBadge>
                            <Button size="sm" variant="ghost" busy={busy === `clear-${e.id}-${x.date}`} aria-label={`Vrátit podle rozvrhu: ${exceptionLabel(x)}`}
                              onClick={() => void act(`clear-${e.id}-${x.date}`, async () => {
                                await apiJson(`/calendar/timetable/${e.id}/exceptions/${x.date}`, { method: "DELETE" });
                                return "Hodina je zase podle rozvrhu.";
                              })}>Vrátit</Button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState compact>Rozvrh je prázdný. Zadej hodiny jednou za semestr – v kalendáři a v Dnes se pak objeví samy.</EmptyState>
      )}

      {exceptionFor ? (
        <ExceptionForm entry={exceptionFor} today={today} busy={busy === "exception"}
          onCancel={() => setExceptionFor(null)}
          onSubmit={async (body, label) => {
            const ok = await act("exception", async () => {
              await apiJson(`/calendar/timetable/${exceptionFor.id}/exceptions`, jsonBody("POST", body));
              return label;
            });
            if (ok) setExceptionFor(null);
          }} />
      ) : null}

      <Card as="section" aria-labelledby="timetable-form-title" data-timetable-form="">
        <CardHeader as="h3" title={<span id="timetable-form-title">{editing != null ? "Upravit hodinu" : "Přidat hodinu"}</span>}
          description="Jednou za semestr – opakuje se každý týden v zadaném období." />
        {subjects.length === 0 ? (
          <EmptyState compact className="mt-2">Nejdřív přidej předmět.</EmptyState>
        ) : (
          <form onSubmit={save} className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" noValidate>
            <FormField label="Předmět" className="sm:col-span-2">
              {(p) => (
                <select {...p} value={subjectId} onChange={(e) => set({ subject_id: e.target.value })} className={fieldClass}>
                  {subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              )}
            </FormField>
            <FormField label="Druh">
              {(p) => (
                <select {...p} value={draft.kind} onChange={(e) => set({ kind: e.target.value as TimetableDraft["kind"] })} className={fieldClass}>
                  {KIND_OPTIONS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                </select>
              )}
            </FormField>
            <FormField label="Den">
              {(p) => (
                <select {...p} value={draft.weekday} onChange={(e) => set({ weekday: e.target.value })} className={fieldClass}>
                  {WEEKDAYS.map((w, i) => <option key={w} value={i}>{w}</option>)}
                </select>
              )}
            </FormField>
            <FormField label="Od">
              {(p) => <input {...p} type="time" value={draft.start} onChange={(e) => set({ start: e.target.value })} className={fieldClass} />}
            </FormField>
            <FormField label="Do">
              {(p) => <input {...p} type="time" value={draft.end} onChange={(e) => set({ end: e.target.value })} className={fieldClass} />}
            </FormField>
            <FormField label="Místnost" className="sm:col-span-2">
              {(p) => <input {...p} value={draft.room} onChange={(e) => set({ room: e.target.value })} placeholder="např. S5" className={fieldClass} autoComplete="off" />}
            </FormField>
            <FormField label="Platí od">
              {(p) => <input {...p} type="date" value={draft.valid_from} onChange={(e) => set({ valid_from: e.target.value })} className={fieldClass} />}
            </FormField>
            <FormField label="Platí do">
              {(p) => <input {...p} type="date" value={draft.valid_until} onChange={(e) => set({ valid_until: e.target.value })} className={fieldClass} />}
            </FormField>
            {formError ? <p role="alert" className="text-sm text-danger sm:col-span-2 lg:col-span-4">{formError}</p> : null}
            <div className={cx("flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4")}>
              <Button type="submit" variant="primary" busy={busy === "save"} busyLabel="Ukládám…">{editing != null ? "Uložit změnu" : "Přidat do rozvrhu"}</Button>
              {editing != null ? (
                <>
                  <Button type="button" variant="ghost" onClick={() => { setEditing(null); setDraft(emptyDraft(today, subjectId)); }}>Zpět</Button>
                  <Button type="button" variant="ghost" busy={busy === "delete"} onClick={() => void act("delete", async () => {
                    await apiJson(`/calendar/timetable/${editing}`, { method: "DELETE" });
                    setEditing(null);
                    setDraft(emptyDraft(today, subjectId));
                    return "Hodina odebrána z rozvrhu i kalendáře.";
                  })}>Odebrat hodinu</Button>
                </>
              ) : null}
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}

function ExceptionForm({ entry, today, busy, onSubmit, onCancel }: {
  entry: TimetableEntry; today: string; busy: boolean; onCancel: () => void;
  onSubmit: (body: Record<string, string>, label: string) => Promise<void>;
}) {
  const [day, setDay] = useState(() => nextWeekday(today > entry.valid_from ? today : entry.valid_from, entry.weekday));
  const [action, setAction] = useState<"cancel" | "move">("cancel");
  const [newDay, setNewDay] = useState(day);
  const [start, setStart] = useState(entry.start);
  const [end, setEnd] = useState(entry.end);
  const name = entry.subject_name ?? entry.title;
  return (
    <Card as="section" aria-labelledby="timetable-exception-title" data-timetable-exception="">
      <CardHeader as="h3" title={<span id="timetable-exception-title">Výjimka: {name}</span>}
        description={`Jedna hodina (${WEEKDAYS[entry.weekday].toLowerCase()} ${entry.start}) – zbytek rozvrhu zůstane.`} />
      <form className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" noValidate onSubmit={(e) => {
        e.preventDefault();
        const d = (s: string) => `${Number(s.slice(8, 10))}. ${Number(s.slice(5, 7))}.`;
        void onSubmit(action === "cancel" ? { date: day, action } : { date: day, action, new_date: newDay, start, end },
          action === "cancel" ? `Hodina ${d(day)} zrušena.` : `Hodina ${d(day)} přesunuta na ${d(newDay)} ${start}.`);
      }}>
        <FormField label="Která hodina (datum)">
          {(p) => <input {...p} type="date" value={day} onChange={(e) => { setDay(e.target.value); setNewDay(e.target.value); }} className={fieldClass} />}
        </FormField>
        <FormField label="Co s ní">
          {(p) => (
            <select {...p} value={action} onChange={(e) => setAction(e.target.value as "cancel" | "move")} className={fieldClass}>
              <option value="cancel">Odpadá</option>
              <option value="move">Přesunout</option>
            </select>
          )}
        </FormField>
        {action === "move" ? (
          <>
            <FormField label="Nové datum">{(p) => <input {...p} type="date" value={newDay} onChange={(e) => setNewDay(e.target.value)} className={fieldClass} />}</FormField>
            <div className="grid grid-cols-2 gap-2">
              <FormField label="Od">{(p) => <input {...p} type="time" value={start} onChange={(e) => setStart(e.target.value)} className={fieldClass} />}</FormField>
              <FormField label="Do">{(p) => <input {...p} type="time" value={end} onChange={(e) => setEnd(e.target.value)} className={fieldClass} />}</FormField>
            </div>
          </>
        ) : null}
        <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4">
          <Button type="submit" variant="primary" busy={busy} busyLabel="Ukládám…">{action === "cancel" ? "Zrušit hodinu" : "Přesunout hodinu"}</Button>
          <Button type="button" variant="ghost" onClick={onCancel}>Zpět</Button>
        </div>
      </form>
    </Card>
  );
}
