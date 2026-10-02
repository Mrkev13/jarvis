import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth_service
import main
import tools
from database import Base
from models import FinanceTransaction


PIN = "4821"


class AuthEnforcementTestCase(unittest.TestCase):
    """Backend musí vynucovat session na všech routách mimo AUTH_PUBLIC_PATHS."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

        self._orig = {
            "auth_session_local": auth_service.SessionLocal,
            "main_session_local": main.SessionLocal,
            "tools_session_local": tools.SessionLocal,
            "pin_hash": auth_service.AUTH_PIN_HASH,
            "failed_attempts": auth_service._failed_attempts,
        }
        auth_service.SessionLocal = self.Session
        main.SessionLocal = self.Session
        tools.SessionLocal = self.Session
        auth_service._failed_attempts = {}
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(
            PIN.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")

        self.client = TestClient(main.app)

    def tearDown(self):
        auth_service.SessionLocal = self._orig["auth_session_local"]
        main.SessionLocal = self._orig["main_session_local"]
        tools.SessionLocal = self._orig["tools_session_local"]
        auth_service.AUTH_PIN_HASH = self._orig["pin_hash"]
        auth_service._failed_attempts = self._orig["failed_attempts"]
        self.engine.dispose()

    def _login(self):
        r = self.client.post("/auth/login", json={"pin": PIN})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("session_set"))
        self.assertIn(auth_service.AUTH_COOKIE_NAME, self.client.cookies)

    def test_protected_read_without_session_returns_401(self):
        r = self.client.get("/finance/summary")
        self.assertEqual(r.status_code, 401)

    def test_protected_write_without_session_is_rejected_and_not_persisted(self):
        r = self.client.post(
            "/finance/transaction",
            json={"amount": 100, "category": "test", "transaction_type": "income"},
        )
        self.assertEqual(r.status_code, 401)
        db = self.Session()
        try:
            self.assertEqual(db.query(FinanceTransaction).count(), 0)
        finally:
            db.close()

    def test_invalid_session_cookie_returns_401(self):
        self.client.cookies.set(auth_service.AUTH_COOKIE_NAME, "forged-token")
        r = self.client.get("/finance/summary")
        self.assertEqual(r.status_code, 401)

    def test_valid_session_grants_access(self):
        self._login()
        r = self.client.get("/finance/summary")
        self.assertEqual(r.status_code, 200)

    def test_revoked_session_after_logout_returns_401(self):
        self._login()
        token = self.client.cookies.get(auth_service.AUTH_COOKIE_NAME)
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)
        # Pošli původní (již revokovaný) token explicitně – logout cookie smaže.
        self.client.cookies.set(auth_service.AUTH_COOKIE_NAME, token)
        r = self.client.get("/finance/summary")
        self.assertEqual(r.status_code, 401)

    def test_public_auth_paths_reachable_without_session(self):
        r_validate = self.client.get("/auth/session/validate")
        self.assertEqual(r_validate.status_code, 200)
        self.assertFalse(r_validate.json().get("valid"))

        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)

        r_bad_login = self.client.post("/auth/login", json={"pin": "0000"})
        self.assertEqual(r_bad_login.status_code, 401)
        self.assertEqual(r_bad_login.json().get("error"), "invalid_pin")

    def test_auth_disabled_keeps_api_open(self):
        auth_service.AUTH_PIN_HASH = ""
        r = self.client.get("/finance/summary")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
