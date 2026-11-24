import Link from "next/link";
import { DayReactor } from "@/components/dashboard/JarvisCore";
import { HudLabel } from "@/components/ui/hud";
import { cx } from "@/lib/ui";

export type HudMood = "alert" | "done" | "calm";
export type HudCoreStat = { label: string; value: React.ReactNode; tone?: string };

/**
 * MRK-134: HUD jádro modulu – stejný jazyk jako Jarvis jádro dne na dashboardu (MRK-132): reaktor se segmenty
 * (rozsvícené = splněné) a jedna věta stavu. Čísla počítá stránka deterministicky ze svých dat, žádné AI.
 * Na mobilu kompaktní řádek (malý reaktor + věta), statistiky od md.
 */
export function HudCore({
  label,
  line,
  total,
  lit,
  mood = "calm",
  stats,
  href,
  linkLabel,
  module,
  className,
}: {
  label: string;
  line: React.ReactNode;
  total: number;
  lit: number;
  mood?: HudMood;
  stats?: HudCoreStat[];
  href?: string;
  linkLabel?: string;
  /** data-hud-core – pro UI kontroly a styl („habits", „work"…) */
  module: string;
  className?: string;
}) {
  const reactor = <DayReactor total={Math.max(0, total)} lit={Math.max(0, Math.min(lit, total))} mood={mood} />;
  return (
    <section aria-label={label} data-hud-core={module} data-hud-mood={mood} className={cx("jarvis-core flex items-center gap-4 md:gap-6", className)}>
      {href ? (
        <Link href={href} aria-label={linkLabel ?? label} className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70">
          {reactor}
        </Link>
      ) : (
        <span className="shrink-0">{reactor}</span>
      )}
      <div className="min-w-0 flex-1">
        <HudLabel as="div" className="hidden md:block">{label}</HudLabel>
        <p data-hud-line="" className="jarvis-core-line font-display text-sm font-medium text-ink md:mt-1 md:text-xl">{line}</p>
        {stats?.length ? (
          <dl className="mt-2 hidden flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted md:flex">
            {stats.map((s) => (
              <div key={s.label} className="flex items-baseline gap-1.5">
                <dt>{s.label}</dt>
                <dd className={cx("font-display text-base font-semibold tabular-nums", s.tone ?? "text-ink-2")}>{s.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
    </section>
  );
}
