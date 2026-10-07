"use client";

import Image from "next/image";
import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui";
import { useModal } from "@/components/ui/useModal";
import { apiUrl } from "@/lib/api";
import { cx } from "@/lib/ui";
import { galleryStep, type MilestoneScreenshot } from "@/lib/wot";

const MAX_THUMBS = 4;

/** Obrázek screenshotu s náhradou při chybě (smazaný soubor, výpadek) – nikdy rozbitá ikona. */
function Shot({ shot, alt, mode }: { shot: MilestoneScreenshot; alt: string; mode: "thumb" | "full" }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span data-shot-state="missing" className="flex h-full w-full items-center justify-center bg-surface-2 px-2 text-center text-xs text-ink-muted">
        Obrázek se nepodařilo načíst
      </span>
    );
  }
  return (
    <Image
      src={apiUrl(shot.url)}
      alt={alt}
      fill
      unoptimized
      loading={mode === "thumb" ? "lazy" : "eager"}
      sizes={mode === "thumb" ? "(max-width: 640px) 45vw, 180px" : "100vw"}
      onError={() => setFailed(true)}
      className={mode === "thumb" ? "object-cover" : "object-contain"}
      data-shot-state="image"
    />
  );
}

/** Galerie screenshotů milníku: náhledy 16:9 (líně), klik = zvětšení v dialogu se šipkami. Bez screenshotů nic. */
export function MilestoneGallery({ shots, tank }: { shots: MilestoneScreenshot[]; tank: string }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!shots.length) return null;
  const visible = shots.slice(0, MAX_THUMBS);
  const extra = shots.length - visible.length;
  const label = (s: MilestoneScreenshot, i: number) => `Screenshot ${i + 1} z ${shots.length} – ${s.caption || tank}`;
  return (
    <>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label={`Screenshoty: ${tank}`}>
        {visible.map((s, i) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => setOpen(i)}
              aria-label={`Zvětšit: ${label(s, i)}`}
              data-shot={s.id}
              className="group relative block aspect-video w-full overflow-hidden rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              <Shot shot={s} alt="" mode="thumb" />
              {i === visible.length - 1 && extra > 0 ? (
                <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-sm font-semibold text-ink">+{extra}</span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
      {open !== null ? <Lightbox shots={shots} index={open} tank={tank} onIndex={setOpen} onClose={() => setOpen(null)} /> : null}
    </>
  );
}

function Lightbox({
  shots,
  index,
  tank,
  onIndex,
  onClose,
}: {
  shots: MilestoneScreenshot[];
  index: number;
  tank: string;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  useModal({ open: true, panelRef, initialFocus: () => closeRef.current, onClose });
  const shot = shots[index];
  const many = shots.length > 1;
  const step = (dir: 1 | -1) => onIndex(galleryStep(index, shots.length, dir));
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-2 sm:p-6"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="shot-lightbox"
        onKeyDown={(e) => {
          if (!many) return;
          if (e.key === "ArrowRight") step(1);
          if (e.key === "ArrowLeft") step(-1);
        }}
        className="motion-palette flex max-h-full w-full max-w-5xl flex-col gap-2 focus:outline-none"
      >
        <div className="flex items-center justify-between gap-2">
          <h2 id={titleId} className="min-w-0 truncate text-sm font-medium text-ink">
            {tank} · {index + 1} / {shots.length}
          </h2>
          <Button ref={closeRef} size="sm" variant="secondary" onClick={onClose} aria-label="Zavřít náhled">
            Zavřít
          </Button>
        </div>
        <div className="relative h-[70dvh] w-full overflow-hidden rounded-[var(--radius-control)] bg-black sm:h-[75dvh]">
          <Shot key={shot.id} shot={shot} alt={shot.caption || `Screenshot bitvy: ${tank}`} mode="full" />
        </div>
        <div className={cx("flex items-center gap-2", many ? "justify-between" : "justify-center")}>
          {many ? (
            <Button size="md" variant="secondary" onClick={() => step(-1)} aria-label="Předchozí screenshot" className="min-w-11">
              ←
            </Button>
          ) : null}
          <p className="min-w-0 flex-1 text-center text-sm text-ink-2">{shot.caption || shot.original_name || ""}</p>
          {many ? (
            <Button size="md" variant="secondary" onClick={() => step(1)} aria-label="Další screenshot" className="min-w-11">
              →
            </Button>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}
