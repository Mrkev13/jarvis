"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Card, EmptyState, ErrorState, LoadingState, StatusBadge, fieldClass } from "@/components/ui";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import {
  CREDIT_OPTIONS,
  absenceTone,
  creditTone,
  examsSummary,
  parseAbsenceLimit,
  shortDate,
  weekLabel,
  weekState,
  type CreditStatus,
  type ProgressPayload,
  type SubjectProgress,
} from "@/lib/schoolProgress";
import { cx } from "@/lib/ui";

/**
 * MRK-86: zápočty a docházka – u každého aktivního předmětu stav zápočtu, souhrn zkoušek, docházka „byl X z Y"
 * a absence proti limitu. Tento týden se zapisuje jedním klepnutím (Byl / Nebyl), minulý týden jde opravit.
 * Všechno počítá backend (GET /school/progress); tady jen zobrazení a zápisy.
 */
export function ProgressPanel({ reloadKey }: { reloadKey?: unknown }) {
  const [data, setData] = useState<ProgressPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiJson<ProgressPayload>("/school/progress"));
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e, "Zápočty a docházku se nepodařilo načíst."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load, reloadKey]);

  async function write(subject: SubjectProgress, key: string, path: string, init: RequestInit, done: string) {
    setBusy(`${subject.id}:${key}`);
    setErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => Number(id) !== subject.id)));
    try {
      const updated = await apiJson<SubjectProgress>(path, init);
      setData((prev) => (prev ? { ...prev, subjects: prev.subjects.map((s) => (s.id === updated.id ? updated : s)) } : prev));
      setNotice(done);
    } catch (e) {
      setErrors((prev) => ({ ...prev, [subject.id]: errorMessage(e, "Uložení se nepodařilo – zkus to znovu.") }));
    } finally {
      setBusy(null);
    }
  }

  function attend(subject: SubjectProgress, week: string, present: boolean | null) {
    const word = present === null ? "nezapsáno" : present ? "byl" : "nebyl";
    void write(subject, `week:${week}`, `/school/subject/${subject.id}/attendance`, jsonBody("PUT", { week_start: week, present }),
      `${subject.name}, ${weekLabel(week)}: ${word}.`);
  }

  function setCredit(subject: SubjectProgress, status: CreditStatus) {
    const label = CREDIT_OPTIONS.find((o) => o.value === status)?.label.toLowerCase() ?? status;
    void write(subject, "credit", `/school/subject/${subject.id}/credit`, jsonBody("PUT", { status }), `${subject.name}: zápočet ${label}.`);
  }

  async function setLimit(subject: SubjectProgress, text: string) {
    const limit = parseAbsenceLimit(text);
    if (limit === "invalid") {
      setErrors((prev) => ({ ...prev, [subject.id]: "Limit absencí musí být celé číslo 0–52 (prázdné = bez limitu)." }));
      return;
    }
    setBusy(`${subject.id}:limit`);
    try {
      await apiJson(`/school/subject/${subject.id}`, jsonBody("PATCH", { absence_limit: limit }));
      await load();
      setNotice(limit === null ? `${subject.name}: bez limitu absencí.` : `${subject.name}: limit ${limit} absencí.`);
    } catch (e) {
      setErrors((prev) => ({ ...prev, [subject.id]: errorMessage(e, "Limit se nepodařilo uložit.") }));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !data) return <LoadingState lines={3} label="Načítám zápočty a docházku…" />;
  if (loadError && !data) return <ErrorState message={loadError} onRetry={() => void load()} retrying={loading} />;
  if (!data) return null;
  if (!data.subjects.length) return <EmptyState compact>Žádný aktivní předmět – přidej ho v sekci Předměty.</EmptyState>;

  return (
    <div className="space-y-3">
      <p role="status" aria-live="polite" className="min-h-5 text-sm text-success">
        {notice}
      </p>
      <ul aria-label="Zápočty a docházka" className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {data.subjects.map((s) => (
          <SubjectCard
            key={s.id}
            subject={s}
            week={data.week_start}
            previousWeek={data.previous_week_start}
            busy={busy}
            error={errors[s.id] ?? null}
            onAttend={attend}
            onCredit={setCredit}
            onLimit={setLimit}
          />
        ))}
      </ul>
    </div>
  );
}

function WeekButtons({
  subject,
  week,
  label,
  busy,
  onAttend,
  primary,
}: {
  subject: SubjectProgress;
  week: string;
  label: string;
  busy: string | null;
  onAttend: (s: SubjectProgress, week: string, present: boolean | null) => void;
  primary?: boolean;
}) {
  const state = weekState(subject, week);
  const working = busy === `${subject.id}:week:${week}`;
  const option = (present: boolean) => {
    const pressed = state === present;
    return (
      <Button
        size="sm"
        variant={pressed ? (present ? "success" : "danger") : "secondary"}
        aria-pressed={pressed}
        aria-label={`${present ? "Byl" : "Nebyl"} – ${subject.name}, ${label}`}
        disabled={busy !== null}
        busy={working}
        // druhé klepnutí na zvolený stav záznam smaže (překlep jde vrátit)
        onClick={() => onAttend(subject, week, pressed ? null : present)}
        className={cx("min-h-11 min-w-20 flex-1", pressed && "font-semibold")}
        data-week-action={primary ? "current" : "previous"}
      >
        {present ? "Byl" : "Nebyl"}
      </Button>
    );
  };
  return (
    <div className="space-y-1">
      <p className="text-xs text-ink-muted">
        {label} <span className="tabular-nums">(od {shortDate(week)})</span>
        {state === null ? " · nezapsáno" : null}
      </p>
      <div className="flex gap-2">
        {option(true)}
        {option(false)}
      </div>
    </div>
  );
}

function SubjectCard({
  subject: s,
  week,
  previousWeek,
  busy,
  error,
  onAttend,
  onCredit,
  onLimit,
}: {
  subject: SubjectProgress;
  week: string;
  previousWeek: string;
  busy: string | null;
  error: string | null;
  onAttend: (s: SubjectProgress, week: string, present: boolean | null) => void;
  onCredit: (s: SubjectProgress, status: CreditStatus) => void;
  onLimit: (s: SubjectProgress, text: string) => Promise<void>;
}) {
  const [limitText, setLimitText] = useState(s.attendance.limit === null ? "" : String(s.attendance.limit));
  const exams = examsSummary(s.exams);
  const tone = absenceTone(s.attendance);
  return (
    <Card as="li" inset className="min-w-0 space-y-3" data-progress-subject={s.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 break-words text-sm font-semibold text-ink">{s.name}</h3>
        <StatusBadge tone={creditTone(s.credit.status)}>
          Zápočet {s.credit.label}
          {s.credit.date ? ` · ${shortDate(s.credit.date)}` : ""}
        </StatusBadge>
      </div>

      <div className={cx("rounded-[var(--radius-control)] border px-3 py-2 text-sm",
        tone === "danger" ? "border-danger/40 bg-danger/10" : tone === "warning" ? "border-warning/40 bg-warning/10" : "border-line-subtle bg-surface-2")}
      >
        <p className="text-ink-2">
          <span className="font-medium text-ink">Docházka:</span> {s.attendance.text}
        </p>
        {s.attendance.warning ? (
          <p className={cx("mt-1 text-xs font-medium", tone === "danger" ? "text-danger" : "text-warning")}>{s.attendance.warning}</p>
        ) : null}
      </div>

      <WeekButtons subject={s} week={week} label="Tento týden" busy={busy} onAttend={onAttend} primary />
      <WeekButtons subject={s} week={previousWeek} label="Minulý týden" busy={busy} onAttend={onAttend} />

      {exams ? (
        <div className="text-xs text-ink-muted">
          <p>{exams}</p>
          {s.exams.results.length ? (
            <ul className="mt-1 space-y-0.5" aria-label={`Výsledky zkoušek – ${s.name}`}>
              {s.exams.results.map((r) => (
                <li key={r.id} className="break-words">
                  {r.title}: <span className="text-ink-2">{r.result ?? r.outcome_label}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-ink-muted">
          Zápočet
          <select
            className={cx(fieldClass, "min-h-11")}
            value={s.credit.status}
            disabled={busy !== null}
            onChange={(e) => onCredit(s, e.target.value as CreditStatus)}
            aria-label={`Stav zápočtu – ${s.name}`}
          >
            {CREDIT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void onLimit(s, limitText);
          }}
        >
          <label className="flex w-24 flex-col gap-1 text-xs text-ink-muted">
            Limit absencí
            <input
              className={cx(fieldClass, "min-h-11")}
              inputMode="numeric"
              value={limitText}
              placeholder="bez"
              onChange={(e) => setLimitText(e.target.value)}
              aria-label={`Limit absencí – ${s.name}`}
            />
          </label>
          <Button type="submit" size="sm" className="min-h-11" disabled={busy !== null} busy={busy === `${s.id}:limit`}>
            Uložit
          </Button>
        </form>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </Card>
  );
}
