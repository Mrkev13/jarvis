import { BAR_TONE, clampPercent, cx, progressTone, type Tone } from "@/lib/ui";

/** Ukazatel průběhu (role=progressbar). Barva: akcent, 100 % zeleně, jinou sémantiku dává volající. */
export function Progress({
  value,
  label,
  tone,
  size = "md",
  className,
}: {
  value: number;
  /** Přístupný popis („Splněno 42 %" se doplní). */
  label: string;
  tone?: Tone;
  size?: "sm" | "md";
  className?: string;
}) {
  const pct = clampPercent(value);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className={cx("w-full overflow-hidden rounded-full bg-surface-2 ring-1 ring-inset ring-line-subtle", size === "sm" ? "h-1.5" : "h-2", className)}
    >
      <div
        className={cx("motion-progress h-full rounded-full", BAR_TONE[progressTone(pct, tone)])}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
