"use client";

/** Hranice, při kterých se plamen krátce „rozhoří" (připraveno pro budoucí Habits/Fitness). */
export const STREAK_MILESTONES = [7, 14, 30, 50, 100, 365] as const;

interface StreakFlameProps {
  days: number;
  broken?: boolean;
  milestones?: readonly number[];
  size?: "sm" | "md" | "lg";
}

const SIZE_CLASS = { sm: "text-base", md: "text-2xl", lg: "text-4xl" } as const;

/**
 * Plamen streaku:
 *  - aktivní streak → jemné plápolání,
 *  - milník (7, 14, 30 … dní) → krátké silnější rozhoření, pak plápolání,
 *  - přerušený / nulový streak → šedý plamen bez animace.
 * Animace respektují prefers-reduced-motion (viz app/motion.css).
 */
export function StreakFlame({ days, broken = false, milestones = STREAK_MILESTONES, size = "md" }: StreakFlameProps) {
  const active = !broken && days > 0;
  const milestone = active && milestones.includes(days);
  const motionClass = milestone ? "motion-flame-milestone" : active ? "motion-flame-active" : "";
  const label = active
    ? `Streak ${days} ${days === 1 ? "den" : days < 5 ? "dny" : "dní"}${milestone ? " – milník!" : ""}`
    : "Streak přerušen";

  return (
    <span className="inline-flex items-center gap-1.5" role="img" aria-label={label} title={label}>
      <span
        // key = days → při dosažení milníku se rozhoření přehraje znovu
        key={milestone ? `m-${days}` : "flame"}
        aria-hidden="true"
        className={`motion-flame ${SIZE_CLASS[size]} ${motionClass} ${active ? "" : "grayscale opacity-40"}`}
      >
        🔥
      </span>
      <span className={`font-semibold tabular-nums ${active ? "text-orange-200" : "text-zinc-500"}`}>{days}</span>
    </span>
  );
}
