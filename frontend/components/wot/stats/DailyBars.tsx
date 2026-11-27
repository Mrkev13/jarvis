"use client";

import { useId, useState } from "react";
import { dayLabel, niceTicks, pct, SERIES_COLOR, type WotDaily } from "@/lib/wotStats";

const PLOT = { w: 640, h: 180, l: 32, r: 8, t: 10, b: 24 };

/**
 * MRK-153: bitvy po dnech – sloupce od nuly, 4px zaoblený vrch, 2px mezera. Najetí / dotyk ukáže den, bitvy,
 * % výher a průměrný damage; popisky osy x jen u části dní (čitelnost na mobilu). Pod grafem tabulka.
 */
export function DailyBars({ days }: { days: WotDaily[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  const max = Math.max(1, ...days.map((d) => d.battles));
  const ticks = niceTicks(0, max, 3).filter((t) => t >= 0);
  const top = ticks[ticks.length - 1] || 1;
  const innerW = PLOT.w - PLOT.l - PLOT.r;
  const slot = innerW / days.length;
  const barW = Math.max(2, Math.min(28, slot - 2));
  const sy = (v: number) => PLOT.t + (1 - v / top) * (PLOT.h - PLOT.t - PLOT.b);
  const every = Math.ceil(days.length / 8);
  const active = hover != null ? days[hover] : null;

  return (
    <figure className="space-y-2" data-testid="wot-daily">
      <figcaption className="text-sm font-medium text-ink">Bitvy po dnech</figcaption>
      <div className="relative">
        <svg viewBox={`0 0 ${PLOT.w} ${PLOT.h}`} className="h-auto w-full" role="img" aria-labelledby={titleId} onPointerLeave={() => setHover(null)}>
          <title id={titleId}>{`Bitvy po dnech, celkem ${days.reduce((a, d) => a + d.battles, 0)}`}</title>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PLOT.l} x2={PLOT.w - PLOT.r} y1={sy(t)} y2={sy(t)} className="stroke-line-subtle" strokeWidth="1" />
              <text x={PLOT.l - 6} y={sy(t) + 3.5} textAnchor="end" className="fill-ink-muted text-[10px] tabular-nums">{t}</text>
            </g>
          ))}
          {days.map((d, i) => {
            const x = PLOT.l + i * slot + (slot - barW) / 2;
            const h = sy(0) - sy(d.battles);
            const r = Math.min(4, barW / 2, h);
            return (
              <g key={d.date}>
                {d.battles > 0 ? (
                  <path d={`M${x},${sy(0)}V${sy(d.battles) + r}Q${x},${sy(d.battles)} ${x + r},${sy(d.battles)}H${x + barW - r}Q${x + barW},${sy(d.battles)} ${x + barW},${sy(d.battles) + r}V${sy(0)}Z`}
                    fill={SERIES_COLOR} opacity={hover == null || hover === i ? 1 : 0.55} data-bar={d.date} />
                ) : null}
                {i % every === 0 || i === days.length - 1 ? (
                  <text x={x + barW / 2} y={PLOT.h - 7} textAnchor="middle" className="fill-ink-muted text-[10px]">{dayLabel(d.date)}</text>
                ) : null}
                <rect x={PLOT.l + i * slot} y={PLOT.t} width={slot} height={PLOT.h - PLOT.t - PLOT.b} fill="transparent"
                  onPointerEnter={() => setHover(i)} onPointerDown={() => setHover(i)} />
              </g>
            );
          })}
        </svg>
        {active ? (
          <div role="status" className="pointer-events-none absolute top-0 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2 py-1 text-xs shadow"
            style={{ left: `${Math.min(70, Math.max(0, ((PLOT.l + (hover ?? 0) * slot) / PLOT.w) * 100 - 6))}%` }} data-chart-tooltip>
            <span className="text-ink">{dayLabel(active.date)}</span>
            <span className="ml-1.5 tabular-nums text-ink-2">{active.battles} bitev · výhry {pct(active.win_rate)} · dmg {active.avg_damage == null ? "–" : Math.round(active.avg_damage).toLocaleString("cs-CZ")}</span>
          </div>
        ) : null}
      </div>
      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer">Tabulka</summary>
        <table className="mt-1 w-full">
          <thead><tr><th className="text-left font-normal">Den</th><th className="text-right font-normal">Bitvy</th><th className="text-right font-normal">Výhry</th><th className="text-right font-normal">Ø damage</th></tr></thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.date}>
                <td className="py-0.5">{dayLabel(d.date)}</td>
                <td className="text-right tabular-nums text-ink-2">{d.battles}</td>
                <td className="text-right tabular-nums text-ink-2">{pct(d.win_rate)}</td>
                <td className="text-right tabular-nums text-ink-2">{d.avg_damage == null ? "–" : Math.round(d.avg_damage).toLocaleString("cs-CZ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
