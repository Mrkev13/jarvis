"""MRK-140: notifikace z paper tradingu – falešné API, nikdy síť."""
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import trading_notifications as tn
from database import Base
from finance_ai_policy import is_finance_notification
from models import Assignment, Notification, Subject
from notifications_service import NotificationCandidate, generate_notifications, list_notifications

TODAY = date(2026, 11, 24)


def account(name, total, ret, active=True, reason=None):
    return {"name": name, "active": active, "disabled_reason": reason, "total": total, "return_pct": ret}


def api(health=None, report=None, summary=None):
    data = {
        "/health": health if health is not None else {"ok": True, "last_runs": [], "data_until": "2026-11-23"},
        "/report": report if report is not None else {
            "date": "2026-11-23",
            "accounts": [account("sma_cross", 10011.96, 0.12), account("ema_trailing", 9972.11, -0.28),
                         account("buy_hold_spy", 9967.77, -0.32)],
            "fills": [{"strategy": "sma_cross", "side": "buy", "symbol": "AAPL", "qty": 2},
                      {"strategy": "buy_hold_spy", "side": "buy", "symbol": "SPY", "qty": 13}],
            "signals": [{"strategy": "ema_trailing", "action": "sell", "symbol": "XOM"}],
        },
        "/summary": summary if summary is not None else [],
    }

    def fetch(path):
        return data[path]
    return fetch


def failing(path):
    raise tn.TradingApiError("Trading API neodpovídá (URLError). Zkontroluj kontejnery standa-trading.")


def candidates(fetch, today=TODAY):
    return tn.trading_candidates(NotificationCandidate, today, fetch=fetch)


class TradingCandidatesTestCase(unittest.TestCase):
    def test_not_configured_does_nothing(self):
        with mock.patch.dict(os.environ, {"TRADING_API_URL": ""}), \
                mock.patch.object(tn, "_http_get", side_effect=AssertionError("no call")):
            self.assertEqual(tn.trading_candidates(NotificationCandidate, TODAY), [])

    def test_daily_report(self):
        [c] = candidates(api())
        self.assertEqual(c.dedupe_key, "trading_report:2026-11-23")
        self.assertEqual((c.area, c.severity, c.notification_type), ("finance", "info", "trading_report"))
        self.assertEqual(c.title, "Paper trading 23. 11.")
        self.assertIn("sma_cross: 10 012 USD (+0,12 %), vs SPY +0,44 %", c.message)
        self.assertIn("SPY (benchmark): 9 968 USD (-0,32 %)", c.message)
        self.assertIn("nákup 2× AAPL (sma_cross)", c.message)
        self.assertIn("Nové signály na další obchodní den: 1.", c.message)
        # páteční/pondělní report vydrží 4 dny
        self.assertEqual(c.expires_at, datetime(2026, 11, 27))

    def test_report_lists_at_most_six_fills(self):
        fills = [{"strategy": "s", "side": "sell", "symbol": f"T{i}", "qty": 1} for i in range(9)]
        rep = {"date": "2026-11-23", "accounts": [], "fills": fills, "signals": []}
        [c] = candidates(api(report=rep))
        self.assertIn("prodej 1× T5 (s) a dalších 3.", c.message)
        self.assertNotIn("T6", c.message)

    def test_old_or_missing_report_is_skipped(self):
        self.assertEqual(candidates(api(report={"date": None})), [])
        old = {"date": "2026-11-18", "accounts": [], "fills": [], "signals": []}
        self.assertEqual(candidates(api(report=old)), [])

    def test_api_down_gives_single_health_warning(self):
        [c] = candidates(failing)
        self.assertEqual((c.dedupe_key, c.severity, c.notification_type),
                         ("trading_health", "warning", "trading_health"))
        self.assertIn("neodpovídá", c.message)
        self.assertIsNone(c.expires_at)

    def test_failed_run_and_stale_data_merge_into_one_health(self):
        health = {"ok": False, "last_runs": [{"job": "collect", "status": "error"}], "data_until": "2026-11-13"}
        cs = candidates(api(health=health))
        hs = [c for c in cs if c.notification_type == "trading_health"]
        self.assertEqual(len(hs), 1)
        self.assertIn("'collect'", hs[0].message)
        self.assertIn("2026-11-13", hs[0].message)

    def test_weekend_data_is_not_stale(self):
        # pátek 20. 11. → středa 25. 11. = 5 dní, ještě v pořádku
        health = {"ok": True, "last_runs": [], "data_until": "2026-11-20"}
        cs = candidates(api(health=health), today=date(2026, 11, 25))
        self.assertFalse([c for c in cs if c.notification_type == "trading_health"])

    def test_kill_switch_alert_only_for_drawdown(self):
        summary = [
            account("ema_trailing", 6900, -31, active=False, reason="drawdown -31.2 % přes limit 30 % (2026-11-20)"),
            account("rsi_filter", None, None, active=False, reason="vyřazeno po backtestu (2026-11-21)"),
        ]
        alerts = [c for c in candidates(api(summary=summary)) if c.notification_type == "trading_alert"]
        self.assertEqual([a.dedupe_key for a in alerts], ["trading_disabled:ema_trailing"])
        self.assertEqual(alerts[0].severity, "important")
        self.assertEqual(alerts[0].expires_at, datetime(2026, 11, 24) + timedelta(days=14))

    def test_invalid_responses_give_health_warning_not_silence(self):
        # Regrese (review PR #111): neplatný tvar odpovědi = neověřený stav → health, nikdy prázdný seznam.
        bad = {
            "nečitelné datum": api(health={"ok": False, "last_runs": [{"job": "collect", "status": "error"}],
                                            "data_until": "nesmysl"}),
            "health není objekt": api(health=["ok"]),
            "report bez data jako text": api(report={"date": 20261123}),
            "summary není seznam": api(summary={"name": "x"}),
            "účet bez jména": api(summary=[{"active": False, "disabled_reason": "drawdown"}]),
            "účet bez výnosu": api(report={"date": "2026-11-23", "accounts": [{"name": "x", "total": 1}]}),
            "last_runs je text": api(health={"ok": False, "last_runs": "error", "data_until": "2026-11-23"}),
        }
        for label, fetch in bad.items():
            with self.subTest(label):
                [c] = candidates(fetch)
                self.assertEqual(c.dedupe_key, "trading_health")
                self.assertEqual(c.message, tn.INVALID_RESPONSE)

    def test_all_trading_notifications_are_hidden_from_ai(self):
        summary = [account("x", 1, -31, active=False, reason="drawdown")]
        for c in candidates(api(summary=summary)) + candidates(failing):
            self.assertTrue(is_finance_notification(c.area, c.notification_type))
            self.assertTrue(is_finance_notification(None, c.notification_type))


class TradingHttpTestCase(unittest.TestCase):
    """_http_get převádí chyby na bezpečný text (bez URL a klíče)."""

    def _raise(self, exc):
        with mock.patch.dict(os.environ, {"TRADING_API_URL": "http://trading-api:8000", "TRADING_API_KEY": "tajne"}), \
                mock.patch.object(tn.urllib.request, "urlopen", side_effect=exc):
            with self.assertRaises(tn.TradingApiError) as ctx:
                tn._http_get("/health")
        self.assertNotIn("tajne", str(ctx.exception))
        self.assertNotIn("trading-api", str(ctx.exception))
        return str(ctx.exception)

    def test_bad_key(self):
        err = tn.urllib.error.HTTPError("http://trading-api:8000/health", 401, "Unauthorized", {}, None)
        self.assertIn("odmítá klíč", self._raise(err))

    def test_connection_refused(self):
        self.assertIn("neodpovídá (URLError)", self._raise(tn.urllib.error.URLError("refused")))


class TradingInGenerateNotificationsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.env = mock.patch.dict(os.environ, {"TRADING_API_URL": "http://trading-api:8000"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.db.close()
        self.engine.dispose()

    def run_with(self, fetch, today=TODAY):
        with mock.patch.object(tn, "_http_get", side_effect=fetch):
            stats = generate_notifications(self.db, today=today)
        self.db.commit()
        return stats

    def open_keys(self):
        return {n.dedupe_key for n in self.db.query(Notification).filter(Notification.resolved == False)}  # noqa: E712

    def test_report_created_once_and_deduplicated(self):
        self.assertEqual(self.run_with(api())["created"], 1)
        self.assertEqual(self.run_with(api())["created"], 0)
        [n] = list_notifications(self.db, now=datetime(2026, 11, 24, 9))
        self.assertEqual(n["dedupe_key"], "trading_report:2026-11-23")
        self.assertEqual(n["area"], "finance")

    def test_health_resolves_itself_when_api_recovers(self):
        self.run_with(failing)
        self.assertIn("trading_health", self.open_keys())
        self.run_with(api())
        self.assertNotIn("trading_health", self.open_keys())
        self.assertIn("trading_report:2026-11-23", self.open_keys())

    def test_outage_then_invalid_response_keeps_health_until_real_recovery(self):
        # Regrese (review PR #111): výpadek → neplatná odpověď nesmí upozornění vyřešit, až zdravá odpověď.
        self.run_with(failing)
        self.assertIn("trading_health", self.open_keys())

        invalid = api(health={"ok": False, "last_runs": [{"job": "collect", "status": "error"}],
                              "data_until": "nesmysl"})
        stats = self.run_with(invalid)
        self.assertEqual(stats["resolved_irrelevant"], 0)
        self.assertIn("trading_health", self.open_keys())

        self.run_with(api())
        self.assertNotIn("trading_health", self.open_keys())

    def test_unexpected_error_keeps_health_and_other_notifications(self):
        subj = Subject(name="Test", code="", semester="", credits=0, active=True)
        self.db.add(subj)
        self.db.flush()
        self.db.add(Assignment(title="Úkol", description="", due_date=TODAY + timedelta(days=2),
                               priority="medium", status="todo", subject_id=subj.id))
        self.db.commit()
        self.run_with(failing)

        with mock.patch.object(tn, "trading_candidates", side_effect=RuntimeError("unexpected")), \
                mock.patch("notifications_service.trading_candidates", side_effect=RuntimeError("unexpected")):
            stats = generate_notifications(self.db, today=TODAY)
        self.db.commit()
        self.assertEqual(stats["resolved_irrelevant"], 0)
        keys = self.open_keys()
        self.assertIn("trading_health", keys)
        self.assertTrue(any(k.startswith("assignment_deadline_3d:") for k in keys))

    def test_report_stays_after_next_run_without_new_data(self):
        # Report nemá být „vyřešen“ jen proto, že další den API vrací starší datum – vyprší sám.
        self.run_with(api())
        self.run_with(api(report={"date": "2026-11-23", "accounts": [], "fills": [], "signals": []}),
                      today=date(2026, 11, 25))
        self.assertIn("trading_report:2026-11-23", self.open_keys())


if __name__ == "__main__":
    unittest.main()
