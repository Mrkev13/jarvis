"use client";

import { useId, useRef, useState } from "react";
import { isPromiseLike } from "@/lib/dialog";
import { cx } from "@/lib/ui";
import { Button } from "./Button";
import { useModal } from "./useModal";

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  message?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Text tlačítka během odesílání. */
  busyLabel?: string;
  /** Destruktivní akce (červené potvrzení, výchozí fokus na Zrušit). Výchozí true kvůli zpětné kompatibilitě. */
  danger?: boolean;
  /** Vnější busy stav (např. stránka sama čeká na API). */
  busy?: boolean;
  /**
   * Potvrzení. Vrátí-li Promise, dialog zůstane otevřený v busy stavu (bez dvojího odeslání, Escape a klik
   * mimo nic neudělají) a zavře se až voláním onCancel/změnou `open` od stránky.
   */
  onConfirm: () => void | Promise<unknown>;
  onCancel: () => void;
};

/**
 * Potvrzovací dialog (Roadmap 4A): role="dialog", aria-modal, past na fokus, Escape, busy stav,
 * obnovení fokusu po zavření, sdílený zámek scrollu, omezený pohyb přes motion-* třídy.
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Smazat",
  cancelLabel = "Zrušit",
  busyLabel = "Probíhá…",
  danger = true,
  busy: externalBusy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [internalBusy, setInternalBusy] = useState(false);
  const busy = externalBusy || internalBusy;
  const panelRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const messageId = useId();
  useModal({
    open,
    panelRef,
    // Destruktivní akce: výchozí fokus na bezpečné „Zrušit".
    initialFocus: () => (danger ? cancelRef.current : confirmRef.current),
    onClose: onCancel,
    busy,
  });

  if (!open) return null;

  async function confirm() {
    if (busy) return;
    const result = onConfirm();
    if (!isPromiseLike(result)) return;
    setInternalBusy(true);
    try {
      await result;
    } finally {
      setInternalBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target !== e.currentTarget) return;
        // Bez preventDefault by výchozí akce mousedown přesunula fokus na <body> až po obnovení fokusu.
        e.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={message ? messageId : undefined}
        aria-busy={busy || undefined}
        className="motion-card w-full max-w-md rounded-card border border-line bg-elevated p-5 md:p-6 shadow-[var(--shadow-elevated)]"
      >
        <h2 id={titleId} className="text-lg font-semibold text-ink">
          {title}
        </h2>
        {message ? (
          <div id={messageId} className="mt-2 text-sm leading-relaxed text-ink-2">
            {message}
          </div>
        ) : null}
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            variant={danger ? "danger" : "primary"}
            onClick={() => void confirm()}
            busy={busy}
            busyLabel={busyLabel}
            className={cx(danger && "bg-danger/10")}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
