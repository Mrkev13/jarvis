"use client";

import { useId } from "react";
import { cx } from "@/lib/ui";
import { Button } from "./Button";
import { fieldClass } from "./forms";

/**
 * Lišta filtrů seznamu (Roadmap 4B: Aktivita, Paměť): vyhledávání, filtry, počet výsledků
 * a „Zrušit filtry". role=search; počet výsledků se ohlásí čtečce (aria-live).
 * Načítání s debounce řeší stránka (useApiResource({ debounceMs })), lišta jen sbírá hodnoty.
 */
export function FilterBar({
  label,
  search,
  children,
  activeCount = 0,
  onReset,
  result,
  className,
}: {
  /** Přístupný název oblasti hledání („Filtry aktivity"). */
  label: string;
  search?: { value: string; onChange: (value: string) => void; placeholder?: string; label?: string };
  /** Další filtry (FilterSelect, FilterChips, data…). */
  children?: React.ReactNode;
  activeCount?: number;
  onReset?: () => void;
  /** Krátký text o výsledcích („12 záznamů"). */
  result?: React.ReactNode;
  className?: string;
}) {
  const searchId = useId();
  return (
    <div
      role="search"
      aria-label={label}
      className={cx("space-y-3 rounded-card border border-line bg-surface p-3 md:p-4", className)}
    >
      {search ? (
        <div className="min-w-0">
          <label htmlFor={searchId} className="sr-only">
            {search.label ?? "Hledat"}
          </label>
          <input
            id={searchId}
            type="search"
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
            placeholder={search.placeholder ?? "Hledat…"}
            className={cx(fieldClass, "pointer-coarse:min-h-11")}
          />
        </div>
      ) : null}
      {children ? <div className="flex flex-wrap items-end gap-3">{children}</div> : null}
      {result || (onReset && activeCount > 0) ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-muted">
          <span aria-live="polite">{result}</span>
          {onReset && activeCount > 0 ? (
            <Button size="sm" variant="ghost" onClick={onReset}>
              Zrušit filtry ({activeCount})
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Výběr v liště filtrů s viditelným popiskem. */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cx("min-w-[9rem] flex-1 space-y-1 sm:flex-none", className)}>
      <label htmlFor={id} className="block text-xs font-medium text-ink-2">
        {label}
      </label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={cx(fieldClass, "pointer-coarse:min-h-11")}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Multi-výběr čipy (aria-pressed). Prázdný výběr = vše. */
export function FilterChips({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  selected: ReadonlyArray<string>;
  onToggle: (value: string) => void;
}) {
  return (
    <div role="group" aria-label={label} className="w-full">
      <div className="mb-1 text-xs font-medium text-ink-2" aria-hidden="true">
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const pressed = selected.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={pressed}
              onClick={() => onToggle(o.value)}
              className={cx(
                "motion-press min-h-9 pointer-coarse:min-h-11 rounded-full border px-3 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                pressed ? "border-accent/50 bg-accent/10 text-accent-strong" : "border-line bg-surface-2 text-ink-muted hover:text-ink",
              )}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
