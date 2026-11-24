"use client";

import { GameImage } from "@/components/games/GameImage";
import { HudLabel } from "@/components/ui/hud";
import { useTankInfo } from "@/hooks/useTankInfo";
import { formatNumber } from "@/lib/format";
import { wotCore } from "@/lib/hudModules";
import { cx } from "@/lib/ui";
import { grindProgress, type WotGrind } from "@/lib/wot";
import { armorPlates, nationStyle, romanTier } from "@/lib/wotHangar";

/**
 * MRK-138: hangár – zaměřený tank (první aktivní grind) jako hlavní prvek stránky WoT: velký obrázek z Tankopedie,
 * tónování podle národa, římský tier na pozadí, XP lišta z pancéřových plátů a věta stavu (stejná jako HUD jádro,
 * data-hud-core="wot"). Bez manifestu obrázků zůstane čitelný text, jen bez tónování a tieru.
 */
export function HangarHero({ grind, activeCount, aces }: { grind: WotGrind | null; activeCount: number; aces: number }) {
  const tank = useTankInfo(grind?.tank);
  const nation = nationStyle(tank?.nation);
  const tier = romanTier(tank?.tier);
  const progress = grind ? grindProgress(grind) : null;
  const plates = armorPlates(progress);
  const model = wotCore(grind ? { tank: grind.tank, progress, remaining: Math.max(0, Number(grind.xp_remaining) || 0) } : null);
  return (
    <section
      aria-label="Hangár: zaměřený tank"
      data-hud-core="wot"
      data-hud-mood={model.mood}
      data-wot-hangar=""
      className="wot-hangar relative overflow-hidden rounded-card border p-4 md:p-6"
      style={{ ["--nation-rgb" as string]: nation?.rgb ?? "240 180 76" } as React.CSSProperties}
    >
      {tier ? <span aria-hidden="true" className="wot-hangar-tier">{tier}</span> : null}
      <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-6">
        <div className="wot-hangar-tank shrink-0 self-center">
          {grind ? <GameImage kind="tank" name={grind.tank} size="xl" mobileSize="lg" /> : <span className="block h-[88px] w-[141px]" />}
        </div>
        <div className="min-w-0 flex-1">
          <HudLabel as="div" className="flex flex-wrap items-center gap-x-2">
            <span>Hangár · zaměřeno</span>
            {nation ? <span data-wot-nation="">{nation.label}</span> : null}
            {tier ? <span data-wot-tier="">tier {tier}</span> : null}
          </HudLabel>
          <h2 className="wot-hangar-name mt-1 truncate font-display text-2xl font-bold uppercase tracking-[0.08em] text-ink md:text-3xl">
            {grind ? grind.tank : "Žádný grind"}
          </h2>
          <p data-hud-line="" className="mt-1 text-sm text-ink-2">{model.line}</p>
          {grind ? (
            <div className="mt-3" role="img" aria-label={progress === null ? "Průběh neznámý" : `Průběh ${progress} %`}>
              <div className="wot-plates" aria-hidden="true">
                {Array.from({ length: plates.total }, (_, i) => (
                  <span key={i} className={cx("wot-plate", i < plates.lit && "wot-plate-lit")} style={{ ["--i" as string]: i } as React.CSSProperties} />
                ))}
              </div>
              <div className="mt-1.5 flex flex-wrap justify-between gap-x-4 text-xs tabular-nums text-ink-muted">
                <span>Zbývá <b className="font-semibold text-ink">{formatNumber(grind.xp_remaining)} XP</b>{grind.xp_start ? ` z ${formatNumber(grind.xp_start)}` : ""}</span>
                <span>{progress === null ? "průběh neznámý" : `${progress} %`}</span>
              </div>
            </div>
          ) : null}
          <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted">
            <div className="flex items-baseline gap-1.5"><dt>Aktivní grindy</dt><dd className="font-display text-base font-semibold tabular-nums text-ink-2">{activeCount}</dd></div>
            <div className="flex items-baseline gap-1.5"><dt>Mka</dt><dd className="font-display text-base font-semibold tabular-nums text-warning">{aces}</dd></div>
          </dl>
        </div>
      </div>
    </section>
  );
}
