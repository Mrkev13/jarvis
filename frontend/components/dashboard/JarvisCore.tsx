import Link from "next/link";
import { HudLabel } from "@/components/ui/hud";
import { coreLine, coreMood, coreSegments } from "@/lib/jarvisCore";
import type { TodayPayload } from "@/lib/today";
import { cx } from "@/lib/ui";

/**
 * MRK-132: Jarvis jádro dne – nahoře na dashboardu. Reaktor, jehož segmenty jsou dnešní položky (rozsvícené =
 * hotové), a jedna věta od Jarvise. Vše z GET /today (lib/jarvisCore.ts), žádné AI. Na mobilu kompaktní řádek,
 * aby „Co hoří" a další položka dne zůstaly na první obrazovce (MRK-78).
 */
export function JarvisCore({ today }: { today: TodayPayload }) {
  const { summary } = today;
  const seg = coreSegments(summary.done, summary.remaining);
  const mood = coreMood(summary);
  const line = coreLine(summary);
  return (
    <section
      aria-label="Jarvis: stav dne"
      data-jarvis-core={mood}
      className="jarvis-core flex items-center gap-4 md:gap-6"
    >
      <Link
        href="/today"
        aria-label={`Režim Dnes: hotovo ${summary.done}, zbývá ${summary.remaining}`}
        className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
      >
        <DayReactor total={seg.total} lit={seg.lit} mood={mood} />
      </Link>
      <div className="min-w-0 flex-1">
        <HudLabel as="div" className="hidden md:block">Jarvis · stav dne · {today.date_label}</HudLabel>
        <p data-jarvis-line="" className="jarvis-core-line font-display text-sm font-medium text-ink md:mt-1 md:text-xl">
          {line}
        </p>
        <dl className="mt-2 hidden flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted md:flex">
          <Stat label="Hotovo" value={summary.done} tone="text-success" />
          <Stat label="Zbývá" value={summary.remaining} tone="text-accent-strong" />
          <Stat label="Hoří" value={summary.attention} tone={summary.attention > 0 ? "text-danger" : "text-ink-2"} />
        </dl>
      </div>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt>{label}</dt>
      <dd className={cx("font-display text-base font-semibold tabular-nums", tone)}>{value}</dd>
    </div>
  );
}

const R = 40;
const GAP = 5; // stupně mezi segmenty

function arc(start: number, end: number): string {
  const rad = (d: number) => ((d - 90) * Math.PI) / 180;
  const [x1, y1] = [50 + R * Math.cos(rad(start)), 50 + R * Math.sin(rad(start))];
  const [x2, y2] = [50 + R * Math.cos(rad(end)), 50 + R * Math.sin(rad(end))];
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 ${end - start > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

/** Reaktor dne: segmenty po obvodu (hotové svítí), uprostřed jádro v barvě nálady dne. */
export function DayReactor({ total, lit, mood }: { total: number; lit: number; mood: "alert" | "done" | "calm" }) {
  const n = Math.max(total, 1);
  const step = 360 / n;
  return (
    <svg viewBox="0 0 100 100" aria-hidden="true" focusable="false" className={cx("day-reactor", `day-reactor-${mood}`)}>
      <circle cx="50" cy="50" r="48" className="day-reactor-halo" />
      <circle cx="50" cy="50" r="47" fill="none" className="day-reactor-rim" strokeWidth="1" />
      <g className="day-reactor-segments">
        {total === 0 ? (
          <circle cx="50" cy="50" r={R} fill="none" strokeWidth="7" className="day-seg" strokeDasharray="2 4" />
        ) : (
          Array.from({ length: n }, (_, i) => (
            <path
              key={i}
              d={n === 1 ? arc(0, 359.9) : arc(i * step + GAP / 2, (i + 1) * step - GAP / 2)}
              fill="none"
              strokeWidth="7"
              strokeLinecap="butt"
              className={cx("day-seg", i < lit && "day-seg-lit")}
              style={{ ["--i" as string]: i } as React.CSSProperties}
            />
          ))
        )}
      </g>
      <circle cx="50" cy="50" r="27" fill="none" strokeWidth="1.5" strokeDasharray="3 3" className="day-reactor-inner" />
      <circle cx="50" cy="50" r="17" className="day-reactor-core" />
    </svg>
  );
}
