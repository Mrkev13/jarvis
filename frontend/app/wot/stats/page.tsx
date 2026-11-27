"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { DailyBars } from "@/components/wot/stats/DailyBars";
import { StepChart } from "@/components/wot/stats/StepChart";
import { GameImage } from "@/components/games/GameImage";
import {
  AreaBadge,
  Card,
  CardHeader,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  StatGrid,
  TextLink,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { RESOURCE_LABELS } from "@/lib/wot";
import { changeLabel, compactNumber, pct, PERIOD_OPTIONS, pointLabel, type WotStats, type WotStatsPeriod } from "@/lib/wotStats";
import { cx } from "@/lib/ui";

const RESOURCES = ["credits", "gold", "bonds", "free_xp"] as const;

/**
 * MRK-153: statistiky WoT po bitvách – bez replaye, ze snímků hodinové synchronizace s Wargaming API.
 * Období dnes / 3 dny / týden / měsíc / půl roku / celkově (v adrese `?period=`). Hodnocení a zdroje v čase
 * (každá veličina vlastní graf – různá měřítka, nikdy dvě osy), bitvy po dnech, tanky za období.
 */
function Stats() {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("period");
  const period: WotStatsPeriod = PERIOD_OPTIONS.some((o) => o.value === raw) ? (raw as WotStatsPeriod) : "week";
  const res = useApiResource<WotStats>(`/wot/stats?period=${period}`);
  const s = res.data?.period === period ? res.data : null;

  return (
    <ContentContainer className="theme-wot">
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Tanks</HudLabel>}
        title="Statistiky"
        subtitle="Bitvy, hodnocení a zdroje – automaticky z Wargaming API, bez replaye."
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <AreaBadge area="wot" />
            <TextLink href="/wot">← World of Tanks</TextLink>
          </span>
        }
      />

      {/* filtr období – jeden řádek nad grafy, platí pro všechno na stránce */}
      <div role="group" aria-label="Období" className="mb-5 flex flex-wrap gap-1.5" data-wot-periods>
        {PERIOD_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={period === o.value}
            onClick={() => router.replace(o.value === "week" ? "/wot/stats" : `/wot/stats?period=${o.value}`, { scroll: false })}
            className={cx(
              "motion-press min-h-9 pointer-coarse:min-h-11 rounded-full border px-3 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
              period === o.value ? "border-accent/50 bg-accent/10 text-accent-strong" : "border-line bg-surface-2 text-ink-muted hover:text-ink",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>

      {res.status === "error" ? (
        <ErrorState message="Statistiky se nepodařilo načíst." onRetry={() => void res.reload()} />
      ) : !s ? (
        <LoadingState lines={4} label="Počítám statistiky…" />
      ) : (
        <div className="space-y-6" data-wot-stats={period}>
          {s.partial && s.data_since ? (
            <p className="text-sm text-ink-muted" data-wot-partial>
              Hub ukládá statistiky od {pointLabel(s.data_since)} – starší část období zatím nemá data.
            </p>
          ) : null}

          <Card as="section" aria-labelledby="wot-stats-summary">
            <CardHeader title={<span id="wot-stats-summary">{s.label}</span>} />
            {s.summary.battles === 0 ? (
              <EmptyState compact>Za tohle období žádné bitvy.</EmptyState>
            ) : (
              <StatGrid cols={4}>
                <MetricCard label="Bitvy" value={s.summary.battles.toLocaleString("cs-CZ")} />
                <MetricCard label="Výhry" value={pct(s.summary.win_rate)} hint={`${s.summary.wins.toLocaleString("cs-CZ")} vítězství`} />
                <MetricCard label="Ø damage" value={compactNumber(s.summary.avg_damage)} hint={`Ø ${s.summary.avg_frags ?? "–"} zničení`} />
                <MetricCard label="Přežití" value={pct(s.summary.survival)} hint={`Ø ${compactNumber(s.summary.avg_xp)} XP`} />
              </StatGrid>
            )}
            {s.best_tank ? (
              <p className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2" data-wot-best>
                <span className="flex items-center gap-2">
                  <GameImage kind="tank" name={s.best_tank.name} size="xs" />
                  <span>Nejlíp ti šel <span className="font-medium text-ink">{s.best_tank.name}</span></span>
                </span>
                <span className="tabular-nums text-ink-muted">· {s.best_tank.battles} bitev · Ø {compactNumber(s.best_tank.avg_damage)} dmg · výhry {pct(s.best_tank.win_rate)}</span>
              </p>
            ) : null}
          </Card>

          <Card as="section" aria-labelledby="wot-stats-rating">
            <CardHeader
              title={<span id="wot-stats-rating">Hodnocení</span>}
              description={`Osobní hodnocení Wargamingu${s.rating_change != null ? ` · ${s.rating_change > 0 ? "+" : ""}${s.rating_change} za období` : ""}. WN8 přijde později.`}
            />
            <StepChart title="Osobní hodnocení" points={s.rating} from={s.from} to={s.to} format={(v) => Math.round(v).toLocaleString("cs-CZ")} testId="wot-rating-chart" wide />
          </Card>

          <Card as="section" aria-labelledby="wot-stats-resources">
            <CardHeader title={<span id="wot-stats-resources">Zdroje v čase</span>} description="Z propojeného Wargaming účtu. Každá měna má vlastní graf (jiná měřítka)." />
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              {RESOURCES.map((k) => (
                <div key={k}>
                  <StepChart title={RESOURCE_LABELS[k]} points={s.resources[k]} from={s.from} to={s.to} testId={`wot-resource-chart-${k}`} />
                  {changeLabel(s.resources[k]) ? <p className="mt-1 text-xs text-ink-muted">Za období: {changeLabel(s.resources[k])}</p> : null}
                </div>
              ))}
            </div>
          </Card>

          {s.daily.length > 1 ? (
            <Card as="section" aria-labelledby="wot-stats-daily">
              <CardHeader title={<span id="wot-stats-daily">Po dnech</span>} />
              <DailyBars days={s.daily} />
            </Card>
          ) : null}

          {s.tanks.length ? (
            <Card as="section" aria-labelledby="wot-stats-tanks">
              <CardHeader title={<span id="wot-stats-tanks">Tanky</span>} description="Seřazeno podle počtu bitev." />
              <div className="overflow-x-auto">
                <table className="w-full text-sm" aria-label="Tanky za období" data-wot-tanks>
                  <thead>
                    <tr className="text-left text-xs text-ink-muted">
                      <th className="py-1.5 font-normal">Tank</th>
                      <th className="py-1.5 text-right font-normal">Bitvy</th>
                      <th className="py-1.5 text-right font-normal">Výhry</th>
                      <th className="py-1.5 pl-2 text-right font-normal">Ø dmg</th>
                      <th className="hidden py-1.5 text-right font-normal sm:table-cell">Ø zničení</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line-subtle">
                    {s.tanks.map((t) => (
                      <tr key={t.tank_id} data-tank={t.tank_id}>
                        <td className="py-1.5">
                          <span className="flex items-center gap-2">
                            <GameImage kind="tank" name={t.name} size="xs" />
                            <span className="text-ink">{t.name}</span>
                            {t.tier ? <span className="hidden text-xs text-ink-muted sm:inline">tier {t.tier}</span> : null}
                          </span>
                        </td>
                        <td className="py-1.5 text-right tabular-nums">{t.battles}</td>
                        <td className="py-1.5 text-right tabular-nums">{pct(t.win_rate)}</td>
                        <td className="py-1.5 text-right tabular-nums">{compactNumber(t.avg_damage)}</td>
                        <td className="hidden py-1.5 text-right tabular-nums sm:table-cell">{t.avg_frags ?? "–"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : null}
        </div>
      )}
    </ContentContainer>
  );
}

export default function WotStatsPage() {
  return (
    <Suspense fallback={null}>
      <Stats />
    </Suspense>
  );
}
