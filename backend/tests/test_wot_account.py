"""MRK-105: zdroje WoT z propojeného Wargaming účtu – přihlášení (state, allowlist originu), ověření tokenu, šifrované
uložení, hodinová synchronizace s prodloužením tokenu, vypršení = jasný stav, odpojení, ruční zápis jako záloha a
token nikde (API, Aktivita, log). Falešný transport, nikdy síť."""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from cryptography.fernet import Fernet

TESTS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
for p in (BACKEND_DIR, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import database  # noqa: E402
import wot_account_service as svc  # noqa: E402
import wot_integrations  # noqa: E402
import wot_wargaming as wg  # noqa: E402
from models import ActivityLog, WotAccountLink, WotResource  # noqa: E402
from test_wot_milestones import WotBase  # noqa: E402

APP_ID = "0123456789abcdef0123456789abcdef"
ACCOUNT = 500123
TOKEN = "tok-first-0123456789abcdef"
TOKEN2 = "tok-second-0123456789abcdef"
ORIGIN = "https://hub.example.test"
KEY = Fernet.generate_key().decode()
ENV = {"WG_APPLICATION_ID": APP_ID, "WG_REGION": "eu", "WOT_NICKNAME": "tester_1", "WOT_TOKEN_KEY": KEY,
       "FRONTEND_ORIGINS": f"{ORIGIN},http://127.0.0.1:3000"}
NOW = datetime(2026, 11, 27, 10, 0)  # naive UTC


def unix(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


class Resp:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.content = json.dumps(data).encode()

    def json(self):
        return self._data


class FakeWg:
    def __init__(self):
        self.valid = {TOKEN}
        self.values = {"credits": 4_250_000, "gold": 1200, "free_xp": 85_000, "bonds": 3400}
        self.down = False
        self.calls = []

    def __call__(self, method, url, **kw):
        path = url.split("/wot/", 1)[1].rstrip("/")
        self.calls.append((method, path, kw))
        assert url.startswith("https://api.worldoftanks.eu/wot/") and kw.get("allow_redirects") is False
        payload = kw.get("data") if method == "POST" else kw.get("params")
        assert payload["application_id"] == APP_ID
        if "access_token" in payload:
            assert method == "POST" and "params" not in kw, "token jen v těle, ne v URL"
        if self.down:
            raise ConnectionError("down")
        token = payload.get("access_token")
        if token not in self.valid:
            return Resp({"status": "error", "error": {"code": 407, "message": "INVALID_ACCESS_TOKEN"}})
        if path == "account/info":
            assert payload["fields"] == "private.credits,private.gold,private.free_xp,private.bonds"
            return Resp({"status": "ok", "data": {str(payload["account_id"]): {"private": dict(self.values)}}})
        if path == "auth/prolongate":
            self.valid = {TOKEN2}
            return Resp({"status": "ok", "data": {"access_token": TOKEN2, "account_id": ACCOUNT,
                                                  "expires_at": unix(NOW + timedelta(days=20))}})
        if path == "auth/logout":
            self.valid = set()
            return Resp({"status": "ok", "data": None})
        raise AssertionError(path)


class AccountBase(WotBase):
    def setUp(self):
        super().setUp()
        self.api = FakeWg()
        self.clock = [NOW]
        self.mono = [1000.0]
        self._mp = [
            patch.dict(os.environ, ENV),
            patch.object(wg, "client", lambda: wg.Client(wg.load_config(), self.api)),
            patch.object(svc, "utc_now", lambda: self.clock[0]),
            patch.object(svc, "_states", {}),
            patch.object(database, "SessionLocal", self.Session),
        ]
        for p in self._mp:
            p.start()

    def tearDown(self):
        for p in self._mp:
            p.stop()
        super().tearDown()

    def start(self, origin=ORIGIN):
        loc = svc.start_login(origin, wg.client(), monotonic=lambda: self.mono[0])["location"]
        parsed = urlparse(loc)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), ("https", "api.worldoftanks.eu", "/wot/auth/login/"))
        redirect = parse_qs(parsed.query)["redirect_uri"][0]
        self.assertTrue(redirect.startswith(f"{origin}/wot/connect/"))
        return redirect.rsplit("/", 1)[1]

    def connect(self, state, **over):
        data = {"state": state, "status": "ok", "access_token": TOKEN, "account_id": str(ACCOUNT),
                "expires_at": str(unix(NOW + timedelta(days=14))), **over}
        db = self.Session()
        try:
            out = svc.connect(db, data, wg.client(), now=self.clock[0], monotonic=lambda: self.mono[0])
            db.commit()
            return out
        finally:
            db.close()

    def sync(self, force=False):
        db = self.Session()
        try:
            out = svc.sync(db, wg.client(), now=self.clock[0], force=force)
            db.commit()
            return out
        finally:
            db.close()

    def amounts(self):
        return self.q(lambda db: {r.resource: (r.amount, r.source) for r in db.query(WotResource)})


class TestConnect(AccountBase):
    def test_connect_stores_encrypted_token_and_fills_resources(self):
        out = self.connect(self.start())
        self.assertTrue(out["connected"])
        self.assertEqual(out["resources"]["credits"]["amount"], 4_250_000)
        self.assertEqual(out["resources"]["gold"]["source"], "wargaming")
        link = self.q(lambda db: db.query(WotAccountLink).one())
        self.assertNotIn(TOKEN, link.token_enc)
        self.assertEqual(Fernet(KEY.encode()).decrypt(link.token_enc.encode()).decode(), TOKEN)
        self.assertEqual(self.amounts()["free_xp"], (85_000, "wargaming"))
        summary = self.q(lambda db: [a.summary.replace("\xa0", " ") for a in db.query(ActivityLog).order_by(ActivityLog.id)])
        self.assertIn("propojen", summary[0])
        self.assertIn("Credits 4 250 000", summary[1])

    def test_state_is_single_use_expires_and_origin_is_allowlisted(self):
        with self.assertRaises(svc.AccountError) as e:
            svc.start_login("https://evil.example", wg.client())
        self.assertEqual(e.exception.code, "bad_origin")
        state = self.start()
        self.connect(state)
        with self.assertRaises(svc.AccountError) as e:
            self.connect(state)
        self.assertEqual(e.exception.code, "bad_state")
        old = self.start()
        self.mono[0] += svc.STATE_TTL_SECONDS + 1
        with self.assertRaises(svc.AccountError) as e:
            self.connect(old)
        self.assertEqual(e.exception.code, "bad_state")
        for bad in ("", "../x", None):
            with self.assertRaises(svc.AccountError):
                self.connect(bad)

    def test_cancelled_or_foreign_token_is_rejected_without_storing(self):
        with self.assertRaises(svc.AccountError) as e:
            self.connect(self.start(), status="error")
        self.assertEqual(e.exception.code, "cancelled")
        with self.assertRaises(svc.AccountError) as e:
            self.connect(self.start(), access_token="tok-forged-0123456789")
        self.assertEqual(e.exception.code, "token_invalid")
        self.assertEqual(self.q(lambda db: db.query(WotAccountLink).count()), 0)

    def test_without_token_key_nothing_is_stored(self):
        with patch.dict(os.environ, {"WOT_TOKEN_KEY": ""}):
            with self.assertRaises(svc.AccountError) as e:
                svc.start_login(ORIGIN, wg.client())
            self.assertEqual(e.exception.code, "key_missing")
            st = self.q(lambda db: svc.status(db, wg.client()))
            self.assertFalse(st["configured"])
            self.assertEqual(st["missing"], ["WOT_TOKEN_KEY"])


class TestSync(AccountBase):
    def test_hourly_sync_updates_values_and_throttles(self):
        self.connect(self.start())
        self.api.values["credits"] = 5_000_000
        self.assertEqual(self.sync()["result"], "skipped", "hned po propojení se znovu nevolá")
        self.clock[0] += timedelta(hours=1)
        self.assertEqual(self.q(lambda db: wot_integrations.hourly_resources(db))["result"], "ok")  # bez commitu
        out = self.sync()
        self.assertEqual(out, {"result": "ok", "changes": 1})
        self.assertEqual(self.amounts()["credits"], (5_000_000, "wargaming"))
        acts = self.q(lambda db: [a.summary.replace("\xa0", " ") for a in db.query(ActivityLog)])
        self.assertIn("WoT zdroje z Wargamingu: Credits 4 250 000 → 5 000 000", acts)
        self.clock[0] += timedelta(hours=1)
        self.assertEqual(self.sync(), {"result": "ok", "changes": 0})
        self.assertEqual(len(self.q(lambda db: db.query(ActivityLog).all())), len(acts), "beze změny žádný řádek")

    def test_token_prolonged_before_expiry(self):
        self.connect(self.start())
        self.clock[0] = NOW + timedelta(days=12)  # zbývají 2 dny
        self.assertEqual(self.sync()["result"], "ok")
        link = self.q(lambda db: db.query(WotAccountLink).one())
        self.assertEqual(Fernet(KEY.encode()).decrypt(link.token_enc.encode()).decode(), TOKEN2)
        self.assertEqual(link.expires_at, NOW + timedelta(days=20))
        self.assertIn("auth/prolongate", [c[1] for c in self.api.calls])

    def test_revoked_or_expired_token_is_a_clear_state(self):
        self.connect(self.start())
        self.api.valid = set()  # zrušeno ve Wargamingu
        self.clock[0] += timedelta(hours=1)
        self.assertEqual(self.sync()["result"], "token_invalid")
        st = self.q(lambda db: svc.status(db, wg.client()))
        self.assertEqual((st["connected"], st["status"], st["error"]), (False, "expired", "token_invalid"))
        self.assertIn("propoj účet znovu", st["error_text"])
        self.assertEqual(self.sync(force=True)["result"], "not_connected")
        # hodnoty zůstaly, ruční zápis funguje dál
        self.assertEqual(self.amounts()["gold"], (1200, "wargaming"))
        expired_rows = self.q(lambda db: [a for a in db.query(ActivityLog) if "vypršelo" in a.summary])
        self.assertEqual(len(expired_rows), 1)

    def test_past_expiry_needs_no_network(self):
        self.connect(self.start())
        self.clock[0] = NOW + timedelta(days=15)
        calls = len(self.api.calls)
        self.assertEqual(self.sync()["result"], "token_invalid")
        self.assertEqual(len(self.api.calls), calls)

    def test_outage_keeps_connection_and_values(self):
        self.connect(self.start())
        self.api.down = True
        self.clock[0] += timedelta(hours=1)
        self.assertEqual(self.sync()["result"], "unavailable")
        st = self.q(lambda db: svc.status(db, wg.client()))
        self.assertEqual((st["connected"], st["error"]), (True, "unavailable"))
        self.api.down = False
        self.assertEqual(self.sync()["result"], "ok")
        self.assertIsNone(self.q(lambda db: svc.status(db, wg.client()))["error"])

    def test_without_link_nothing_happens(self):
        self.assertEqual(self.sync(force=True)["result"], "not_connected")
        self.assertEqual(self.api.calls, [])


class TestRest(AccountBase):
    def test_rest_flow_manual_fallback_disconnect_and_no_token_anywhere(self):
        self.login()
        self.assertEqual(self.client.get("/wot/account").json()["status"], "not_connected")
        r = self.client.post("/wot/account/login", json={"origin": ORIGIN})
        self.assertEqual(r.status_code, 200, r.text)
        state = parse_qs(urlparse(r.json()["location"]).query)["redirect_uri"][0].rsplit("/", 1)[1]
        self.assertEqual(self.client.post("/wot/account/login", json={"origin": "https://x.test"}).status_code, 400)
        r = self.client.post("/wot/account/connect", json={
            "state": state, "status": "ok", "access_token": TOKEN, "account_id": str(ACCOUNT),
            "expires_at": str(unix(NOW + timedelta(days=14)))})
        self.assertEqual(r.status_code, 200, r.text)
        bodies = [r.text, self.client.get("/wot/account").text, self.client.post("/wot/account/sync").text,
                  self.client.get("/wot/resources").text]
        self.assertEqual(self.client.get("/wot/resources").json()["credits"], 4_250_000)
        # ruční zápis zůstává jako záloha a je vidět jako ruční
        self.assertEqual(self.client.post("/wot/resource", json={"resource": "bonds", "amount": 100}).status_code, 200)
        self.assertEqual(self.client.get("/wot/account").json()["resources"]["bonds"]["source"], "manual")
        r = self.client.delete("/wot/account")
        self.assertFalse(r.json()["connected"])
        self.assertIn("auth/logout", [c[1] for c in self.api.calls])
        self.assertEqual(self.q(lambda db: db.query(WotAccountLink).count()), 0)
        acts = self.q(lambda db: " ".join(f"{a.summary} {a.delta_json}" for a in db.query(ActivityLog)))
        for text in [*bodies, r.text, acts]:
            for secret in (TOKEN, KEY, APP_ID, str(ACCOUNT)):
                self.assertNotIn(secret, text)

    def test_access_log_redacts_tokens(self):
        svc.redact_access_log()
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                   ("1.2.3.4", "GET", f"/wot/connect/x?status=ok&access_token={TOKEN}&a=1", "1.1", 200),
                                   None)
        for f in logging.getLogger("uvicorn.access").filters:
            f.filter(record)
        self.assertNotIn(TOKEN, record.getMessage())
        self.assertIn("access_token=***&a=1", record.getMessage())
