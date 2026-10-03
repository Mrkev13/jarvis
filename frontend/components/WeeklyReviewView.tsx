"use client";

import Link from "next/link";
import { Card, EntityList, EntityRow, HudFrame, HudLabel, MetricCard, StatGrid, StatusBadge } from "@/components/ui";
import { safeHref } from "@/lib/briefing";
import { staggerStyle } from "@/lib/motion";
import { cx, trendTone, type Tone } from "@/lib/ui";
import { confidenceLabel, type ForecastView, type WeeklyContent, type WeeklyItem } from "@/lib/weeklyReview";

function MaybeLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = safeHref(url);
  return href ? (
    <Link
      href={href}
      className="block rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 motion-hover-lift"
    >
      {children}
    </Link>
  ) : (
    <>{children}</>
  );
}

/** Fakt: neutrální plocha, význam nese jen tečka a nadpis sekce (ne barevné pozadí). */
function FactList({ items, tone }: { items: WeeklyItem[]; tone: Tone }) {
  const dot = tone === "success" ? "bg-success" : tone === "danger" ? "bg-warning" : "bg-accent";
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.ref}>
          <MaybeLink url={item.url}>
            <div className="flex gap-3 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-3 py-2.5">
              <span aria-hidden="true" className={cx("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", dot)} />
              <div className="min-w-0 text-sm">
                <div className="break-words text-ink">{item.text}</div>
                {item.when && !item.text.includes(item.when) ? <div className="mt-0.5 text-xs text-ink-muted">{item.when}</div> : null}
              </div>
            </div>
          </MaybeLink>
        </li>
      ))}
    </ul>
  );
}

function BlockTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <h3 className="mb-2.5 flex flex-wrap items-baseline gap-x-2 text-sm font-semibold text-ink">
      {children}
      {hint ? <HudLabel className="text-[10px]">{hint}</HudLabel> : null}
    </h3>
  );
}

function ForecastPanel({ forecasts }: { forecasts: ForecastView[] }) {
  return (
    <HudFrame variant="violet">
      <Card tone="ai" className="bg-accent-2/[0.04]" aria-labelledby="forecasts-title">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 id="forecasts-title" className="flex items-center gap-2 text-sm font-semibold text-ink">
            Odhady
            <StatusBadge tone="ai">Odhad / Forecast</StatusBadge>
          </h3>
          <HudLabel>nejsou fakta · jen z dat</HudLabel>
        </div>
        {forecasts.length ? (
          <ul className="space-y-3">
            {forecasts.map((f) => (
              <li key={f.ref} className="border-l-2 border-dashed border-accent-2/50 pl-3">
                <p className="text-sm italic text-ink">{f.statement}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <StatusBadge tone="ai">{confidenceLabel(f.confidence)}</StatusBadge>
                  {f.basis_labels.length || f.rule ? (
                    <span className="text-xs text-ink-muted">
                      Podklad: {[f.rule, ...f.basis_labels].filter(Boolean).join(" · ")}
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-muted">Žádný odhad – data na něj nestačí.</p>
        )}
      </Card>
    </HudFrame>
  );
}

/** Obsah týdenního přehledu: fakta, srovnání (spočítaná), příští týden, odhady (vizuálně oddělené), zaměření. */
export default function WeeklyReviewView({ content, isFallback = false }: { content: WeeklyContent; isFallback?: boolean }) {
  const metrics = content.comparisons.filter((c) => c.metric);
  const textComparisons = content.comparisons.filter((c) => !c.metric);
  return (
    <div className="space-y-6">
      <div className="motion-card" style={staggerStyle(0)}>
        {isFallback ? (
          <StatusBadge tone="warning" className="mb-2">Náhled z dat – bez AI shrnutí</StatusBadge>
        ) : null}
        <h2 className="break-words text-xl md:text-2xl font-semibold tracking-tight text-ink">{content.headline}</h2>
        <p className="mt-2 max-w-3xl leading-relaxed text-ink-2">{content.summary}</p>
      </div>

      {content.wins.length || content.concerns.length ? (
        <div className="grid gap-5 md:grid-cols-2">
          {content.wins.length ? (
            <section className="motion-card min-w-0" style={staggerStyle(1)}>
              <BlockTitle hint="fakta">Co se povedlo</BlockTitle>
              <FactList items={content.wins} tone="success" />
            </section>
          ) : null}
          {content.concerns.length ? (
            <section className="motion-card min-w-0" style={staggerStyle(2)}>
              <BlockTitle hint="fakta">Na co pozor</BlockTitle>
              <FactList items={content.concerns} tone="danger" />
            </section>
          ) : null}
        </div>
      ) : null}

      {metrics.length || textComparisons.length ? (
        <section className="motion-card" style={staggerStyle(3)}>
          <BlockTitle hint="spočítáno z dat">Srovnání s minulým týdnem</BlockTitle>
          {metrics.length ? (
            <StatGrid cols={3}>
              {metrics.map((c) => {
                const m = c.metric!;
                return (
                  <MetricCard
                    key={c.ref}
                    label={m.label}
                    value={m.cur_text}
                    trend={m.delta_text || undefined}
                    trendTone={trendTone(m.trend)}
                    hint={m.prev_text !== null ? `${m.prev_label} ${m.prev_text}` : undefined}
                  />
                );
              })}
            </StatGrid>
          ) : null}
          {textComparisons.length ? <FactList items={textComparisons} tone="neutral" /> : null}
        </section>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="motion-card min-w-0" style={staggerStyle(4)}>
          <BlockTitle hint="známé závazky">Příští týden</BlockTitle>
          {content.next_week.length ? (
            <EntityList>
              {content.next_week.map((n) => (
                <EntityRow key={n.ref} title={<MaybeLink url={n.url}>{n.text}</MaybeLink>} meta={n.when && !n.text.includes(n.when) ? n.when : undefined} />
              ))}
            </EntityList>
          ) : (
            <p className="text-sm text-ink-muted">Na příští týden nejsou známé žádné termíny.</p>
          )}
        </section>
        <section className="motion-card min-w-0" style={staggerStyle(5)}>
          <ForecastPanel forecasts={content.forecasts} />
        </section>
      </div>

      {content.focus.length ? (
        <section className="motion-card" style={staggerStyle(6)}>
          <BlockTitle>Zaměř se</BlockTitle>
          <FactList items={content.focus} tone="neutral" />
        </section>
      ) : null}
    </div>
  );
}
