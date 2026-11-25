/**
 * Trading (MRK-141) – čisté funkce stránky paper tradingu (testy: lib.test.mjs). Data = `GET /trading`
 * (backend modules/trading/service.overview, read-only API stacku standa-trading).
 */
export type TradingStrategy = {
  name: string;
  label: string;
  benchmark: boolean;
  total: number | null;
  return_pct: number | null;
  vs_spy: number | null;
  active: boolean;
  disabled_reason: string | null;
};
export type TradingFill = { strategy: string | null; side: "buy" | "sell"; symbol: string; qty: number | null };
export type TradingSignal = { strategy: string | null; action: string | null; symbol: string };
export type TradingRun = { job: string; status: string | null; at: string | null };
export type TradingHealth = { ok: boolean; data_until: string | null; stale: boolean; runs: TradingRun[] };

export type EquityPoint = { date: string; total: number; drawdown_pct: number | null };
export type TradingPosition = {
  strategy: string | null; symbol: string; qty: number | null; avg_price: number | null; last_close: number | null;
  opened_date: string | null; last_date: string | null; pnl_pct: number | null; pnl_usd: number | null;
};
export type TradingOrder = {
  id: number | null; strategy: string | null; side: "buy" | "sell"; symbol: string; qty: number | null;
  created_date: string | null; fill_date: string | null; fill_price: number | null; fee: number | null;
};

export type TradingOverview =
  | { configured: false; status: "not_configured" }
  | { configured: true; status: "unavailable" | "invalid"; message: string }
  | {
      configured: true;
      status: "ok";
      health: TradingHealth;
      report_date: string | null;
      strategies: TradingStrategy[];
      fills: TradingFill[];
      signals: TradingSignal[];
      best: string | null;
      /** MRK-141: doplňky z dalších endpointů – null / chybějící klíč = endpoint teď nedal data */
      equity?: Record<string, EquityPoint[]>;
      positions?: TradingPosition[] | null;
      orders_pending?: TradingOrder[] | null;
      orders_filled?: TradingOrder[] | null;
    };

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

const nbsp = " ";

/** „10 012 USD“ (celé dolary, mezery po tisících). */
export function usd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "–";
  return `${Math.round(value).toLocaleString("cs-CZ").replace(/\s/g, nbsp)}${nbsp}USD`;
}

/** „+0,12 %“ / „−0,28 %“ (pravé minus). */
export function pct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")}${nbsp}%`;
}

export function returnTone(value: number | null | undefined): Tone {
  if (value == null || value === 0) return "neutral";
  return value > 0 ? "success" : "danger";
}

/** „nákup 2× AAPL“ / „prodej 1,5× XOM“. */
export function fillLabel(f: Pick<TradingFill, "side" | "symbol" | "qty">): string {
  const qty = f.qty == null ? "" : `${String(f.qty).replace(".", ",")}× `;
  return `${f.side === "buy" ? "nákup" : "prodej"} ${qty}${f.symbol}`;
}

export function signalLabel(s: Pick<TradingSignal, "action" | "symbol">): string {
  const action = s.action === "buy" ? "koupit" : s.action === "sell" ? "prodat" : s.action ?? "signál";
  return `${action} ${s.symbol}`;
}

/** „23. 11.“ z YYYY-MM-DD; jinak „–“. */
export function shortDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  return m ? `${Number(m[3])}. ${Number(m[2])}.` : "–";
}

/** Věta a nálada HUD jádra (data-hud-core="trading"): kolik strategií poráží SPY, nebo co je špatně. */
export function tradingCore(o: TradingOverview): { total: number; lit: number; mood: "alert" | "done" | "calm"; line: string } {
  if (o.status !== "ok") {
    const line = o.status === "not_configured" ? "Trading API není nastavené." : "Paper trading teď nejde ověřit.";
    return { total: 1, lit: 0, mood: "alert", line };
  }
  const strategies = o.strategies.filter((s) => !s.benchmark);
  const beating = strategies.filter((s) => (s.vs_spy ?? 0) > 0).length;
  const disabled = strategies.filter((s) => !s.active).length;
  const problems = !o.health.ok || o.health.stale;
  const parts = [
    strategies.length ? `${beating} z ${strategies.length} strategií poráží SPY` : "Žádná strategie",
    disabled ? `${disabled} vypnutá pojistkou` : null,
    problems ? (o.health.stale ? "data jsou stará" : "poslední běh selhal") : null,
  ].filter(Boolean);
  return {
    total: Math.max(1, strategies.length),
    lit: beating,
    mood: problems || disabled ? "alert" : strategies.length && beating === strategies.length ? "done" : "calm",
    line: `${parts.join(" · ")}.`,
  };
}

// ---------- graf kapitálu (MRK-141) ----------

/** Kategorické barvy pro tmavý povrch (dataviz palette, validováno na #050911: všech 6 kontrol PASS pro 4 sloty). */
export const SERIES_COLORS = ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b", "#0aac23", "#9887ef", "#eb6263"];
export const BENCHMARK_COLOR = "#8a94a6";

/** Barva podle STRATEGIE (abecední pořadí jmen), ne podle výnosu – filtr ani změna pořadí barvy nepřebarví.
 *  Benchmark je vždy šedý; víc strategií než barev = šedá (v praxi 3–4 strategie). */
export function seriesColors(names: string[], benchmark: string = "buy_hold_spy"): Record<string, string> {
  const out: Record<string, string> = {};
  [...names].filter((n) => n !== benchmark).sort((a, b) => a.localeCompare(b)).forEach((n, i) => { out[n] = SERIES_COLORS[i] ?? BENCHMARK_COLOR; });
  if (names.includes(benchmark)) out[benchmark] = BENCHMARK_COLOR;
  return out;
}

/** Největší propad (nejnižší drawdown_pct) křivky; bez dat null. */
export function maxDrawdown(points: EquityPoint[]): number | null {
  const dd = points.map((p) => p.drawdown_pct).filter((v): v is number => typeof v === "number");
  return dd.length ? Math.min(...dd) : null;
}

export type ChartSeries = { name: string; points: { x: number; y: number; date: string; total: number }[] };
export type ChartModel = { dates: string[]; series: ChartSeries[]; yMin: number; yMax: number; yTicks: number[] };

/** Body grafu: osa X = společná řada dat (sjednocená), osa Y = kapitál v USD s okrajem; jedna osa, žádná druhá škála. */
export function chartModel(equity: Record<string, EquityPoint[]>, width: number, height: number, pad = { l: 56, r: 12, t: 10, b: 24 }): ChartModel | null {
  const dates = [...new Set(Object.values(equity).flatMap((pts) => pts.map((p) => p.date)))].sort();
  const values = Object.values(equity).flatMap((pts) => pts.map((p) => p.total));
  if (dates.length < 2 || !values.length) return null;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const span = hi - lo || Math.max(1, hi * 0.01);
  lo -= span * 0.1;
  hi += span * 0.1;
  const step = niceStep((hi - lo) / 4);
  const yMin = Math.floor(lo / step) * step;
  const yMax = Math.ceil(hi / step) * step;
  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax + step / 2; v += step) yTicks.push(Math.round(v * 100) / 100);
  const xOf = (d: string) => pad.l + (dates.indexOf(d) / (dates.length - 1)) * (width - pad.l - pad.r);
  const yOf = (v: number) => pad.t + (1 - (v - yMin) / (yMax - yMin)) * (height - pad.t - pad.b);
  const series = Object.entries(equity).map(([name, pts]) => ({
    name, points: pts.map((p) => ({ x: round1(xOf(p.date)), y: round1(yOf(p.total)), date: p.date, total: p.total })),
  }));
  return { dates, series, yMin, yMax, yTicks };
}

function niceStep(raw: number): number {
  const pow = 10 ** Math.floor(Math.log10(raw || 1));
  const n = raw / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

/** Index dne pod ukazatelem: `ratio` = poloha v kreslicí ploše 0–1 (už bez okrajů os), `n` = počet dní. */
export function hoverIndex(ratio: number, n: number): number {
  if (n < 1 || !Number.isFinite(ratio)) return 0;
  return Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
}

/** SVG path z bodů. */
export function linePath(points: { x: number; y: number }[]): string {
  return points.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
}

/** P&L pozic po strategiích (USD), pro souhrn nad tabulkou. */
export function pnlByStrategy(positions: TradingPosition[]): { strategy: string; pnl_usd: number; count: number }[] {
  const map = new Map<string, { pnl_usd: number; count: number }>();
  for (const p of positions) {
    const k = p.strategy ?? "–";
    const cur = map.get(k) ?? { pnl_usd: 0, count: 0 };
    cur.pnl_usd += p.pnl_usd ?? 0;
    cur.count += 1;
    map.set(k, cur);
  }
  return [...map].map(([strategy, v]) => ({ strategy, pnl_usd: Math.round(v.pnl_usd * 100) / 100, count: v.count }))
    .sort((a, b) => a.strategy.localeCompare(b.strategy));
}

/** „+12,23 USD“ / „−24,30 USD“. */
export function usdSigned(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(2).replace(".", ",")}${nbsp}USD`;
}

/** Cena akcie „347,95“. */
export function price(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "–" : value.toFixed(2).replace(".", ",");
}
