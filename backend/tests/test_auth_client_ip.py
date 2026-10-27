"""MRK-73: the PIN rate limit cannot be bypassed by rotating X-Forwarded-For; the attempts dict stays bounded."""
import ipaddress
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import main  # noqa: E402
from auth_service import client_ip  # noqa: E402
from database import Base  # noqa: E402
from env_config import env_ip_networks  # noqa: E402

PIN = "4821"
LOOPBACK = (ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128"))


class ClientIpTestCase(unittest.TestCase):
    def test_default_trusts_no_proxy(self):
        self.assertEqual(auth_service.AUTH_TRUSTED_PROXIES, ())
        self.assertEqual(client_ip("127.0.0.1", "203.0.113.9"), "127.0.0.1")
        self.assertEqual(client_ip("100.64.0.7", "1.2.3.4, 5.6.7.8"), "100.64.0.7")
        self.assertEqual(client_ip(None, "1.2.3.4"), "unknown")

    def test_trusted_proxy_uses_the_hop_it_added(self):
        with patch.object(auth_service, "AUTH_TRUSTED_PROXIES", LOOPBACK):
            # Tailscale Serve sets X-Forwarded-For to the tailnet source address
            self.assertEqual(client_ip("127.0.0.1", "100.101.102.103"), "100.101.102.103")
            # an appending proxy: what the client sent stays on the left and is ignored
            self.assertEqual(client_ip("127.0.0.1", "6.6.6.6, 100.101.102.103"), "100.101.102.103")
            self.assertEqual(client_ip("::1", "100.101.102.103, 127.0.0.1"), "100.101.102.103")
            self.assertEqual(client_ip("127.0.0.1", None), "127.0.0.1")
            self.assertEqual(client_ip("127.0.0.1", "not-an-ip"), "127.0.0.1")
            # a peer outside the allowlist cannot pick its own key
            self.assertEqual(client_ip("100.64.0.7", "127.0.0.1"), "100.64.0.7")

    def test_env_parsing(self):
        with patch.dict(os.environ, {"AUTH_TRUSTED_PROXIES": " 127.0.0.1, ::1 ,10.0.0.0/8"}):
            self.assertEqual([str(n) for n in env_ip_networks("AUTH_TRUSTED_PROXIES")],
                             ["127.0.0.1/32", "::1/128", "10.0.0.0/8"])
        with patch.dict(os.environ, {"AUTH_TRUSTED_PROXIES": "127.0.0.1,localhst"}):
            with self.assertRaises(ValueError):
                env_ip_networks("AUTH_TRUSTED_PROXIES")


class LoginRateLimitTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        pin_hash = bcrypt.hashpw(PIN.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")
        self._patches = [patch.object(auth_service, "SessionLocal", session),
                         patch.object(main, "SessionLocal", session),
                         patch.object(auth_service, "AUTH_PIN_HASH", pin_hash),
                         patch.object(auth_service, "_failed_attempts", {})]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _login(self, pin, xff):
        return self.client.post("/auth/login", json={"pin": pin}, headers={"X-Forwarded-For": xff})

    def test_rotating_x_forwarded_for_does_not_bypass_the_limit(self):
        for i in range(5):
            self.assertEqual(self._login("0000", f"198.51.100.{i}").json()["error"], "invalid_pin")
        r = self._login(PIN, "198.51.100.77")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Too many failed attempts", r.json()["error"])

    def test_behind_trusted_proxy_rotation_still_counts_for_the_real_client(self):
        with patch.object(auth_service, "AUTH_TRUSTED_PROXIES", LOOPBACK), \
                patch.object(main, "client_ip", lambda _peer, xff: client_ip("127.0.0.1", xff)):
            for i in range(5):
                self._login("0000", f"203.0.113.{i}, 100.101.102.103")
            r = self._login(PIN, "203.0.113.99, 100.101.102.103")
            self.assertIn("Too many failed attempts", r.json()["error"])
            # another tailnet device is not locked out by the first one
            self.assertTrue(self._login(PIN, "100.90.1.2").json()["session_set"])

    def _asgi_login_attempts(self, uvicorn_args):
        """Real Uvicorn CLI parsing + Config.load() middleware stack; the peer is loopback (Tailscale Serve)."""
        import asyncio
        import httpx
        from uvicorn import Config
        from uvicorn.main import main as uvicorn_cli

        params = uvicorn_cli.make_context("uvicorn", ["main:app", *uvicorn_args]).params
        config = Config(main.app, proxy_headers=params["proxy_headers"],
                        forwarded_allow_ips=params["forwarded_allow_ips"], log_config=None)
        config.load()

        async def run():
            transport = httpx.ASGITransport(app=config.loaded_app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://hub") as client:
                for i in range(5):
                    await client.post("/auth/login", json={"pin": "0000"},
                                      headers={"X-Forwarded-For": f"198.51.100.{i}"})
                r = await client.post("/auth/login", json={"pin": PIN}, headers={"X-Forwarded-For": "198.51.100.77"})
                return r.json()
        return asyncio.run(run())

    def test_production_uvicorn_flags_keep_the_real_peer(self):
        import production
        self.assertIn("Too many failed attempts", self._asgi_login_attempts(production.UVICORN_SAFETY_ARGS)["error"])
        self.assertEqual(set(auth_service._failed_attempts), {"127.0.0.1"})

    def test_uvicorn_defaults_would_let_rotation_through(self):
        # Why --no-proxy-headers is required: by default Uvicorn trusts loopback and rewrites the client from the header.
        self.assertTrue(self._asgi_login_attempts([]).get("session_set"))

    def test_attempts_dict_is_bounded(self):
        with patch.object(auth_service, "MAX_TRACKED_IPS", 50):
            for i in range(200):
                auth_service._record_failed_attempt(f"key-{i}")
            self.assertLessEqual(len(auth_service._failed_attempts), 50)
            self.assertIn("key-199", auth_service._failed_attempts, "the newest attempts are kept")


if __name__ == "__main__":
    unittest.main()
