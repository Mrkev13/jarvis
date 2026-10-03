import { cx, TEXT_TONE, type Tone } from "@/lib/ui";
import { HudLabel } from "./hud";

/**
 * Jedna metrika: popisek, hodnota (čitelná na první pohled), volitelný trend a doplněk.
 * `trend` je hotový text („+12 %"); barvu trendu dává `trendTone` (polaritu zná backend/stránka).
 */
export function MetricCard({
  label,
  value,
  unit,
  trend,
  trendTone = "neutral",
  hint,
  tone = "neutral",
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  unit?: React.ReactNode;
  trend?: React.ReactNode;
  trendTone?: Tone;
  hint?: React.ReactNode;
  /** Barva hodnoty – jen u veličin s významem (bilance, výdaje…). */
  tone?: Tone;
  className?: string;
}) {
  return (
    <div className={cx("min-w-0 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3 md:p-4", className)}>
      <HudLabel as="div">{label}</HudLabel>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5">
        <span className={cx("text-xl md:text-2xl font-semibold tabular-nums tracking-tight", tone === "neutral" ? "text-ink" : TEXT_TONE[tone])}>
          {value}
        </span>
        {unit ? <span className="text-sm text-ink-muted">{unit}</span> : null}
      </div>
      {trend || hint ? (
        <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs">
          {trend ? <span className={cx("font-medium tabular-nums", TEXT_TONE[trendTone])}>{trend}</span> : null}
          {hint ? <span className="text-ink-muted">{hint}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

/** Mřížka metrik: 2 sloupce na mobilu, víc na širších obrazovkách. */
export function StatGrid({ children, cols = 4, className }: { children: React.ReactNode; cols?: 2 | 3 | 4; className?: string }) {
  return (
    <div
      className={cx(
        "grid grid-cols-2 gap-3",
        cols === 3 ? "md:grid-cols-3" : cols === 4 ? "md:grid-cols-4" : null,
        className,
      )}
    >
      {children}
    </div>
  );
}
