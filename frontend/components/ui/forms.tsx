import { useId } from "react";
import { cx } from "@/lib/ui";

/** Třídy pro input/select/textarea – jeden vzhled místo desítek kopií. */
export const fieldClass = cx(
  "w-full min-h-10 rounded-[var(--radius-control)] border border-line bg-surface-2 px-3 py-2 text-sm text-ink",
  "placeholder:text-ink-faint transition-colors",
  "hover:border-ink-faint focus:border-accent/70 focus:outline-none focus:ring-2 focus:ring-accent/25",
  "disabled:opacity-50 [color-scheme:dark]",
);

/**
 * Popisek + pole + nápověda/chyba. Pole dostane id a aria-describedby automaticky
 * (children je render funkce s props pro pole).
 */
export function FormField({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  className?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => React.ReactNode;
}) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cx("min-w-0 space-y-1.5", className)}>
      <label htmlFor={id} className="block text-xs font-medium text-ink-2">
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
