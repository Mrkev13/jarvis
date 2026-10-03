"""Phase E: /push API – auth, konfigurace bez úniku tajemství, odběr/odhlášení, test (fake push služba)."""
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
import webpush  # noqa: E402
from database import Base  # noqa: E402
from models import PushSubscription  # noqa: E402
from tests.test_webpush import RFC  # noqa: E402

ENDPOINT = "https://fcm.googleapis.com/fcm/send/secret-device-token"
SUB = {"endpoint": ENDPOINT, "keys": {"p256dh": RFC["ua_public"], "auth": RFC["auth"]}}


class PushApiTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.private, self.public = webpush.generate_keypair()
        self._patches = [
            patch.object(main, "SessionLocal", self.Session),
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH",
                         bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode("utf-8")),
            patch.dict(os.environ, {"WEB_PUSH_VAPID_PRIVATE_KEY": self.private,
                                    "WEB_PUSH_VAPID_PUBLIC_KEY": self.public,
                                    "WEB_PUSH_CONTACT": "mailto:me@example.com",
                                    "EXTERNAL_DELIVERY_ENABLED": "true"}),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)

    def test_all_push_endpoints_require_session(self):
        for method, path, body in (("GET", "/push/config", None), ("GET", "/push/status", None),
                                   ("POST", "/push/subscriptions", SUB), ("POST", "/push/unsubscribe", {"endpoint": ENDPOINT}),
                                   ("POST", "/push/test", {"endpoint": ENDPOINT})):
            with self.subTest(path=path):
                kwargs = {"json": body} if body is not None else {}
                self.assertEqual(self.client.request(method, path, **kwargs).status_code, 401)
        self.assertEqual(self.Session().query(PushSubscription).count(), 0)

    def test_config_exposes_only_the_public_key(self):
        self.login()
        r = self.client.get("/push/config")
        body = r.json()
        self.assertEqual((body["available"], body["public_key"], body["reason"]), (True, self.public, None))
        self.assertNotIn(self.private, r.text)
        with patch.dict(os.environ, {"WEB_PUSH_VAPID_PRIVATE_KEY": "", "WEB_PUSH_VAPID_PUBLIC_KEY": ""}):
            self.assertEqual(self.client.get("/push/config").json(),
                             {"enabled": True, "available": False, "reason": "not_configured", "public_key": None})
        with patch.dict(os.environ, {"EXTERNAL_DELIVERY_ENABLED": "false"}):
            self.assertEqual(self.client.get("/push/config").json()["reason"], "disabled")

    def test_subscribe_status_and_unsubscribe(self):
        self.login()
        r = self.client.post("/push/subscriptions", json=SUB, headers={"User-Agent": "Firefox/130"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.post("/push/subscriptions", json=SUB).status_code, 200)  # idempotentní
        status = self.client.get("/push/status")
        [view] = status.json()["subscriptions"]
        self.assertEqual(view["host"], "fcm.googleapis.com")
        self.assertNotIn("secret-device-token", status.text, "endpoint se ven neposílá")
        self.assertNotIn(RFC["auth"], status.text)
        self.assertEqual(self.client.post("/push/unsubscribe", json={"endpoint": ENDPOINT}).json()["removed"], True)
        self.assertEqual(self.client.post("/push/unsubscribe", json={"endpoint": ENDPOINT}).json()["removed"], False)
        self.assertEqual(self.client.get("/push/status").json()["subscriptions"], [])

    def test_invalid_subscriptions_are_400(self):
        self.login()
        bad = [
            {**SUB, "endpoint": "https://192.168.1.10/push"},
            {**SUB, "endpoint": "http://fcm.googleapis.com/x"},
            {**SUB, "keys": {"p256dh": "nope", "auth": RFC["auth"]}},
            {**SUB, "keys": {}},
        ]
        for payload in bad:
            with self.subTest(payload=str(payload)[:80]):
                self.assertEqual(self.client.post("/push/subscriptions", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/push/subscriptions", json={"endpoint": ENDPOINT}).status_code, 422)

    def test_test_push_uses_this_device_only(self):
        self.login()
        self.assertEqual(self.client.post("/push/test", json={"endpoint": ENDPOINT}).json()["error"], "not_subscribed")
        self.client.post("/push/subscriptions", json=SUB)
        sent = []

        def fake_send(endpoint, body, authorization, **kw):
            sent.append(endpoint)
            return webpush.PushResponse(201, message_id="m1")

        with patch.object(webpush, "send", fake_send):
            r = self.client.post("/push/test", json={"endpoint": ENDPOINT}).json()
        self.assertEqual(r, {"ok": True, "error": None})
        self.assertEqual(sent, [ENDPOINT])

        with patch.object(webpush, "send", lambda *a, **k: webpush.PushResponse(410)):
            r = self.client.post("/push/test", json={"endpoint": ENDPOINT}).json()
        self.assertEqual(r, {"ok": False, "error": "http_410"})
        self.assertTrue(self.client.get("/push/status").json()["subscriptions"][0]["disabled"])
        self.assertEqual(self.client.post("/push/subscriptions", json=SUB).json()["subscription"]["disabled"], False)

    def test_test_push_without_configuration(self):
        self.login()
        self.client.post("/push/subscriptions", json=SUB)
        with patch.dict(os.environ, {"WEB_PUSH_VAPID_PRIVATE_KEY": ""}):
            self.assertEqual(self.client.post("/push/test", json={"endpoint": ENDPOINT}).json(),
                             {"ok": False, "error": "not_configured"})


if __name__ == "__main__":
    unittest.main()
