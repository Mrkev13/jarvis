"use client";

import { useRef } from "react";
import { cx } from "@/lib/ui";

export type TabItem<T extends string> = { value: T; label: React.ReactNode; count?: number };

/**
 * Segmentové přepínání pohledů (role=tablist). Šipky vlevo/vpravo, Home/End. Obsah si stránka vykreslí sama
 * a označí ho `role="tabpanel"` s aria-labelledby={`${id}-${value}`}.
 */
export function Tabs<T extends string>({
  id,
  items,
  value,
  onChange,
  label,
  className,
}: {
  id: string;
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  className?: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(e: React.KeyboardEvent, index: number) {
    let next = -1;
    if (e.key === "ArrowRight") next = (index + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(items[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} className={cx("inline-flex rounded-[var(--radius-control)] border border-line bg-surface p-1", className)}>
      {items.map((item, i) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`${id}-${item.value}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`${id}-panel`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cx(
              "motion-press min-h-9 rounded-lg px-3 text-sm transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
              selected ? "bg-elevated text-ink shadow-[inset_0_-1px_0_0_rgb(34_211_238/0.6)]" : "text-ink-muted hover:text-ink",
            )}
          >
            {item.label}
            {item.count !== undefined ? <span className="ml-1.5 tabular-nums text-ink-muted">{item.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
