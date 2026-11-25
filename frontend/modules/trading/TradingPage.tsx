"use client";

import { useState } from "react";
import { HudCore } from "@/components/jarvis/HudCore";
import {
  Button,
  Card,
  CardHeader,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  PageSection,
  StatusBadge,
  fieldClass,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { staggerStyle } from "@/lib/motion";
import { cx } from "@/lib/ui";
import { EquityChart } from "./EquityChart";
import {
  fillLabel, pct, pnlByStrategy, price, returnTone, shortDate, signalLabel, tradingCore, usd, usdSigned,
  type TradingOrder, type TradingOverview, type TradingPosition, type TradingStrategy,
} from "./lib";

/**
 * Trading (MRK-141): paper trading strategií proti SPY ze stacku standa-trading – jen čtení. Strategie (kapitál,
 * výnos, srovnání s benchmarkem, pojistka), obchody posledního dne, signály na další den a zdraví stacku.
 * Finance do AI nejde (MRK-60) – stránka je jediné místo, kde se data ukazují (kromě notifikací MRK-140).
 */
export default function TradingPage() {
  // MRK-141: report za vybraný den (`/report?date=`), jinak poslední
  const [reportDay, setReportDay] = useState("");
  const res = useApiResource<TradingOverview>(reportDay ? `/trading?date=${reportDay}` : "/trading");
  const data = res.data;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · Trading</HudLabel>}
        title="Trading"
        subtitle="Paper trading strategií proti SPY. Jen čtení ze standa-trading – nic se tu neobchoduje."
        actions={
          <Button variant="secondary" disabled={res.loading} onClick={() => void res.reload()}>
            Obnovit
          </Button>
        }
      />

      {res.loading && !data ? (
        <LoadingState lines={4} label="Načítám paper trading…" />
      ) : res.status === "error" || !data ? (
        <ErrorState message={res.error ?? "Přehled tradingu se nepodařilo načíst."} onRetry={() => void res.reload()} />
      ) : data.status === "not_configured" ? (
        <Card data-trading-setup="">
          <CardHeader title="Trading API ještě není nastavené" description="Hub čte stack standa-trading jen pro čtení." />
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">
            <li>Na serveru doplň do <code>.env.production</code> <code>TRADING_API_URL</code> (v Docker síti <code>http://trading-api:8000</code>) a <code>TRADING_API_KEY</code> ze standa-trading.</li>
            <li>Restartuj backend (<code>restart-v3.sh</code>) – stránka i notifikace se pak načtou samy.</li>
          </ol>
        </Card>
      ) : data.status !== "ok" ? (
        <Card data-trading-down="">
          <CardHeader title="Paper trading teď nejde ověřit" description={data.message} />
          <div className="mt-3">
            <Button size="sm" variant="secondary" onClick={() => void res.reload()}>Zkusit znovu</Button>
          </div>
        </Card>
      ) : (
        <div className="space-y-6">
          <HudCore module="trading" label="Jarvis · trading" {...tradingCore(data)} />

          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2" data-trading-health="">
            <StatusBadge tone={data.health.ok && !data.health.stale ? "success" : "warning"} dot={data.health.ok && !data.health.stale}>
              {!data.health.ok ? "Poslední běh selhal" : data.health.stale ? "Data jsou stará" : "Stack běží"}
            </StatusBadge>
            <span>Report z {shortDate(data.report_date)}</span>
            <span aria-hidden="true">·</span>
            <span>Data do {shortDate(data.health.data_until)}</span>
            <label className="ml-auto flex items-center gap-2 text-xs text-ink-muted">
              Report za den
              <input type="date" aria-label="Report za den" value={reportDay} max={data.health.data_until ?? undefined}
                onChange={(e) => setReportDay(e.target.value)} className={cx(fieldClass, "w-auto py-1")} />
            </label>
            {reportDay ? <Button size="sm" variant="ghost" onClick={() => setReportDay("")}>Nejnovější</Button> : null}
          </div>

          {/* MRK-141: křivka kapitálu všech strategií proti SPY (90 dní) */}
          {data.equity && Object.keys(data.equity).length ? (
            <Card as="section" aria-labelledby="trading-equity">
              <CardHeader as="h2" title={<span id="trading-equity">Vývoj kapitálu</span>} description="Posledních 90 dní, všechny strategie proti SPY (čárkovaně)." />
              <div className="mt-3"><EquityChart equity={data.equity} strategies={data.strategies} /></div>
            </Card>
          ) : null}

          <PageSection labelledBy="trading-strategies" title="Strategie" description="Seřazené podle výnosu; benchmark SPY je měřítko (buy & hold).">
            {data.strategies.length ? (
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Strategie">
                {data.strategies.map((s, i) => <StrategyCard key={s.name} s={s} best={s.name === data.best} idx={i} />)}
              </ul>
            ) : (
              <EmptyState compact>Standa-trading zatím nemá žádnou strategii.</EmptyState>
            )}
          </PageSection>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card as="section" aria-labelledby="trading-fills">
              <CardHeader as="h2" title={<span id="trading-fills">Obchody {shortDate(data.report_date)}</span>} description="Co strategie v posledním obchodním dni koupily a prodaly." />
              {data.fills.length ? (
                <ul className="mt-2 divide-y divide-line-subtle" aria-label="Obchody">
                  {data.fills.map((f, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span className="flex min-w-0 items-center gap-2">
                        <StatusBadge tone={f.side === "buy" ? "success" : "warning"}>{f.side === "buy" ? "Nákup" : "Prodej"}</StatusBadge>
                        <span className="truncate text-ink">{fillLabel(f)}</span>
                      </span>
                      <span className="shrink-0 text-xs text-ink-muted">{f.strategy ?? ""}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState compact className="mt-2">Žádné obchody.</EmptyState>
              )}
            </Card>
            <Card as="section" aria-labelledby="trading-signals">
              <CardHeader as="h2" title={<span id="trading-signals">Signály na další den</span>} description="Co strategie provedou při dalším otevření trhu." />
              {data.signals.length ? (
                <ul className="mt-2 divide-y divide-line-subtle" aria-label="Signály">
                  {data.signals.map((s, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 py-2 text-sm">
                      <span className="truncate text-ink">{signalLabel(s)}</span>
                      <span className="shrink-0 text-xs text-ink-muted">{s.strategy ?? ""}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState compact className="mt-2">Žádné nové signály.</EmptyState>
              )}
            </Card>
          </div>

          {data.positions ? <Positions positions={data.positions} /> : null}

          {data.orders_pending || data.orders_filled ? (
            <div className="grid gap-6 lg:grid-cols-2">
              {data.orders_pending ? (
                <OrdersCard id="trading-pending" title="Čekající pokyny" description="Provedou se při dalším otevření trhu." empty="Žádné čekající pokyny." orders={data.orders_pending} />
              ) : null}
              {data.orders_filled ? (
                <OrdersCard id="trading-filled" title="Historie obchodů" description="Posledních 30 provedených pokynů." empty="Zatím žádné provedené obchody." orders={data.orders_filled} filled />
              ) : null}
            </div>
          ) : null}

          {data.health.runs.length ? (
            <Card as="section" aria-labelledby="trading-runs">
              <CardHeader as="h2" title={<span id="trading-runs">Poslední běhy</span>} description="Úlohy stacku standa-trading (sběr dat, obchodování, report)." />
              <ul className="mt-2 flex flex-wrap gap-2" aria-label="Poslední běhy">
                {data.health.runs.map((r, i) => (
                  <li key={i}>
                    <StatusBadge tone={r.status === "error" ? "danger" : r.status === "ok" ? "success" : "neutral"}>
                      {r.job}{r.status ? ` · ${r.status}` : ""}
                    </StatusBadge>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      )}
    </ContentContainer>
  );
}

function StrategyCard({ s, best, idx }: { s: TradingStrategy; best: boolean; idx: number }) {
  return (
    <Card
      as="li"
      data-trading-strategy={s.name}
      style={staggerStyle(idx)}
      className={cx("motion-card flex min-w-0 flex-col gap-2", s.benchmark && "border-dashed", !s.active && "opacity-80", best && "border-success/50")}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {s.benchmark ? <StatusBadge tone="neutral">Benchmark</StatusBadge> : null}
        {best ? <StatusBadge tone="success">Nejlepší vs SPY</StatusBadge> : null}
        {!s.active ? <StatusBadge tone="danger">Vypnuta pojistkou</StatusBadge> : null}
      </div>
      <h3 className="truncate font-display text-base font-semibold tracking-[0.04em] text-ink">{s.label}</h3>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-display text-2xl font-semibold tabular-nums text-ink">{usd(s.total)}</span>
        <StatusBadge tone={returnTone(s.return_pct)}>{pct(s.return_pct)}</StatusBadge>
      </div>
      {s.vs_spy != null ? (
        <p className="text-xs text-ink-muted">vs SPY <b className={cx("font-semibold tabular-nums", s.vs_spy >= 0 ? "text-success" : "text-danger")}>{pct(s.vs_spy)}</b></p>
      ) : null}
      {s.disabled_reason ? <p className="text-xs text-ink-muted">Pojistka: {s.disabled_reason}</p> : null}
    </Card>
  );
}

/** MRK-141: otevřené pozice s aktuálním P&L (`/positions`), souhrn P&L po strategiích nad seznamem. */
function Positions({ positions }: { positions: TradingPosition[] }) {
  const sums = pnlByStrategy(positions);
  return (
    <Card as="section" aria-labelledby="trading-positions" data-trading-positions="">
      <CardHeader as="h2" title={<span id="trading-positions">Otevřené pozice</span>} description="Nákupní cena proti poslední závěrečné ceně." />
      {positions.length ? (
        <>
          <dl className="mt-2 flex flex-wrap gap-2" aria-label="P&L po strategiích">
            {sums.map((s) => (
              <div key={s.strategy} className="flex items-baseline gap-1.5 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2.5 py-1.5">
                <dt className="text-xs text-ink-muted">{s.strategy} · {s.count}</dt>
                <dd className={cx("text-sm font-semibold tabular-nums", s.pnl_usd >= 0 ? "text-success" : "text-danger")}>{usdSigned(s.pnl_usd)}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[34rem] text-left text-sm tabular-nums" aria-label="Pozice">
              <thead>
                <tr className="text-xs text-ink-muted">
                  <th className="py-1.5 pr-3 font-normal">Symbol</th><th className="py-1.5 pr-3 font-normal">Strategie</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Ks</th><th className="py-1.5 pr-3 text-right font-normal">Nákup</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Teď</th><th className="py-1.5 text-right font-normal">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => (
                  <tr key={`${p.strategy}-${p.symbol}-${i}`} className="border-t border-line-subtle">
                    <td className="py-1.5 pr-3 font-medium text-ink">{p.symbol}</td>
                    <td className="py-1.5 pr-3 text-ink-muted">{p.strategy ?? "–"}</td>
                    <td className="py-1.5 pr-3 text-right">{p.qty ?? "–"}</td>
                    <td className="py-1.5 pr-3 text-right">{price(p.avg_price)}</td>
                    <td className="py-1.5 pr-3 text-right">{price(p.last_close)}</td>
                    <td className={cx("py-1.5 text-right", (p.pnl_usd ?? 0) >= 0 ? "text-success" : "text-danger")}>
                      {pct(p.pnl_pct)} <span className="text-xs">({usdSigned(p.pnl_usd)})</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <EmptyState compact className="mt-2">Žádné otevřené pozice.</EmptyState>
      )}
    </Card>
  );
}

function OrdersCard({ id, title, description, empty, orders, filled }: { id: string; title: string; description: string; empty: string; orders: TradingOrder[]; filled?: boolean }) {
  return (
    <Card as="section" aria-labelledby={id}>
      <CardHeader as="h2" title={<span id={id}>{title}</span>} description={description} />
      {orders.length ? (
        <ul className="mt-2 divide-y divide-line-subtle" aria-label={title}>
          {orders.map((o, i) => (
            <li key={o.id ?? i} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="flex min-w-0 items-center gap-2">
                <StatusBadge tone={o.side === "buy" ? "success" : "warning"}>{o.side === "buy" ? "Nákup" : "Prodej"}</StatusBadge>
                <span className="truncate text-ink">{fillLabel(o)}{filled && o.fill_price != null ? ` @ ${price(o.fill_price)}` : ""}</span>
              </span>
              <span className="shrink-0 text-right text-xs text-ink-muted">
                {o.strategy ?? ""}<br />{shortDate(filled ? o.fill_date : o.created_date)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState compact className="mt-2">{empty}</EmptyState>
      )}
    </Card>
  );
}
