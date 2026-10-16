"use client";

import Image from "next/image";
import { createPortal } from "react-dom";
import { useId, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { useModal } from "@/components/ui/useModal";

export function CharlieMemorialButton({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      title="Charlie"
      aria-label="Charlie"
      aria-haspopup="dialog"
      onClick={onOpen}
      className="grid h-9 w-9 place-items-center rounded-lg text-ink-muted/45 transition-colors hover:bg-surface hover:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
    >
      <Icon name="paw" size="sm" />
    </button>
  );
}

export function CharlieMemorialPanel({
  onClose,
  panelRef,
  closeRef,
  titleId = "charlie-memorial-title",
  descriptionId = "charlie-memorial-description",
}: {
  onClose: () => void;
  panelRef: React.RefObject<HTMLDivElement | null>;
  closeRef?: React.RefObject<HTMLButtonElement | null>;
  titleId?: string;
  descriptionId?: string;
}) {
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-line bg-elevated shadow-[var(--shadow-elevated)] focus:outline-none"
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <h2 id={titleId} className="text-base font-semibold text-ink">Charlie</h2>
          <button
            ref={closeRef}
            type="button"
            aria-label="Zavřít"
            onClick={onClose}
            className="grid h-10 w-10 place-items-center rounded-lg text-xl text-ink-muted hover:bg-surface hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
          >
            ×
          </button>
        </div>
        <div className="p-4 sm:p-5">
          {/* unoptimized: /_next/image fetches the file server-side without the session cookie, the auth proxy
              redirects that to /login and the photo breaks. The browser loads it directly, still behind login. */}
          <Image
            src="/charlie-memorial.jpg"
            unoptimized
            width={1536}
            height={668}
            sizes="(max-width: 768px) calc(100vw - 2rem), 640px"
            alt="Charlie"
            className="max-h-[65vh] h-auto w-full rounded-xl object-contain"
          />
          <p id={descriptionId} className="mt-4 text-center text-sm text-ink-2">Pořád součást Hubu.</p>
        </div>
      </div>
    </div>
  );
}

export function CharlieMemorialDialog({
  open,
  onClose,
  restoreFocus = true,
}: {
  open: boolean;
  onClose: () => void;
  restoreFocus?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useModal({ open, panelRef, initialFocus: () => closeRef.current, onClose, restoreFocus });

  if (!open) return null;
  return createPortal(
    <CharlieMemorialPanel
      onClose={onClose}
      panelRef={panelRef}
      closeRef={closeRef}
      titleId={titleId}
      descriptionId={descriptionId}
    />,
    document.body,
  );
}

export function CharlieMemorial() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <CharlieMemorialButton onOpen={() => setOpen(true)} />
      <CharlieMemorialDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
