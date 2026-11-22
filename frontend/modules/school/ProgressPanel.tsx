"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Card, EmptyState, ErrorState, LoadingState, StatusBadge, fieldClass } from "@/components/ui";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import {
  CREDIT_OPTIONS,
  SCHEDULE_OPTIONS,
  absenceTone,
  attendanceWeeks,
  creditTone,
  examsSummary,
  parseAbsenceLimit,
  scheduleChoice,
  schedulePatch,
  shortDate,
  weekLabel,
  weekState,
  type CreditStatus,
  type ProgressPayload,
  type ScheduleChoice,
  type SubjectProgress,
} from "@/lib/schoolProgress";
import { cx } from "@/lib/ui";

/**
 * MRK-86: zápočty a docházka – u každého aktivního předmětu stav zápočtu, souhrn zkoušek, docházka „byl X z Y"
 * a absence proti limitu. Tento týden se zapisuje jedním klepnutím (Byl / Nebyl), minulý týden jde opravit.
 * MRK-112: předmět může mít výuku ob týden (nabízí se jen týdny s výukou) a starší týdny jde doplnit v historii.
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

  function clearError(subjectId: number) {
    setErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => Number(id) !== subjectId)));
  }

  async function write(subject: SubjectProgress, key: string, path: string, init: RequestInit, done: string) {
    setBusy(`${subject.id}:${key}`);
    clearError(subject.id);
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
    // stará chyba (neplatný limit, selhání) patří k předchozímu pokusu – před novým zmizí
    clearError(subject.id);
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

  async function setSchedule(subject: SubjectProgress, choice: ScheduleChoice) {
    if (!data) return;
    clearError(subject.id);
    setBusy(`${subject.id}:schedule`);
    try {
      await apiJson(`/school/subject/${subject.id}`, jsonBody("PATCH", schedulePatch(choice, data.week_start, data.previous_week_start)));
      await load();
      setNotice(`${subject.name}: výuka ${SCHEDULE_OPTIONS.find((o) => o.value === choice)?.label.toLowerCase()}.`);
    } catch (e) {
      setErrors((prev) => ({ ...prev, [subject.id]: errorMessage(e, "Rytmus výuky se nepodařilo uložit.") }));
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
            busy={busy}
            error={errors[s.id] ?? null}
            onAttend={attend}
            onCredit={setCredit}
            onLimit={setLimit}
            onSchedule={setSchedule}
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
  dateInLabel,
}: {
  subject: SubjectProgress;
  week: string;
  label: string;
  busy: string | null;
  onAttend: (s: SubjectProgress, week: string, present: boolean | null) => void;
  primary?: boolean;
  /** Starší týdny mají datum už v popisku („týden od 14. 9.") – bez druhého „(od …)". */
  dateInLabel?: boolean;
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
        {label}
        {dateInLabel ? null : <span className="tabular-nums"> (od {shortDate(week)})</span>}
        {state === null ? " · nezapsáno" : null}
      </p>
      <div className="flex gap-2">
        {option(true)}
        {option(false)}
      </div>
    </div>
  );
}

const OLDER_STEP = 8;

function SubjectCard({
  subject: s,
  week,
  busy,
  error,
  onAttend,
  onCredit,
  onLimit,
  onSchedule,
}: {
  subject: SubjectProgress;
  week: string;
  busy: string | null;
  error: string | null;
  onAttend: (s: SubjectProgress, week: string, present: boolean | null) => void;
  onCredit: (s: SubjectProgress, status: CreditStatus) => void;
  onLimit: (s: SubjectProgress, text: string) => Promise<void>;
  onSchedule: (s: SubjectProgress, choice: ScheduleChoice) => Promise<void>;
}) {
  const [limitText, setLimitText] = useState(s.attendance.limit === null ? "" : String(s.attendance.limit));
  const [olderShown, setOlderShown] = useState(OLDER_STEP);
  const exams = examsSummary(s.exams);
  const tone = absenceTone(s.attendance);
  const biweekly = s.schedule.every === 2;
  const weeks = attendanceWeeks(s, week);
  const olderMissing = weeks.older.filter((w) => weekState(s, w) === null).length;
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
          {biweekly ? <span className="text-ink-muted"> · ob týden</span> : null}
        </p>
        {s.attendance.warning ? (
          <p className={cx("mt-1 text-xs font-medium", tone === "danger" ? "text-danger" : "text-warning")}>{s.attendance.warning}</p>
        ) : null}
      </div>

      {weeks.current ? (
        <WeekButtons subject={s} week={weeks.current} label="Tento týden" busy={busy} onAttend={onAttend} primary />
      ) : (
        <p className="text-xs text-ink-muted" data-no-class-week>
          Tento týden <span className="tabular-nums">(od {shortDate(week)})</span> · výuka není
        </p>
      )}
      {weeks.previous ? (
        <WeekButtons subject={s} week={weeks.previous} label={biweekly ? "Minulá výuka" : "Minulý týden"} busy={busy} onAttend={onAttend} />
      ) : null}

      {weeks.older.length ? (
        <details className="group rounded-[var(--radius-control)] border border-line-subtle" data-older-weeks>
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-3 text-sm text-ink-2">
            <span>
              Starší týdny
              {olderMissing ? <span className="text-ink-muted"> · nezapsáno {olderMissing}</span> : null}
            </span>
            <span aria-hidden className="text-ink-muted transition-transform group-open:rotate-180">▾</span>
          </summary>
          <div className="space-y-3 border-t border-line-subtle px-3 py-3">
            {weeks.older.slice(0, olderShown).map((w) => (
              <WeekButtons key={w} subject={s} week={w} label={weekLabel(w)} busy={busy} onAttend={onAttend} dateInLabel />
            ))}
            {weeks.older.length > olderShown ? (
              <Button size="sm" variant="secondary" className="min-h-11 w-full" onClick={() => setOlderShown((n) => n + OLDER_STEP)}>
                Zobrazit starší
              </Button>
            ) : null}
          </div>
        </details>
      ) : null}

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

      <label className="flex min-w-0 flex-col gap-1 text-xs text-ink-muted">
        Výuka
        <select
          className={cx(fieldClass, "min-h-11")}
          value={scheduleChoice(s)}
          disabled={busy !== null}
          onChange={(e) => void onSchedule(s, e.target.value as ScheduleChoice)}
          aria-label={`Rytmus výuky – ${s.name}`}
        >
          {SCHEDULE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

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
