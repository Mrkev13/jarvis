"use client";

import { useId, useState } from "react";
import { compactNumber, linePoints, nearestIndex, niceTicks, pointLabel, SERIES_COLOR, stepPath, type WotPoint } from "@/lib/wotStats";

const PLOT = { w: 320, h: 140, l: 44, r: 8, t: 10, b: 22 };

/**
 * MRK-153: jedna veličina v čase (hodnocení, kredity…). Schodovitá 2px čára – stav se mění skokem při synchronizaci.
 * Jedna osa, jedna barva (bez legendy – název nese nadpis), najetí / dotyk ukáže hodnotu a čas, pod grafem tabulka.
 */
export function StepChart({ title, points, from, to, format = compactNumber, testId }: {
  title: string; points: WotPoint[]; from: string | null; to: string; format?: (v: number) => string; testId?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const titleId = useId();
  if (points.length === 0) {
    return (
      <figure className="space-y-2" data-testid={testId}>
        <figcaption className="text-sm font-medium text-ink">{title}</figcaption>
        <p className="text-sm text-ink-muted">Zatím bez dat – Hub je začne ukládat při další synchronizaci.</p>
      </figure>
    );
  }
  const values = points.map((p) => p.value);
  const ticks = niceTicks(Math.min(...values), Math.max(...values), 3);
  const x0 = from ? Date.parse(from) : Date.parse(points[0].at);
  const x1 = Date.parse(to);
  const { pts, sy } = linePoints(points, PLOT, x0, x1, ticks);
  const real = pts.slice(0, points.length);
  const active = hover != null ? real[hover] : null;

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const x = PLOT.l + ((e.clientX - box.left) / box.width) * (PLOT.w - PLOT.l - PLOT.r);
    setHover(nearestIndex(real.map((p) => p.x), x));
  }

  return (
    <figure className="space-y-2" data-testid={testId}>
      <figcaption className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-ink">{title}</span>
        <span className="tabular-nums text-ink-2" data-chart-current>{format(values[values.length - 1])}</span>
      </figcaption>
      <div className="relative">
        <svg viewBox={`0 0 ${PLOT.w} ${PLOT.h}`} className="h-auto w-full" role="img" aria-labelledby={titleId}>
          <title id={titleId}>{`${title}: ${points.length} ${points.length === 1 ? "stav" : "stavů"}, poslední ${format(values[values.length - 1])}`}</title>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PLOT.l} x2={PLOT.w - PLOT.r} y1={sy(t)} y2={sy(t)} className="stroke-line-subtle" strokeWidth="1" />
              <text x={PLOT.l - 6} y={sy(t) + 3.5} textAnchor="end" className="fill-ink-muted text-[10px] tabular-nums">{compactNumber(t)}</text>
            </g>
          ))}
          <text x={PLOT.l} y={PLOT.h - 6} className="fill-ink-muted text-[10px]">{pointLabel(new Date(x0).toISOString())}</text>
          <text x={PLOT.w - PLOT.r} y={PLOT.h - 6} textAnchor="end" className="fill-ink-muted text-[10px]">teď</text>
          <path d={stepPath(pts)} fill="none" stroke={SERIES_COLOR} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {active ? (
            <g pointerEvents="none">
              <line x1={active.x} x2={active.x} y1={PLOT.t} y2={PLOT.h - PLOT.b} className="stroke-ink-muted" strokeWidth="1" strokeDasharray="3 3" />
              <circle cx={active.x} cy={active.y} r="4" fill={SERIES_COLOR} className="stroke-surface" strokeWidth="2" />
            </g>
          ) : null}
          <rect x={PLOT.l} y={PLOT.t} width={PLOT.w - PLOT.l - PLOT.r} height={PLOT.h - PLOT.t - PLOT.b} fill="transparent"
            onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} data-chart-hit />
        </svg>
        {active ? (
          <div role="status" className="pointer-events-none absolute top-0 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2 py-1 text-xs shadow"
            style={{ left: `${Math.min(70, Math.max(0, (active.x / PLOT.w) * 100 - 10))}%` }} data-chart-tooltip>
            <span className="tabular-nums text-ink">{format(active.value)}</span>
            <span className="ml-1.5 text-ink-muted">{pointLabel(active.at)}</span>
          </div>
        ) : null}
      </div>
      <details className="text-xs text-ink-muted">
        <summary className="cursor-pointer">Tabulka</summary>
        <table className="mt-1 w-full">
          <tbody>
            {points.map((p) => (
              <tr key={p.at}><td className="py-0.5">{pointLabel(p.at)}</td><td className="text-right tabular-nums text-ink-2">{format(p.value)}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
