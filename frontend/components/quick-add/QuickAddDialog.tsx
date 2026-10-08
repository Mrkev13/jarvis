"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { AreaBadge, Button, ErrorState, FormField, StatusBadge, StatusPulse, fieldClass } from "@/components/ui";
import { useModal } from "@/components/ui/useModal";
import { apiFetch, errorMessage, isAbortError, jsonBody, readErrorDetail } from "@/lib/api";
import { pulseJarvis } from "@/lib/jarvisSignals";
import { confirmActionBody, rejectActionPath, type PendingAction } from "@/lib/pendingActions";
import {
  canAcknowledge, CONFIDENCE_META, FIELD_DEFS, fieldsToForm, formToFields, isQuickAddKind, KIND_AREAS, KIND_HREFS,
  KIND_LABELS, normalizeParse, prepareErrors, QUICK_ADD_EXAMPLES, readiness, type FieldDef, type FormValues,
  type QuickAddIssue, type QuickAddKind, type QuickAddParse,
} from "@/lib/quickAdd";
import { cx } from "@/lib/ui";

const PARSE_DEBOUNCE_MS = 180;

type ParseState =
  | { status: "idle" }
  | { status: "parsing"; previous: QuickAddParse | null }
  | { status: "done"; result: QuickAddParse }
  | { status: "error"; message: string };

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "failed"; message: string }
  | { status: "saved"; kind: QuickAddKind; title: string; subtitle: string };

/**
 * Rychlé přidání (Ctrl+Shift+K / „+"): jedno pole, deterministický náhled, úprava polí a VÝSLOVNÉ „Uložit".
 * Enter v poli jen znovu rozebere text – nikdy neukládá. Zápis jde přes běžnou pending akci + /actions/confirm.
 * Desktop: panel nahoře; mobil: celá obrazovka, pole nahoře, náhled pod ním, tlačítko dole.
 */
export function QuickAddDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return <Dialog onClose={onClose} />;
}

function Dialog({ onClose }: { onClose: () => void }) {
  const ids = { title: useId(), input: useId(), status: useId(), hint: useId() };
  const panelRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [text, setText] = useState("");
  const [parse, setParse] = useState<ParseState>({ status: "idle" });
  const [form, setForm] = useState<FormValues>({});
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  const [serverErrors, setServerErrors] = useState<QuickAddIssue[]>([]);
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  // připravená (nepotvrzená) pending akce: opakované „Uložit" po chybě potvrzuje TUTÉŽ akci, nevytváří novou
  const [pending, setPendingState] = useState<PendingAction | null>(null);
  const pendingRef = useRef<PendingAction | null>(null);
  const setPending = useCallback((action: PendingAction | null) => {
    pendingRef.current = action;
    setPendingState(action);
  }, []);
  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);
  const refocusRef = useRef(false);

  const busy = save.status === "saving";
  useModal({ open: true, panelRef, initialFocus: () => inputRef.current, onClose, busy });

  // Nepotvrzená pending akce (confirm selhal a uživatel zavřel) se zamítne – v systému nezůstane viset.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      const leftover = pendingRef.current;
      if (leftover) void apiFetch(rejectActionPath(leftover), { method: "POST" }).catch(() => undefined);
    },
    [],
  );

  const runParse = useCallback(async (value: string) => {
    abortRef.current?.abort();
    const seq = ++seqRef.current;
    if (value.trim().length < 2) {
      setParse({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setParse((prev) => ({ status: "parsing", previous: prev.status === "done" ? prev.result : prev.status === "parsing" ? prev.previous : null }));
    try {
      const res = await apiFetch("/quick-add/parse", { ...jsonBody("POST", { text: value }), signal: controller.signal });
      if (!res.ok) throw new Error(await readErrorDetail(res));
      const result = normalizeParse(await res.json());
      if (seq !== seqRef.current) return;
      setParse({ status: "done", result });
      setForm(isQuickAddKind(result.kind) ? fieldsToForm(result.kind, result.fields) : {});
      setResolved(new Set());
      setServerErrors([]);
      setSave((s) => (s.status === "failed" ? { status: "idle" } : s));
    } catch (error) {
      if (isAbortError(error) || seq !== seqRef.current) return;
      setParse({ status: "error", message: errorMessage(error, "Rozbor textu se nepodařil.") });
    }
  }, []);

  // rozbor s krátkým zpožděním při psaní
  useEffect(() => {
    const t = window.setTimeout(() => void runParse(text), PARSE_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [text, runParse]);

  const shown: QuickAddParse | null =
    parse.status === "done" ? parse.result : parse.status === "parsing" ? parse.previous : null;
  const kind = shown && isQuickAddKind(shown.kind) ? shown.kind : null;
  const stale = parse.status === "parsing";

  const ready = useMemo(
    () =>
      kind && shown
        ? readiness({ kind, form, questions: shown.needs_input, resolved, errors: [...shown.errors, ...serverErrors] })
        : null,
    [kind, shown, form, resolved, serverErrors],
  );
  const canSave = Boolean(ready?.ready) && !stale && !busy;

  /** Text nebo pole se změnily → připravená akce už neodpovídá náhledu; zamítne se (nic nezapíše). */
  function discardPending() {
    const old = pendingRef.current;
    if (!old) return;
    setPending(null);
    void apiFetch(rejectActionPath(old), { method: "POST" }).catch(() => undefined);
  }

  function edit(key: string, value: string | boolean) {
    discardPending();
    setForm((f) => ({ ...f, [key]: value }));
    setResolved((r) => new Set(r).add(key));
    setServerErrors((errs) => errs.filter((e) => e.field !== key));
  }

  function acknowledge(field: string) {
    setResolved((r) => new Set(r).add(field));
  }

  async function confirm(action: PendingAction): Promise<boolean> {
    const res = await apiFetch("/actions/confirm", jsonBody("POST", confirmActionBody(action)));
    if (!res.ok) throw new Error(await readErrorDetail(res));
    const body = (await res.json()) as { ok?: boolean; error?: string; detail?: string };
    if (body.ok) return true;
    if (body.error === "action_already_processed" || body.error === "action_not_found_or_expired") setPending(null);
    throw new Error(
      body.error === "action_already_processed"
        ? "Tenhle záznam už byl zpracován – zkontroluj ho na stránce oblasti."
        : body.error === "action_not_found_or_expired"
          ? "Příprava vypršela – ulož to prosím znovu."
          : body.detail || "Uložení se nepodařilo.",
    );
  }

  async function submit() {
    if (!kind || !shown || !canSave) return;
    setSave({ status: "saving" });
    try {
      let action = pendingRef.current;
      if (!action) {
        const res = await apiFetch("/quick-add/prepare", jsonBody("POST", { kind, fields: formToFields(kind, form) }));
        if (res.status === 422) {
          const errors = prepareErrors(await res.json().catch(() => null));
          setServerErrors(errors.map((e) => ({ ...e })));
          setResolved((r) => {
            const next = new Set(r);
            for (const e of errors) next.delete(e.field);
            return next;
          });
          setSave({ status: "failed", message: errors[0]?.message ?? "Údaje neprošly kontrolou." });
          return;
        }
        if (!res.ok) throw new Error(await readErrorDetail(res));
        action = ((await res.json()) as { pending_action: PendingAction }).pending_action;
        setPending(action);
      }
      await confirm(action);
      setPending(null);
      setSave({ status: "saved", kind, title: summaryTitle(kind, form), subtitle: KIND_LABELS[kind] });
      pulseJarvis("success");
    } catch (error) {
      setSave({ status: "failed", message: errorMessage(error, "Uložení se nepodařilo.") });
      pulseJarvis("error");
    }
  }

  function again() {
    setSave({ status: "idle" });
    setText("");
    setParse({ status: "idle" });
    setForm({});
    refocusRef.current = true;
  }

  // po „Přidat další" vrátit fokus do pole, až bude znovu povolené (po vykreslení)
  useEffect(() => {
    if (save.status === "idle" && refocusRef.current) {
      refocusRef.current = false;
      inputRef.current?.focus();
    }
  }, [save.status]);

  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      // Enter nikdy neukládá – jen hned rozebere text (bez čekání na debounce).
      e.preventDefault();
      void runParse(text);
    }
  }

  const statusText =
    save.status === "saved"
      ? "Uloženo."
      : parse.status === "parsing"
        ? "Rozebírám…"
        : shown?.kind === "unknown"
          ? "Tomu zatím nerozumím."
          : kind && ready && !ready.ready
            ? ready.blockers[0]
            : kind
              ? "Připraveno k uložení."
              : "";

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm sm:px-4"
      onMouseDown={(e) => {
        if (e.target !== e.currentTarget || busy) return;
        e.preventDefault();
        onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={ids.title}
        data-testid="quick-add"
        className={cx(
          "motion-palette relative flex h-dvh w-full flex-col overflow-hidden bg-elevated focus:outline-none",
          "sm:mx-auto sm:mt-[10vh] sm:h-auto sm:max-h-[min(40rem,82vh)] sm:max-w-xl sm:rounded-card sm:border sm:border-line sm:shadow-[var(--shadow-elevated)]",
        )}
      >
        <div aria-hidden="true" className="h-px bg-gradient-to-r from-transparent via-accent/60 to-transparent" />
        <div className="flex items-center justify-between gap-2 px-4 pt-3">
          <h2 id={ids.title} className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink-muted">
            Rychlé přidání
          </h2>
          <kbd className="hidden rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-ink-muted sm:inline">Esc</kbd>
          <Button size="sm" variant="ghost" className="sm:hidden" onClick={onClose} disabled={busy}>
            Zavřít
          </Button>
        </div>
        <div className="flex items-center gap-2 border-b border-line px-4 pb-2">
          <span aria-hidden="true" className="text-lg font-semibold text-accent">+</span>
          <label htmlFor={ids.input} className="sr-only">
            Co chceš přidat?
          </label>
          <input
            id={ids.input}
            ref={inputRef}
            type="text"
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="go"
            maxLength={300}
            value={text}
            disabled={busy || save.status === "saved"}
            placeholder="např. oběd 189,90 Kč · zítra fyzio v 17:00"
            aria-describedby={ids.hint}
            onChange={(e) => {
              setText(e.target.value);
              discardPending();
            }}
            onKeyDown={onInputKeyDown}
            className="min-h-12 min-w-0 flex-1 bg-transparent text-base text-ink placeholder:text-ink-faint focus:outline-none disabled:opacity-60"
          />
          {stale ? <StatusPulse tone="accent" live className="h-2 w-2" /> : null}
        </div>
        <p id={ids.hint} className="sr-only">
          Napiš krátkou větu. Náhled se ukáže pod polem, uloží se až tlačítkem Uložit.
        </p>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3">
          {save.status === "saved" ? (
            <Saved state={save} onAgain={again} onClose={onClose} />
          ) : parse.status === "error" ? (
            <ErrorState message={parse.message} onRetry={() => void runParse(text)} />
          ) : shown?.kind === "unknown" ? (
            <div className="space-y-3">
              <p className="text-sm text-ink" data-testid="quick-add-unknown">
                Tomu zatím nerozumím.
              </p>
              <p className="text-xs text-ink-muted">Umím připomínku, výdaj nebo příjem, odpracované hodiny a školní test nebo úkol. Třeba:</p>
              <Examples onPick={setText} />
            </div>
          ) : kind && shown ? (
            <Preview
              kind={kind}
              result={shown}
              form={form}
              stale={stale}
              ready={ready!}
              onEdit={edit}
              onAcknowledge={acknowledge}
            />
          ) : parse.status === "parsing" ? (
            <p className="text-sm text-ink-muted">Rozebírám…</p>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-ink-2">Napiš, co chceš přidat – připomínku, výdaj, práci nebo školní termín.</p>
              <Examples onPick={setText} />
            </div>
          )}
          {save.status === "failed" ? (
            <div role="alert" className="mt-3 rounded-[var(--radius-control)] border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {save.message}
            </div>
          ) : null}
        </div>

        {save.status !== "saved" ? (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            <span id={ids.status} role="status" aria-live="polite" className="mr-auto min-w-0 flex-1 basis-40 text-xs text-ink-muted">
              {statusText}
            </span>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Zrušit
            </Button>
            <Button
              variant="primary"
              onClick={() => void submit()}
              disabled={!canSave}
              busy={busy}
              busyLabel="Ukládám…"
              aria-describedby={ids.status}
              data-testid="quick-add-save"
            >
              {save.status === "failed" && pending ? "Zkusit znovu" : "Uložit"}
            </Button>
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

function summaryTitle(kind: QuickAddKind, form: FormValues): string {
  const v = (k: string) => String(form[k] ?? "").trim();
  if (kind === "finance") return v("description") || v("category") || (form.transaction_type === "income" ? "Příjem" : "Výdaj");
  if (kind === "work") return v("project") || "Práce";
  return v("title") || KIND_LABELS[kind];
}

function Examples({ onPick }: { onPick: (text: string) => void }) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Příklady">
      {QUICK_ADD_EXAMPLES.map((ex) => (
        <li key={ex.text}>
          <button
            type="button"
            onClick={() => onPick(ex.text)}
            className="min-h-9 rounded-full border border-line bg-surface px-3 text-xs text-ink-2 hover:border-ink-faint hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 pointer-coarse:min-h-11"
          >
            {ex.text}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Preview({
  kind,
  result,
  form,
  stale,
  ready,
  onEdit,
  onAcknowledge,
}: {
  kind: QuickAddKind;
  result: QuickAddParse;
  form: FormValues;
  stale: boolean;
  ready: ReturnType<typeof readiness>;
  onEdit: (key: string, value: string | boolean) => void;
  onAcknowledge: (field: string) => void;
}) {
  const conf = CONFIDENCE_META[result.confidence];
  return (
    <section aria-label="Náhled" data-testid="quick-add-preview" data-kind={kind} className={cx("space-y-3 transition-opacity", stale && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <AreaBadge area={KIND_AREAS[kind]} />
        {/* druh jen tam, kde ho oblast neříká sama (Škola → Zkouška / Úkol) */}
        {KIND_AREAS[kind] === "school" ? <StatusBadge tone="neutral">{KIND_LABELS[kind]}</StatusBadge> : null}
        <StatusBadge tone={conf.tone} dot>
          {conf.label}
        </StatusBadge>
      </div>
      <div className="min-w-0">
        <div className="break-words text-base font-semibold text-ink">{result.display.title || KIND_LABELS[kind]}</div>
        {result.display.subtitle ? <div className="break-words text-sm text-ink-muted">{result.display.subtitle}</div> : null}
      </div>

      {ready.openQuestions.length ? (
        <ul className="space-y-2" aria-label="Potřebuju doplnit">
          {ready.openQuestions.map((q) => (
            <li
              key={q.field}
              className="flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-ink"
            >
              <span className="min-w-0 flex-1">{q.question}</span>
              {canAcknowledge(q, form) ? (
                <Button size="sm" variant="secondary" onClick={() => onAcknowledge(q.field)}>
                  Ano
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {result.warnings.length ? (
        <ul className="space-y-1 text-xs text-ink-muted" aria-label="Upozornění">
          {result.warnings.map((w) => (
            <li key={w} className="flex gap-1.5">
              <span aria-hidden="true" className="text-info">
                i
              </span>
              <span className="min-w-0">{w}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {FIELD_DEFS[kind].map((def) => (
          <Field
            key={def.key}
            def={def}
            value={form[def.key]}
            error={ready.fieldErrors[def.key]}
            subjects={result.subjects ?? []}
            onChange={(v) => onEdit(def.key, v)}
          />
        ))}
      </div>
    </section>
  );
}

function Field({
  def,
  value,
  error,
  subjects,
  onChange,
}: {
  def: FieldDef;
  value: string | boolean | undefined;
  error?: string;
  subjects: { id: number; name: string }[];
  onChange: (value: string | boolean) => void;
}) {
  if (def.type === "checkbox") {
    return (
      <label className="flex min-h-10 items-center gap-2 text-sm text-ink-2 sm:col-span-2">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
        {def.label}
      </label>
    );
  }
  const str = typeof value === "string" ? value : "";
  const label = def.suffix ? `${def.label} (${def.suffix})` : def.label;
  return (
    <FormField label={def.required ? `${label} *` : label} error={error} className={def.type === "datetime" || def.key === "title" ? "sm:col-span-2" : undefined}>
      {(props) =>
        def.type === "select" ? (
          <select {...props} value={str} onChange={(e) => onChange(e.target.value)} className={fieldClass}>
            {def.options!.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        ) : def.type === "subject" ? (
          <select {...props} value={str} onChange={(e) => onChange(e.target.value)} className={fieldClass}>
            <option value="">Vyber předmět…</option>
            {subjects.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.name}
              </option>
            ))}
          </select>
        ) : (
          <input
            {...props}
            type={def.type === "date" ? "date" : def.type === "datetime" ? "datetime-local" : "text"}
            inputMode={def.type === "number" ? "decimal" : undefined}
            value={str}
            onChange={(e) => onChange(e.target.value)}
            className={fieldClass}
          />
        )
      }
    </FormField>
  );
}

function Saved({ state, onAgain, onClose }: { state: Extract<SaveState, { status: "saved" }>; onAgain: () => void; onClose: () => void }) {
  const againRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => againRef.current?.focus(), []);
  return (
    <div role="status" data-testid="quick-add-saved" className="space-y-3 rounded-card border border-success/35 bg-success/10 p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <AreaBadge area={KIND_AREAS[state.kind]} />
        <StatusBadge tone="success" dot>
          Uloženo
        </StatusBadge>
      </div>
      <div>
        <div className="break-words text-base font-semibold text-ink">{state.title}</div>
        <div className="text-xs text-ink-muted">{state.subtitle} · v Aktivitě jako „Rychlé přidání“</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button ref={againRef} variant="primary" size="sm" onClick={onAgain}>
          Přidat další
        </Button>
        <Link
          href={KIND_HREFS[state.kind]}
          onClick={onClose}
          className="inline-flex min-h-9 items-center rounded-[var(--radius-control)] px-3 text-sm text-accent-strong hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 pointer-coarse:min-h-11"
        >
          Otevřít {areaTarget(state.kind)}
        </Link>
      </div>
    </div>
  );
}

function areaTarget(kind: QuickAddKind): string {
  return { reminder: "Připomínky", finance: "Finance", work: "Práci", exam: "Školu", assignment: "Školu" }[kind];
}
