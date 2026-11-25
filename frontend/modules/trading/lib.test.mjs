// MRK-141: Trading – formát čísel, popisky obchodů a signálů, HUD jádro.
import assert from "node:assert/strict";
import { test } from "node:test";

import { fillLabel, pct, returnTone, shortDate, signalLabel, tradingCore, usd } from "./lib.ts";

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
