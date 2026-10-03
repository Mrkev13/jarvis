"use client";

import Link from "next/link";
import { safeHref } from "@/lib/briefing";
import { staggerStyle } from "@/lib/motion";
import {
  confidenceLabel,
  trendTone,
  type ForecastView,
  type WeeklyContent,
  type WeeklyItem,
} from "@/lib/weeklyReview";

function MaybeLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = safeHref(url);
  return href ? (
    <Link href={href} className="block rounded-xl motion-hover-lift">
      {children}
    </Link>
  ) : (
    <>{children}</>
  );
}

function Block({ title, hint, children, index }: { title: string; hint?: string; children: React.ReactNode; index: number }) {
  return (
    <section className="motion-card min-w-0" style={staggerStyle(index)}>
      <h3 className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
        {title}
        {hint ? <span className="normal-case tracking-normal text-zinc-600"> · {hint}</span> : null}
      </h3>
      {children}
    </section>
  );
}

function FactRow({ item, tone }: { item: WeeklyItem; tone: "good" | "bad" | "plain" }) {
  const cls =
    tone === "good"
      ? "bg-emerald-500/10 border-emerald-400/30"
      : tone === "bad"
        ? "bg-red-500/10 border-red-400/30"
        : "bg-zinc-950/40 border-zinc-800";
  return (
    <li>
      <MaybeLink url={item.url}>
        <div className={`rounded-xl border p-2.5 text-sm ${cls}`}>
          <div className="break-words text-zinc-100">{item.text}</div>
          {item.when && !item.text.includes(item.when) ? <div className="text-xs text-zinc-500 mt-0.5">{item.when}</div> : null}
        </div>
      </MaybeLink>
    </li>
  );
}

function ComparisonRow({ item }: { item: WeeklyItem }) {
  const m = item.metric;
  if (!m) return <FactRow item={item} tone="plain" />;
  const t = trendTone(m.trend);
  const color = t.tone === "good" ? "text-emerald-300" : t.tone === "bad" ? "text-red-300" : "text-zinc-300";
  return (
    <li className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <span className="text-sm text-zinc-300">{m.label}</span>
        <span className={`text-sm font-semibold ${color}`}>
          {t.arrow ? <span aria-hidden="true">{t.arrow} </span> : null}
          {m.delta_text || "–"}
          {t.label ? <span className="sr-only"> ({t.label})</span> : null}
        </span>
      </div>
      <div className="text-xs text-zinc-500 mt-1">
        {m.cur_text}
        {m.prev_text !== null ? ` · ${m.prev_label} ${m.prev_text}` : ""}
        {m.note ? ` · ${m.note}` : ""}
      </div>
      {item.text && item.text !== m.label ? <div className="text-sm text-zinc-200 mt-1.5 break-words">{item.text}</div> : null}
    </li>
  );
}

function ForecastCard({ f }: { f: ForecastView }) {
  return (
    <li className="rounded-xl border border-dashed border-violet-400/40 bg-violet-500/5 p-3">
      <div className="flex items-center gap-2 flex-wrap mb-1.5">
        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full border bg-violet-500/15 border-violet-400/40 text-violet-200">
          Odhad / Forecast
        </span>
        <span className="text-[11px] text-violet-200/80">{confidenceLabel(f.confidence)}</span>
      </div>
      <p className="text-sm text-zinc-200 italic break-words">{f.statement}</p>
      {f.basis_labels.length || f.rule ? (
        <p className="text-xs text-zinc-500 mt-1.5 break-words">
          Podklad: {[f.rule, ...f.basis_labels].filter(Boolean).join(" · ")}
        </p>
      ) : null}
    </li>
  );
}

/** Obsah týdenního přehledu: fakta, srovnání, příští týden, odhady (vizuálně oddělené), zaměření. */
export default function WeeklyReviewView({ content, isFallback = false }: { content: WeeklyContent; isFallback?: boolean }) {
  let i = 0;
  return (
    <div className="space-y-5">
      <div className="motion-card" style={staggerStyle(i++)}>
        {isFallback ? (
          <p className="text-xs text-amber-200/90 mb-1.5">Náhled z dat bez AI – zatím bez vytvořeného přehledu.</p>
        ) : null}
        <h2 className="text-xl md:text-2xl font-semibold break-words">{content.headline}</h2>
        <p className="text-zinc-300 mt-2 leading-relaxed">{content.summary}</p>
      </div>

      {content.wins.length || content.concerns.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {content.wins.length ? (
            <Block title="Co se povedlo" hint="fakta" index={i++}>
              <ul className="space-y-2">
                {content.wins.map((w) => <FactRow key={w.ref} item={w} tone="good" />)}
              </ul>
            </Block>
          ) : null}
          {content.concerns.length ? (
            <Block title="Na co pozor" hint="fakta" index={i++}>
              <ul className="space-y-2">
                {content.concerns.map((c) => <FactRow key={c.ref} item={c} tone="bad" />)}
              </ul>
            </Block>
          ) : null}
        </div>
      ) : null}

      {content.comparisons.length ? (
        <Block title="Srovnání s minulým týdnem" hint="spočítáno z dat" index={i++}>
          <ul className="grid gap-2 sm:grid-cols-2">
            {content.comparisons.map((c) => <ComparisonRow key={c.ref} item={c} />)}
          </ul>
        </Block>
      ) : null}

      {content.next_week.length ? (
        <Block title="Příští týden" hint="známé závazky" index={i++}>
          <ul className="space-y-2">
            {content.next_week.map((n) => <FactRow key={n.ref} item={n} tone="plain" />)}
          </ul>
        </Block>
      ) : null}

      <Block title="Odhady" hint="nejsou fakta" index={i++}>
        {content.forecasts.length ? (
          <ul className="space-y-2">
            {content.forecasts.map((f) => <ForecastCard key={f.ref} f={f} />)}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500">Žádný odhad – data na něj nestačí.</p>
        )}
      </Block>

      {content.focus.length ? (
        <Block title="Zaměř se" index={i++}>
          <ul className="space-y-2">
            {content.focus.map((f) => <FactRow key={f.ref} item={f} tone="plain" />)}
          </ul>
        </Block>
      ) : null}
    </div>
  );
}
