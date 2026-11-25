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
