"use client";

import { useEffect, useState } from "react";
import { cx } from "@/lib/ui";
import { useOpenQuickAdd } from "./QuickAddProvider";

function useShortcutLabel(): string {
  const [label, setLabel] = useState("Ctrl ⇧ K");
  useEffect(() => {
    const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? "";
    if (/mac|iphone|ipad/i.test(platform)) queueMicrotask(() => setLabel("⌘ ⇧ K"));
  }, []);
  return label;
}

/** „+" v shellu: v postranním panelu jako tlačítko s nápovědou zkratky, v mobilní hlavičce jako ikona. */
export function QuickAddButton({ variant }: { variant: "field" | "icon" }) {
  const open = useOpenQuickAdd();
  const shortcut = useShortcutLabel();
  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={open}
        aria-label="Rychlé přidání"
        aria-haspopup="dialog"
        className="grid h-10 w-10 place-items-center rounded-lg text-2xl leading-none text-accent hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
      >
        <span aria-hidden="true">+</span>
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={open}
      aria-haspopup="dialog"
      aria-keyshortcuts="Control+Shift+K Meta+Shift+K"
      className={cx(
        "flex min-h-10 w-full items-center gap-2 rounded-[var(--radius-control)] border border-accent/30 bg-accent/5 px-3 text-sm text-ink-2 transition-colors",
        "hover:border-accent/60 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
      )}
    >
      <span aria-hidden="true" className="w-4 text-center text-base font-semibold leading-none text-accent">
        +
      </span>
      <span className="flex-1 text-left">Rychlé přidání</span>
      <kbd className="rounded border border-line-subtle bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">{shortcut}</kbd>
    </button>
  );
}
