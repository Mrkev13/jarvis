"use client";

import { useEffect, useState } from "react";
import { cx } from "@/lib/ui";
import { SearchIcon } from "./SearchIcon";
import { useOpenSearch } from "./SearchProvider";

/** Mac → „⌘ K", jinak „Ctrl K" (jen nápověda; zkratka funguje s oběma klávesami). */
function useShortcutLabel(): string {
  const [label, setLabel] = useState("Ctrl K");
  useEffect(() => {
    const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? "";
    if (/mac|iphone|ipad/i.test(platform)) queueMicrotask(() => setLabel("⌘ K"));
  }, []);
  return label;
}

/**
 * Vstup do globálního vyhledávání v shellu: v postranním panelu jako pole s nápovědou zkratky,
 * v mobilní hlavičce jako ikona.
 */
export function SearchButton({ variant }: { variant: "field" | "icon" }) {
  const open = useOpenSearch();
  const shortcut = useShortcutLabel();
  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={open}
        aria-label="Hledat"
        aria-haspopup="dialog"
        className="grid h-10 w-10 place-items-center rounded-lg text-lg text-ink-2 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
      >
        <SearchIcon className="h-5 w-5" />
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={open}
      aria-haspopup="dialog"
      aria-keyshortcuts="Control+K Meta+K"
      className={cx(
        "flex min-h-10 w-full items-center gap-2 rounded-[var(--radius-control)] border border-line bg-surface px-3 text-sm text-ink-muted transition-colors",
        "hover:border-ink-faint hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
      )}
    >
      <SearchIcon />
      <span className="flex-1 text-left">Hledat…</span>
      <kbd className="rounded border border-line-subtle bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-faint">{shortcut}</kbd>
    </button>
  );
}
