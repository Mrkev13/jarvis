"use client";

import { useCompanionPref } from "@/hooks/useJarvisCompanion";
import { cx } from "@/lib/ui";

/** Přepínač Jarvis companiona v postranním panelu (jen desktop ≥ 1024 px, kde companion žije). */
export function JarvisCompanionToggle({ className }: { className?: string }) {
  const { enabled, setEnabled } = useCompanionPref();
  if (enabled === null) return null; // server / před hydratací – preference zatím neznámá
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      data-testid="jarvis-companion-toggle"
      onClick={() => setEnabled(!enabled)}
      className={cx(
        "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm text-ink-muted transition-colors hover:bg-surface hover:text-ink",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
        className,
      )}
    >
      <span>Jarvis companion</span>
      <span
        aria-hidden="true"
        className={cx(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors",
          enabled ? "border-accent/60 bg-accent/25" : "border-line bg-surface-2",
        )}
      >
        <span
          className={cx(
            "absolute h-3.5 w-3.5 rounded-full transition-transform",
            enabled ? "translate-x-[18px] bg-accent-strong shadow-[0_0_8px_rgb(34_211_238/0.8)]" : "translate-x-[2px] bg-ink-muted",
          )}
        />
      </span>
    </button>
  );
}
