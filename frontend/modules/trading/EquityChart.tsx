"use client";

import { useId, useState } from "react";
import { BENCHMARK_COLOR, chartModel, linePath, maxDrawdown, pct, seriesColors, shortDate, usd, type EquityPoint, type TradingStrategy } from "./lib";

const W = 640;
const H = 240;

/**
 * MRK-141: křivka kapitálu všech strategií proti SPY (`/equity/{strategie}?days=90`). Jedna osa (USD), 2px čáry,
 * benchmark šedý čárkovaný, barvy podle jména strategie (ne pořadí). Legenda nad grafem nese i max drawdown;
 * najetí / dotyk ukáže hodnoty všech strategií za den; pod grafem tabulka (přístupnost, žádná informace jen barvou).
 */
export function EquityChart({ equity, strategies }: { equity: Record<string, EquityPoint[]>; strategies: TradingStrategy[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  const model = chartModel(equity, W, H);
  if (!model) return <p className="text-sm text-ink-muted">Graf se ukáže, až budou aspoň dva obchodní dny dat.</p>;

  const colors = seriesColors(Object.keys(equity));
  const label = (name: string) => strategies.find((s) => s.name === name)?.label ?? name;
  // legenda / tabulka: pořadí jako karty strategií (nejlepší nahoře, SPY poslední)
  const order = [...strategies.map((s) => s.name).filter((n) => equity[n]), ...Object.keys(equity).filter((n) => !strategies.some((s) => s.name === n))];
  const day = hover != null ? model.dates[hover] : null;
  const valueAt = (name: string, d: string) => equity[name]?.find((p) => p.date === d)?.total ?? null;
  const xAt = (i: number) => 56 + (i / (model.dates.length - 1)) * (W - 56 - 12);
  const yOf = (v: number) => 10 + (1 - (v - model.yMin) / (model.yMax - model.yMin)) * (H - 10 - 24);

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((x - 56) / (W - 56 - 12)) * (model!.dates.length - 1));
    setHover(Math.max(0, Math.min(model!.dates.length - 1, i)));
  }

  return (
    <figure className="space-y-3" data-trading-equity="">
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-2" aria-label="Legenda grafu">
        {order.map((n) => {
          const pts = equity[n];
          const dd = maxDrawdown(pts);
          const bench = colors[n] === BENCHMARK_COLOR;
          return (
            <li key={n} className="flex items-center gap-1.5" data-legend={n}>
              <svg aria-hidden="true" width="18" height="8"><line x1="1" y1="4" x2="17" y2="4" stroke={colors[n]} strokeWidth="2" strokeDasharray={bench ? "4 3" : undefined} strokeLinecap="round" /></svg>
              <span className="text-ink">{label(n)}</span>
              <span className="tabular-nums text-ink-muted">{usd(pts[pts.length - 1]?.total)}{dd != null && dd < 0 ? ` · max DD ${pct(dd)}` : ""}</span>
            </li>
          );
        })}
      </ul>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-labelledby={titleId}>
          <title id={titleId}>Vývoj kapitálu strategií proti SPY za posledních {model.dates.length} obchodních dní</title>
          {model.yTicks.map((t) => (
            <g key={t}>
              <line x1="56" x2={W - 12} y1={yOf(t)} y2={yOf(t)} className="stroke-line-subtle" strokeWidth="1" />
              <text x="50" y={yOf(t) + 4} textAnchor="end" className="fill-ink-muted text-[11px] tabular-nums">{Math.round(t).toLocaleString("cs-CZ")}</text>
            </g>
          ))}
          <text x="56" y={H - 6} className="fill-ink-muted text-[11px]">{shortDate(model.dates[0])}</text>
          <text x={W - 12} y={H - 6} textAnchor="end" className="fill-ink-muted text-[11px]">{shortDate(model.dates[model.dates.length - 1])}</text>
          {/* benchmark pod strategiemi, ať je měřítko a ne hlavní linka */}
          {[...model.series].sort((a, b) => Number(colors[b.name] === BENCHMARK_COLOR) - Number(colors[a.name] === BENCHMARK_COLOR)).map((s) => (
            <path key={s.name} d={linePath(s.points)} fill="none" stroke={colors[s.name]} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
              strokeDasharray={colors[s.name] === BENCHMARK_COLOR ? "6 4" : undefined} data-series={s.name} />
          ))}
          {hover != null ? (
            <g pointerEvents="none">
              <line x1={xAt(hover)} x2={xAt(hover)} y1="10" y2={H - 24} className="stroke-ink-muted" strokeWidth="1" strokeDasharray="2 3" />
              {order.map((n) => {
                const v = valueAt(n, model.dates[hover]);
                return v == null ? null : <circle key={n} cx={xAt(hover)} cy={yOf(v)} r="4" fill={colors[n]} className="stroke-surface" strokeWidth="2" />;
              })}
            </g>
          ) : null}
          <rect x="56" y="0" width={W - 68} height={H - 24} fill="transparent" onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
        {day ? (
          <div role="status" className="pointer-events-none absolute right-2 top-2 rounded-[var(--radius-control)] border border-line-subtle bg-surface/95 px-2.5 py-1.5 text-xs shadow-lg" data-equity-tooltip="">
            <p className="font-medium text-ink">{shortDate(day)}</p>
            {order.map((n) => {
              const v = valueAt(n, day);
              return v == null ? null : (
                <p key={n} className="flex items-center justify-between gap-3 tabular-nums">
                  <span className="flex items-center gap-1.5 text-ink-2"><span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: colors[n] }} />{label(n)}</span>
                  <span className="text-ink">{usd(v)}</span>
                </p>
              );
            })}
          </div>
        ) : null}
      </div>
      <details className="text-xs text-ink-2">
        <summary className="cursor-pointer text-ink-muted">Tabulka hodnot</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[22rem] text-left tabular-nums">
            <thead><tr className="text-ink-muted"><th className="py-1 pr-3 font-normal">Den</th>{order.map((n) => <th key={n} className="py-1 pr-3 font-normal">{label(n)}</th>)}</tr></thead>
            <tbody>
              {[...model.dates].reverse().map((d) => (
                <tr key={d} className="border-t border-line-subtle"><td className="py-1 pr-3">{shortDate(d)}</td>{order.map((n) => <td key={n} className="py-1 pr-3">{usd(valueAt(n, d))}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
