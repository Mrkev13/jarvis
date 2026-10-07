"use client";

import { useTransitionSignal } from "@/lib/motion";
import { increased, STREAK_MILESTONES, streakVisual } from "@/lib/motionState";
import { cx } from "@/lib/ui";

export { STREAK_MILESTONES };

interface StreakFlameProps {
  days: number;
  broken?: boolean;
  milestones?: readonly number[];
  size?: "sm" | "md";
  /**
   * Jemné plápolání aktivního plamene. Výchozí vypnuto – zapínat jen na jednom „živém" místě
   * (např. dnešní návyk), ne v seznamech. Omezený pohyb ho vždy vypne.
   */
  idle?: boolean;
  /** Data jsou načtená (dokud ne, nárůst se nepočítá – načtení stránky plamen nerozhoří). Výchozí true. */
  ready?: boolean;
  /** Vlastní přístupný popis (výchozí česky „Streak 7 dní – milník"). */
  label?: string;
}

const SIZE_CLASS = { sm: "text-base", md: "text-2xl" } as const;

/**
 * Prezentační základ streaku pro budoucí Habits (Roadmap 6A) – bez sledování a ukládání.
 *  - aktivní streak → statický plamen (volitelně jemné plápolání `idle`),
 *  - nárůst streaku (days vzroste) → jedno krátké rozhoření (≈ 700 ms), ne při načtení,
 *  - milník (7, 14, 30 … dní) → trvale teplejší čip (barva, ne pohyb) + „milník" v popisu,
 *  - přerušený / nulový streak → šedý plamen bez animace.
 * Informace je v aria-label/title a v čísle; plamen je dekorace (aria-hidden).
 */
export function StreakFlame({ days, broken = false, milestones = STREAK_MILESTONES, size = "md", idle = false, ready = true, label }: StreakFlameProps) {
  const visual = streakVisual(days, { broken, milestones });
  const active = visual.state !== "inactive";
  const bump = useTransitionSignal(active ? days : 0, ready, increased);
  const text = label ?? visual.label;

  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full",
        visual.state === "milestone" && "bg-orange-500/10 px-2 ring-1 ring-inset ring-orange-400/40",
      )}
      role="img"
      aria-label={text}
      title={text}
      data-streak={visual.state}
    >
      <span
        // key = počet nárůstů → rozhoření se přehraje při každém dalším nárůstu (přemontuje se jen ikona)
        key={bump}
        aria-hidden="true"
        className={cx(
          "motion-flame",
          SIZE_CLASS[size],
          active && bump > 0 ? (idle ? "motion-streak-bump-idle" : "motion-streak-bump") : active && idle ? "motion-flame-active" : null,
          !active && "grayscale opacity-40",
        )}
      >
        🔥
      </span>
      <span aria-hidden="true" className={cx("font-semibold tabular-nums", active ? "text-orange-200" : "text-ink-muted")}>
        {Math.max(0, Math.floor(Number.isFinite(days) ? days : 0))}
      </span>
    </span>
  );
}
