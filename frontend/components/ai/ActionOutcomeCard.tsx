import { Button } from "@/components/ui";
import { UNDO_OFFER_MS, type ActionOutcome } from "@/hooks/useAiChat";
import { outcomeMotionClass } from "@/lib/pendingActions";
import { cx } from "@/lib/ui";

/**
 * Výsledek akce AI (Roadmap 4C). „Vrátit" jen když ho backend nabídl (result.undo_available) – po dobu nabídky
 * (20 s) ubývá tenký pruh; pak jde změna vrátit už jen dotazem v chatu („vrať poslední změnu").
 */
export function ActionOutcomeCard({ outcome: o, onUndo }: { outcome: ActionOutcome; onUndo: () => void }) {
  const success = o.kind === "success";
  return (
    <li
      className={cx(
        outcomeMotionClass(o.undoActionId),
        "relative overflow-hidden rounded-[var(--radius-control)] border px-3 py-2.5 text-sm",
        success ? "border-success/35 bg-success/[0.06]" : "border-line bg-surface-2",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span aria-hidden="true" className={success ? "text-success" : "text-ink-muted"}>
          {success ? "✓" : "↩"}
        </span>
        <span className="font-medium text-ink">{success ? "Hotovo" : "Zrušeno"}:</span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{o.title}</span>
        {o.undoActionId ? (
          <Button size="sm" variant="secondary" onClick={onUndo} aria-label={`Vrátit změnu: ${o.title}`}>
            Vrátit
          </Button>
        ) : null}
      </div>
      {o.undoActionId ? (
        <>
          <p className="mt-1 text-xs text-ink-muted">Vrátit jde jen krátce po provedení.</p>
          <div
            aria-hidden="true"
            className="motion-undo-timer absolute inset-x-0 bottom-0 h-0.5 bg-success/60"
            style={{ ["--undo-ms" as string]: `${UNDO_OFFER_MS}ms` }}
          />
        </>
      ) : null}
    </li>
  );
}
