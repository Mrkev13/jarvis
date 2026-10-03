"use client";

import { useId, useRef } from "react";
import { createPortal } from "react-dom";
import { cx } from "@/lib/ui";
import { useModal } from "./useModal";

/**
 * Boční panel (Roadmap 4B): mobilní menu a panel notifikací.
 * role="dialog" + aria-modal, past na fokus, Escape, klik mimo zavře, návrat fokusu na otvírač,
 * vjezd zprava (při omezeném pohybu bez animace). Obsah si skládá volající; hlavička je volitelná.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  actions,
  children,
  width = "md",
  restoreFocus = true,
  initialFocus,
  className,
}: {
  open: boolean;
  onClose: () => void;
  /** Název panelu (aria-labelledby). */
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Akce v hlavičce vedle tlačítka Zavřít. */
  actions?: React.ReactNode;
  children: React.ReactNode;
  width?: "sm" | "md";
  restoreFocus?: boolean;
  initialFocus?: () => HTMLElement | null | undefined;
  className?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useModal({ open, panelRef, onClose, restoreFocus, initialFocus });

  if (!open) return null;
  // Portál do <body>: předek s transform/backdrop-filter (sticky hlavička, přechod stránky)
  // by jinak omezil position: fixed jen na svůj rámeček.
  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target !== e.currentTarget) return;
        e.preventDefault(); // fokus se vrátí na otvírač, ne na <body>
        onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cx(
          "motion-drawer absolute right-0 top-0 flex h-full w-full flex-col border-l border-line bg-app shadow-[var(--shadow-elevated)] focus:outline-none",
          width === "sm" ? "max-w-[min(20rem,88vw)]" : "max-w-[min(30rem,100vw)]",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-ink">
              {title}
            </h2>
            {description ? (
              <div id={descId} className="mt-0.5 text-xs text-ink-muted">
                {description}
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {actions}
            <button
              type="button"
              aria-label="Zavřít"
              onClick={onClose}
              className="grid h-10 w-10 place-items-center rounded-lg text-xl text-ink-2 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              ×
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
