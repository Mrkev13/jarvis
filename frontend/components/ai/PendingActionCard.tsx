import { AreaBadge, Button, StatusBadge } from "@/components/ui";
import { describeAction } from "@/lib/aiActions";
import type { PendingAction } from "@/lib/pendingActions";
import { cx } from "@/lib/ui";

/**
 * Akce navržená AI čekající na potvrzení (Roadmap 4C). Ukazuje, co se změní: druh změny, oblast, cílový
 * záznam, staré → nové hodnoty, počet záznamů a upozornění. Potvrzení / zamítnutí beze změny sémantiky
 * (POST /actions/confirm, /ai/reject/{id}); karta je sama o sobě potvrzovacím krokem.
 */
export function PendingActionCard({
  action,
  state,
  onConfirm,
  onReject,
}: {
  action: PendingAction;
  state: "pending" | "executing" | "failed";
  onConfirm: () => void;
  onReject: () => void;
}) {
  const v = describeAction(action);
  const titleId = `pa-${action.id}-title`;
  const statusText =
    state === "executing" ? "Provádím změnu…" : state === "failed" ? "Provedení selhalo – můžeš zkusit znovu." : "Čeká na tvé potvrzení";
  return (
    <li
      aria-labelledby={titleId}
      aria-busy={state === "executing" || undefined}
      className={cx(
        "motion-card relative overflow-hidden rounded-card border bg-surface shadow-card",
        state === "failed" ? "motion-shake border-danger/50" : state === "executing" ? "motion-executing border-accent/40" : "border-accent/30",
      )}
    >
      <div aria-hidden="true" className="h-px bg-gradient-to-r from-transparent via-accent/70 to-transparent" />
      <div className="p-4 md:p-5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            role="status"
            className={cx(
              "mr-1 font-mono text-[11px] uppercase tracking-[0.16em]",
              state === "failed" ? "text-danger" : state === "executing" ? "text-accent-strong" : "text-ink-muted",
            )}
          >
            {statusText}
          </span>
          <StatusBadge tone={v.kindTone}>{v.kindLabel}</StatusBadge>
          {v.area ? <AreaBadge area={v.area} /> : null}
          {v.count > 1 ? <StatusBadge>{v.count} záznamů</StatusBadge> : null}
        </div>
        <h3 id={titleId} className="mt-2 break-words text-base font-semibold text-ink">
          {v.title}
        </h3>

        {v.fields.length ? (
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
            {v.fields.map((f, i) => (
              <div key={`${f.label}-${i}`} className={cx("flex min-w-0 justify-between gap-3 border-b border-line-subtle pb-1.5", f.value.length > 28 && "sm:col-span-2")}>
                <dt className="shrink-0 text-ink-muted">{f.label}</dt>
                <dd className="min-w-0 break-words text-right font-medium text-ink">{f.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}

        {v.items.length ? (
          <ol className="mt-3 space-y-2" aria-label="Dotčené záznamy">
            {v.items.map((item, i) => (
              <li key={i} className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-3 py-2 text-sm">
                <div className="break-words font-medium text-ink">{item.label}</div>
                {item.changes.length ? (
                  <dl className="mt-1 space-y-0.5">
                    {item.changes.map((c, j) => (
                      <div key={j} className="flex flex-wrap gap-x-2 text-ink-2">
                        <dt className="text-ink-muted">{c.label}:</dt>
                        <dd className="min-w-0 break-words">
                          <span className="text-ink-muted line-through decoration-ink-faint">{c.old || "–"}</span>
                          <span aria-hidden="true" className="mx-1.5 text-ink-faint">→</span>
                          <span className="sr-only"> změní se na </span>
                          <span className="font-medium text-ink">{c.new || "–"}</span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </li>
            ))}
            {v.hiddenItems > 0 ? <li className="px-1 text-xs text-ink-muted">a dalších {v.hiddenItems}</li> : null}
          </ol>
        ) : null}

        {v.warnings.length ? (
          <ul className="mt-3 space-y-1 rounded-[var(--radius-control)] border border-warning/35 bg-warning/[0.06] px-3 py-2 text-sm text-ink-2">
            {v.warnings.map((w, i) => (
              <li key={i}>
                <span aria-hidden="true" className="mr-1.5 text-warning">!</span>
                {w}
              </li>
            ))}
          </ul>
        ) : null}

        {v.footer ? (
          <div className="mt-3 flex items-baseline justify-between gap-3 rounded-[var(--radius-control)] bg-surface-2 px-3 py-2">
            <span className="text-sm text-ink-muted">{v.footer.label}</span>
            <span className="text-lg font-semibold tabular-nums text-ink">{v.footer.value}</span>
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="primary"
            className="flex-1 sm:flex-none"
            busy={state === "executing"}
            busyLabel="Provádím…"
            onClick={onConfirm}
            aria-describedby={titleId}
          >
            {state === "failed" ? "Zkusit znovu" : "Potvrdit"}
          </Button>
          <Button variant="secondary" className="flex-1 sm:flex-none" disabled={state === "executing"} onClick={onReject} aria-describedby={titleId}>
            Zamítnout
          </Button>
        </div>
      </div>
    </li>
  );
}
