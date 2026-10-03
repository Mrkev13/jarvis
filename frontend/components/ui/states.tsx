import { cx } from "@/lib/ui";
import { Button } from "./Button";

/** Prázdný stav: krátká česká věta, volitelná akce. Žádné obří placeholdery. */
export function EmptyState({
  children,
  action,
  compact,
  className,
}: {
  children: React.ReactNode;
  action?: React.ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "rounded-[var(--radius-control)] border border-dashed border-line text-sm text-ink-muted",
        compact ? "px-3 py-3" : "px-4 py-6 text-center",
        className,
      )}
    >
      <p>{children}</p>
      {action ? <div className={cx("mt-3", !compact && "flex justify-center")}>{action}</div> : null}
    </div>
  );
}

/** Chyba s volitelným „Zkusit znovu". role=alert → čtečka ji ohlásí. */
export function ErrorState({
  message,
  onRetry,
  retrying,
  className,
}: {
  message: React.ReactNode;
  onRetry?: () => void;
  retrying?: boolean;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cx(
        "flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-danger/40 bg-danger/[0.07] px-4 py-3 text-sm text-ink",
        className,
      )}
    >
      <span className="min-w-0">
        <span aria-hidden="true" className="mr-2 text-danger">●</span>
        {message}
      </span>
      {onRetry ? (
        <Button size="sm" variant="secondary" onClick={onRetry} busy={retrying} busyLabel="Načítám…">
          Zkusit znovu
        </Button>
      ) : null}
    </div>
  );
}

/** Šedý blok místo obsahu při prvním načtení (při omezeném pohybu bez pulzu). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("animate-pulse rounded-[var(--radius-control)] bg-surface-2", className)} />;
}

/** Načítání s přístupným textem; `lines` = počet řádků skeletonu. */
export function LoadingState({ lines = 3, label = "Načítám…", className }: { lines?: number; label?: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cx("space-y-2.5", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? "h-5 w-2/3" : "h-14"} />
      ))}
    </div>
  );
}
