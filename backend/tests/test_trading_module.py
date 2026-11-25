"""MRK-141: modul Trading – read-only přehled ze standa-trading API (falešné API, nikdy síť), bez AI (MRK-60)."""
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import trading_notifications as tn  # noqa: E402
from modules.trading import service  # noqa: E402

TODAY = date(2026, 11, 25)
SECRET_URL = "http://trading-api:8000"
SECRET_KEY = "super-secret-trading-key"


def account(name, total, ret, active=True, reason=None):
    return {"name": name, "active": active, "disabled_reason": reason, "total": total, "return_pct": ret}


def api(health=None, report=None, summary=None):
    data = {
        "/health": health if health is not None else {
            "ok": True, "data_until": "2026-11-24",
            "last_runs": [{"job": "collect", "status": "ok", "finished_at": "2026-11-24T22:05:00Z"},
                          {"job": "trade", "status": "ok", "finished_at": "2026-11-24T22:10:00Z", "secret": "x"}]},
        "/report": report if report is not None else {
            "date": "2026-11-24",
            "accounts": [account("buy_hold_spy", 9967.77, -0.32), account("ema_trailing", 9972.11, -0.28),
                         account("sma_cross", 10011.96, 0.12)],
            "fills": [{"strategy": "sma_cross", "side": "buy", "symbol": "AAPL", "qty": 2, "price": 190.1},
                      {"strategy": "x", "side": "hold", "symbol": "MSFT", "qty": 1}],
            "signals": [{"strategy": "ema_trailing", "action": "sell", "symbol": "XOM"}],
        },
        "/summary": summary if summary is not None else [
            account("ema_trailing", None, None), account("sma_cross", None, None),
            account("rsi_revert", None, None, active=False, reason="drawdown 12 % > 10 %"),
        ],
        # MRK-141: tvary ze skutečného API (Standa, 2026-11-25)
        "/equity/sma_cross?days=90": [{"date": "2026-11-23", "total": 10011.96, "drawdown_pct": 0.0},
                                      {"date": "2026-11-20", "total": 10000.0, "drawdown_pct": 0.0},
                                      {"date": "nope", "total": 1}],
        "/equity/buy_hold_spy?days=90": [{"date": "2026-11-20", "total": 10000.0, "drawdown_pct": 0.0},
                                         {"date": "2026-11-23", "total": 9967.77, "drawdown_pct": -0.32}],
        "/positions": [{"strategy": "sma_cross", "symbol": "AAPL", "qty": 2, "avg_price": 347.9539,
                        "opened_date": "2026-11-23", "last_close": 354.07, "last_date": "2026-11-24", "pnl_pct": 1.76,
                        "pnl_usd": 12.23, "internal": "x"}],
        "/orders?status=pending": [{"id": 19, "strategy": "ema_trailing", "side": "buy", "symbol": "COST", "qty": 1,
                                    "origin": "signal", "status": "pending", "created_date": "2026-11-24",
                                    "fill_date": None, "fill_price": None, "fee": None, "cancel_reason": None}],
        "/orders?status=filled": [{"id": 16, "strategy": "ema_trailing", "side": "sell", "symbol": "XOM", "qty": 6,
                                   "origin": "signal", "status": "filled", "created_date": "2026-11-23",
                                   "fill_date": "2026-11-24", "fill_price": 157.3413, "fee": 1.0, "cancel_reason": None}],
        "/report?date=2026-11-23": {"date": "2026-11-23", "accounts": [account("sma_cross", 10011.96, 0.12)],
                                    "fills": [], "signals": []},
    }
    return lambda path: data[path]


class OverviewTestCase(unittest.TestCase):
    def test_full_overview(self):
        out = service.overview(fetch=api(), today=TODAY)
        self.assertEqual((out["configured"], out["status"], out["report_date"]), (True, "ok", "2026-11-24"))
        names = [s["name"] for s in out["strategies"]]
        self.assertEqual(names, ["sma_cross", "ema_trailing", "rsi_revert", "buy_hold_spy"], "nejlepší nahoře, SPY poslední")
        sma = out["strategies"][0]
        self.assertEqual((sma["total"], sma["return_pct"], sma["vs_spy"], sma["active"]), (10011.96, 0.12, 0.44, True))
        rsi = next(s for s in out["strategies"] if s["name"] == "rsi_revert")
        self.assertEqual((rsi["active"], rsi["disabled_reason"], rsi["total"]), (False, "drawdown 12 % > 10 %", None))
        self.assertEqual(out["strategies"][-1]["label"], "SPY (benchmark)")
        self.assertIsNone(out["strategies"][-1]["vs_spy"])
        self.assertEqual(out["best"], "sma_cross")
        self.assertEqual(out["fills"], [{"strategy": "sma_cross", "side": "buy", "symbol": "AAPL", "qty": 2.0}],
                         "jen známá pole, neplatný side zahozen")
        self.assertEqual(out["signals"], [{"strategy": "ema_trailing", "action": "sell", "symbol": "XOM"}])
        self.assertEqual(out["health"], {"ok": True, "data_until": "2026-11-24", "stale": False, "runs": [
            {"job": "collect", "status": "ok", "at": "2026-11-24T22:05:00Z"},
            {"job": "trade", "status": "ok", "at": "2026-11-24T22:10:00Z"}]})

    def test_equity_positions_and_orders(self):
        out = service.overview(fetch=api(), today=TODAY)
        self.assertEqual(out["equity"]["sma_cross"], [
            {"date": "2026-11-20", "total": 10000.0, "drawdown_pct": 0.0},
            {"date": "2026-11-23", "total": 10011.96, "drawdown_pct": 0.0}], "seřazené, neplatný bod zahozen")
        self.assertEqual(set(out["equity"]), {"sma_cross", "buy_hold_spy"}, "strategie bez křivky (výpadek) chybí")
        self.assertEqual(out["positions"], [{"strategy": "sma_cross", "symbol": "AAPL", "qty": 2.0, "avg_price": 347.9539,
                                             "last_close": 354.07, "opened_date": "2026-11-23", "last_date": "2026-11-24",
                                             "pnl_pct": 1.76, "pnl_usd": 12.23}], "jen známá pole")
        self.assertEqual([o["symbol"] for o in out["orders_pending"]], ["COST"])
        self.assertEqual(out["orders_filled"][0], {"id": 16, "strategy": "ema_trailing", "side": "sell", "symbol": "XOM",
                                                   "qty": 6.0, "created_date": "2026-11-23", "fill_date": "2026-11-24",
                                                   "fill_price": 157.3413, "fee": 1.0})

    def test_optional_endpoint_down_hides_only_its_section(self):
        base = api()

        def partial(path):
            if path.startswith("/positions") or path.startswith("/equity"):
                raise tn.TradingApiError("Trading API vrátilo chybu 500.")
            return base(path)
        out = service.overview(fetch=partial, today=TODAY)
        self.assertEqual(out["status"], "ok")
        self.assertIsNone(out["positions"])
        self.assertEqual(out["equity"], {})
        self.assertEqual(len(out["orders_pending"]), 1)

    def test_report_for_a_chosen_day(self):
        out = service.overview(fetch=api(), today=TODAY, report_date="2026-11-23")
        self.assertEqual(out["report_date"], "2026-11-23")
        self.assertEqual(service.parse_report_date("2026-11-23"), "2026-11-23")
        for bad in ("23.11.2026", "2026-13-01", "../x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                service.parse_report_date(bad)
        self.assertIsNone(service.parse_report_date(""))

    def test_stale_data_and_failed_run(self):
        h = {"ok": False, "data_until": "2026-11-17", "last_runs": [{"job": "collect", "status": "error"}]}
        out = service.overview(fetch=api(health=h), today=TODAY)
        self.assertEqual((out["health"]["ok"], out["health"]["stale"]), (False, True))
        self.assertEqual(out["health"]["runs"], [{"job": "collect", "status": "error", "at": None}])

    def test_not_configured(self):
        with mock.patch.dict(os.environ, {"TRADING_API_URL": ""}), \
                mock.patch.object(tn, "_http_get", side_effect=AssertionError("no call")):
            self.assertEqual(service.overview(), {"configured": False, "status": "not_configured"})

    def test_unavailable_is_a_readable_state(self):
        def down(path):
            raise tn.TradingApiError("Trading API neodpovídá (URLError). Zkontroluj kontejnery standa-trading.")
        out = service.overview(fetch=down, today=TODAY)
        self.assertEqual(out["status"], "unavailable")
        self.assertIn("neodpovídá", out["message"])

    def test_invalid_shape_is_a_readable_state(self):
        for bad in ({"report": ["x"]}, {"summary": {"not": "a list"}}, {"report": {"date": "24.11.2026"}}):
            with self.subTest(bad=bad):
                out = service.overview(fetch=api(**bad), today=TODAY)
                self.assertEqual((out["status"], out["message"]), ("invalid", tn.INVALID_RESPONSE))


class SecurityAndAiTestCase(unittest.TestCase):
    def test_rest_never_leaks_url_or_key(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        import auth_service
        import bcrypt
        import main
        from database import Base

        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.addCleanup(engine.dispose)
        with mock.patch.object(auth_service, "SessionLocal", Session), mock.patch.object(main, "SessionLocal", Session), \
                mock.patch.dict(os.environ, {"TRADING_API_URL": SECRET_URL, "TRADING_API_KEY": SECRET_KEY}), \
                mock.patch.object(tn, "_http_get", side_effect=tn.TradingApiError("Trading API odmítá klíč – zkontroluj TRADING_API_KEY v .env Hubu i standa-trading.")), \
                mock.patch.object(service.tn, "fetch_json", side_effect=tn.TradingApiError("Trading API odmítá klíč – zkontroluj TRADING_API_KEY v .env Hubu i standa-trading.")), \
                mock.patch.object(auth_service, "_failed_attempts", {}), \
                mock.patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode()):
            client = TestClient(main.app)
            self.assertEqual(client.get("/trading").status_code, 401, "jen po přihlášení")
            self.assertEqual(client.post("/auth/login", json={"pin": "4821"}).status_code, 200)
            r = client.get("/trading")
            self.assertEqual(client.get("/trading?date=23.11.2026").status_code, 400, "neplatné datum reportu")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "unavailable")
        self.assertNotIn(SECRET_URL, r.text)
        self.assertNotIn(SECRET_KEY, r.text)

    def test_module_has_no_ai_surface(self):
        import module_registry
        import tool_registry
        mod = next(m for m in module_registry.MODULES if m.id == "trading")
        self.assertNotIn("ai_context", mod.capabilities, "finance do AI nejde (MRK-60)")
        self.assertEqual(mod.integrations.context, ())
        self.assertFalse([t for t in tool_registry.TOOL_SPECS if "trading" in t.name])


if __name__ == "__main__":
    unittest.main()
