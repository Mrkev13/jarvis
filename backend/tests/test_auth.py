import os
import sys
import unittest
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import bcrypt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class AuthServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False
        )

        import auth_service
        self._orig_session_local = auth_service.SessionLocal
        self._orig_auth_pin_hash = auth_service.AUTH_PIN_HASH
        self._orig_failed_attempts = auth_service._failed_attempts
        auth_service.SessionLocal = self.Session
        auth_service._failed_attempts = {}

        self.auth_service = auth_service

    def tearDown(self):
        import auth_service
        auth_service.SessionLocal = self._orig_session_local
        auth_service.AUTH_PIN_HASH = self._orig_auth_pin_hash
        auth_service._failed_attempts = self._orig_failed_attempts

    def test_01_auth_disabled_no_hash_default(self):
        # AUTH_PIN_HASH prázdný (výchozí stav po setUp, ale resetuj explicitně)
        self.auth_service.AUTH_PIN_HASH = ""
        self.assertFalse(self.auth_service.auth_enabled())
        result = self.auth_service.validate_session_token(None)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("is_authenticated"))
        self.assertTrue(result.get("auth_disabled"))

    def test_02_bcrypt_verify_good_and_bad_pin(self):
        good_pin = "1234"
        bad_pin = "0000"
        pin_hash = bcrypt.hashpw(
            good_pin.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")
        self.auth_service.AUTH_PIN_HASH = pin_hash

        self.assertTrue(self.auth_service.auth_enabled())
        self.assertTrue(self.auth_service._bcrypt_verify_pin(good_pin))
        self.assertFalse(self.auth_service._bcrypt_verify_pin(bad_pin))

    def test_03_session_token_sha256_hashed_in_db(self):
        good_pin = "abcd"
        pin_hash = bcrypt.hashpw(
            good_pin.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")
        self.auth_service.AUTH_PIN_HASH = pin_hash

        token_plaintext, expires_at, err = (
            self.auth_service.authenticate_pin_and_create_session(
                good_pin, "127.0.0.1", "test-ua"
            )
        )
        self.assertEqual(err, "")
        self.assertIsNotNone(token_plaintext)
        self.assertIsNotNone(expires_at)

        db = self.Session()
        try:
            from models import AuthSession
            rows = db.query(AuthSession).all()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            expected_hash = _sha256(token_plaintext)
            self.assertEqual(row.token_hash, expected_hash)
            self.assertEqual(row.ip_address, "127.0.0.1")
            self.assertEqual(row.user_agent, "test-ua")
            self.assertFalse(row.revoked)
            self.assertIsNotNone(row.created_at)
            self.assertIsNotNone(row.expires_at)
            self.assertGreater(row.expires_at, row.created_at)
        finally:
            db.close()

    def test_04_rate_limit_5_attempts_5min_lock(self):
        good_pin = "5678"
        bad_pin = "0000"
        pin_hash = bcrypt.hashpw(
            good_pin.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")
        self.auth_service.AUTH_PIN_HASH = pin_hash
        self.auth_service._failed_attempts = {}

        for i in range(5):
            tok, exp, err = self.auth_service.authenticate_pin_and_create_session(
                bad_pin, "ip1", None
            )
            self.assertEqual(err, "invalid_pin")
            self.assertIsNone(tok)

        # 6. pokus - i správný PIN má vrátit lock
        tok, exp, err = self.auth_service.authenticate_pin_and_create_session(
            good_pin, "ip1", None
        )
        self.assertIsNone(tok)
        self.assertIn("Too many failed attempts", err)
        self.assertIn("Locked for", err)
        self.assertIn("s.", err)
        remaining = int(err.split("Locked for ")[1].split("s")[0])
        self.assertGreaterEqual(remaining, 290)
        self.assertLessEqual(remaining, 300)

        # Jiná IP by měla projít
        tok, exp, err = self.auth_service.authenticate_pin_and_create_session(
            good_pin, "ip2", None
        )
        self.assertEqual(err, "")
        self.assertIsNotNone(tok)

    def test_05_validate_session_revoked_and_expired(self):
        good_pin = "secret"
        pin_hash = bcrypt.hashpw(
            good_pin.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")
        self.auth_service.AUTH_PIN_HASH = pin_hash

        from models import AuthSession

        # Vytvoř validní session manuálně
        valid_token = "valid-token-123"
        now = datetime.utcnow()
        db = self.Session()
        try:
            db.add(AuthSession(
                token_hash=_sha256(valid_token),
                created_at=now,
                expires_at=now + timedelta(hours=24),
                last_seen_at=now,
                ip_address="1.1.1.1",
                revoked=False,
            ))
            # Expired session
            expired_token = "expired-token-456"
            db.add(AuthSession(
                token_hash=_sha256(expired_token),
                created_at=now - timedelta(days=2),
                expires_at=now - timedelta(days=1),
                last_seen_at=now - timedelta(days=2),
                ip_address="2.2.2.2",
                revoked=False,
            ))
            db.commit()
        finally:
            db.close()

        # Platný token -> valid
        result = self.auth_service.validate_session_token(valid_token)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("is_authenticated"))
        self.assertEqual(result.get("ip_address"), "1.1.1.1")
        self.assertFalse(result.get("auth_disabled"))

        # Revokuj token
        db = self.Session()
        try:
            sess = (
                db.query(AuthSession)
                .filter(AuthSession.token_hash == _sha256(valid_token))
                .first()
            )
            sess.revoked = True
            db.commit()
        finally:
            db.close()

        result_revoked = self.auth_service.validate_session_token(valid_token)
        self.assertIsNotNone(result_revoked)
        self.assertFalse(result_revoked.get("is_authenticated"))

        # Expired token
        result_expired = self.auth_service.validate_session_token(expired_token)
        self.assertIsNotNone(result_expired)
        self.assertFalse(result_expired.get("is_authenticated"))
        self.assertTrue(result_expired.get("expired"))

    def test_06_logout_revokes_and_validate_endpoint_shape(self):
        good_pin = "hello"
        pin_hash = bcrypt.hashpw(
            good_pin.encode("utf-8"), bcrypt.gensalt(rounds=4)
        ).decode("utf-8")
        self.auth_service.AUTH_PIN_HASH = pin_hash

        from models import AuthSession

        # Vytvoř platnou session
        tok, exp, err = self.auth_service.authenticate_pin_and_create_session(
            good_pin, "10.0.0.1", "ua-test"
        )
        self.assertEqual(err, "")
        self.assertIsNotNone(tok)

        # Ověř, že před revoke je validní
        before = self.auth_service.validate_session_token(tok)
        self.assertIsNotNone(before)
        self.assertTrue(before.get("is_authenticated"))

        # Vyvolej revoke
        revoked = self.auth_service.revoke_session_token(tok)
        self.assertTrue(revoked)

        # Po revoke by měl být invalid
        after = self.auth_service.validate_session_token(tok)
        self.assertIsNotNone(after)
        self.assertFalse(after.get("is_authenticated"))

        # DB kontrola
        db = self.Session()
        try:
            sess = (
                db.query(AuthSession)
                .filter(AuthSession.token_hash == _sha256(tok))
                .first()
            )
            self.assertTrue(sess.revoked)
        finally:
            db.close()

        # validate_session_token(None) když auth disabled -> OK
        self.auth_service.AUTH_PIN_HASH = ""
        r = self.auth_service.validate_session_token(None)
        self.assertIsNotNone(r)
        self.assertTrue(r.get("is_authenticated"))
        self.assertTrue(r.get("auth_disabled"))

        # Neplatný token vrací None, ale ne None, je dict s is_authenticated=False
        self.auth_service.AUTH_PIN_HASH = pin_hash
        bad = self.auth_service.validate_session_token("completely-nonexistent-token")
        self.assertIsNotNone(bad)
        self.assertFalse(bad.get("is_authenticated"))


if __name__ == "__main__":
    unittest.main()
