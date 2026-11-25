// MRK-141: Trading – formát čísel, popisky obchodů a signálů, HUD jádro.
import assert from "node:assert/strict";
import { test } from "node:test";

import { BENCHMARK_COLOR, SERIES_COLORS, chartModel, fillLabel, linePath, maxDrawdown, pct, pnlByStrategy, price, returnTone, seriesColors, shortDate, signalLabel, tradingCore, usd, usdSigned } from "./lib.ts";

const s = (name, ret, vs, extra = {}) => ({ name, label: name, benchmark: false, total: 10000, return_pct: ret, vs_spy: vs, active: true, disabled_reason: null, ...extra });
const ok = (strategies, health = { ok: true, data_until: "2026-11-24", stale: false, runs: [] }) => ({
  configured: true, status: "ok", health, report_date: "2026-11-24", strategies, fills: [], signals: [], best: null,
});

test("money and percent formatting", () => {
  assert.equal(usd(10011.96), "10 012 USD");
  assert.equal(usd(null), "–");
  assert.equal(pct(0.12), "+0,12 %");
  assert.equal(pct(-0.28), "−0,28 %");
  assert.equal(pct(0), "0,00 %");
  assert.equal(returnTone(0.1), "success");
  assert.equal(returnTone(-0.1), "danger");
  assert.equal(returnTone(null), "neutral");
  assert.equal(shortDate("2026-11-04"), "4. 11.");
  assert.equal(shortDate("nope"), "–");
});

test("fill and signal labels", () => {
  assert.equal(fillLabel({ side: "buy", symbol: "AAPL", qty: 2 }), "nákup 2× AAPL");
  assert.equal(fillLabel({ side: "sell", symbol: "XOM", qty: 1.5 }), "prodej 1,5× XOM");
  assert.equal(signalLabel({ action: "sell", symbol: "XOM" }), "prodat XOM");
  assert.equal(signalLabel({ action: null, symbol: "SPY" }), "signál SPY");
});

test("hud core sentence and mood", () => {
  const bench = { ...s("buy_hold_spy", -0.3, null), benchmark: true };
  assert.deepEqual(tradingCore(ok([s("a", 0.1, 0.4), s("b", -0.5, -0.2), bench])),
    { total: 2, lit: 1, mood: "calm", line: "1 z 2 strategií poráží SPY." });
  assert.equal(tradingCore(ok([s("a", 0.1, 0.4), bench])).mood, "done");
  const off = tradingCore(ok([s("a", 0.1, 0.4), s("c", -9, -8, { active: false })]));
  assert.equal(off.mood, "alert");
  assert.match(off.line, /1 vypnutá pojistkou/);
  assert.match(tradingCore(ok([s("a", 0.1, 0.4)], { ok: true, data_until: "2026-11-01", stale: true, runs: [] })).line, /data jsou stará/);
  assert.deepEqual(tradingCore({ configured: false, status: "not_configured" }), { total: 1, lit: 0, mood: "alert", line: "Trading API není nastavené." });
  assert.equal(tradingCore({ configured: true, status: "unavailable", message: "x" }).line, "Paper trading teď nejde ověřit.");
});

// MRK-141: graf kapitálu, pozice
test("colors follow the strategy name, benchmark is grey", () => {
  const a = seriesColors(["sma_cross", "buy_hold_spy", "ema_trailing"]);
  assert.deepEqual(a, { ema_trailing: SERIES_COLORS[0], sma_cross: SERIES_COLORS[1], buy_hold_spy: BENCHMARK_COLOR });
  assert.equal(seriesColors(["sma_cross", "ema_trailing"]).sma_cross, a.sma_cross, "pořadí na vstupu barvu nemění");
});

test("chart model: shared date axis, one y scale with nice ticks", () => {
  const eq = {
    sma_cross: [{ date: "2026-11-20", total: 10000, drawdown_pct: 0 }, { date: "2026-11-24", total: 10056.41, drawdown_pct: 0 }],
    buy_hold_spy: [{ date: "2026-11-20", total: 10000, drawdown_pct: 0 }, { date: "2026-11-23", total: 9967.77, drawdown_pct: -0.32 }],
  };
  const m = chartModel(eq, 600, 240);
  assert.deepEqual(m.dates, ["2026-11-20", "2026-11-23", "2026-11-24"]);
  assert.ok(m.yMin <= 9967.77 && m.yMax >= 10056.41);
  assert.ok(m.yTicks.length >= 3 && m.yTicks.length <= 7, String(m.yTicks));
  const sma = m.series.find((s) => s.name === "sma_cross");
  assert.equal(sma.points[0].x, 56, "první den na levém okraji");
  assert.equal(sma.points[1].x, 588, "poslední den na pravém okraji");
  assert.ok(sma.points[1].y < sma.points[0].y, "vyšší kapitál = výš");
  assert.equal(linePath([{ x: 1, y: 2 }, { x: 3, y: 4 }]), "M1,2 L3,4");
  assert.equal(chartModel({ a: [{ date: "2026-11-20", total: 1, drawdown_pct: 0 }] }, 600, 240), null, "jeden den = bez grafu");
});

test("drawdown, position P&L and money", () => {
  assert.equal(maxDrawdown([{ date: "a", total: 1, drawdown_pct: 0 }, { date: "b", total: 1, drawdown_pct: -2.5 }]), -2.5);
  assert.equal(maxDrawdown([]), null);
  const pos = (strategy, pnl_usd) => ({ strategy, symbol: "X", qty: 1, avg_price: 1, last_close: 1, opened_date: null, last_date: null, pnl_pct: 0, pnl_usd });
  assert.deepEqual(pnlByStrategy([pos("sma_cross", 12.23), pos("sma_cross", -24.3), pos("ema_trailing", 1.27)]),
    [{ strategy: "ema_trailing", pnl_usd: 1.27, count: 1 }, { strategy: "sma_cross", pnl_usd: -12.07, count: 2 }]);
  assert.equal(usdSigned(12.23), "+12,23 USD");
  assert.equal(usdSigned(-24.3), "−24,30 USD");
  assert.equal(price(347.9539), "347,95");
});
