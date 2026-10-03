import os
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

import bcrypt

from database import SessionLocal
from models import AuthSession
from env_config import env_bool, env_str


def _utc_now() -> datetime:
    """Timezone-aware UTC datetime. Python 3.13+ email.utils.format_datetime
    s usegmt=True vyžaduje timezone-aware datetime; zároveň zachováme
    kompatibilitu se starším SQLite/PG DateTime sloupci (při zápisu do DB se
    timezone awareness ztratí, což je OK)."""
    return datetime.now(tz=timezone.utc)


def _ensure_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ===== Configuration =====
AUTH_PIN_HASH = env_str("AUTH_PIN_HASH")  # bcrypt hash of PIN, empty = auth disabled
AUTH_COOKIE_NAME = env_str("AUTH_COOKIE_NAME", "standa_hub_session")
AUTH_COOKIE_SECURE = env_bool("AUTH_COOKIE_SECURE", False)
AUTH_COOKIE_HTTPONLY = True
AUTH_COOKIE_SAMESITE = "Lax"

# Podporujeme oba názvy proměnných pro zpětnou kompatibilitu:
# preferovaný = AUTH_SESSION_TTL_HOURS (env template a spec), fallback AUTH_SESSION_TTL_MINUTES.
_ttl_hours_env = os.environ.get("AUTH_SESSION_TTL_HOURS")
if _ttl_hours_env:
    AUTH_SESSION_TTL_MINUTES = int(float(_ttl_hours_env) * 60)
else:
    AUTH_SESSION_TTL_MINUTES = int(os.environ.get("AUTH_SESSION_TTL_MINUTES", "1440"))  # 24h default
BCRYPT_ROUNDS = 12

# Per-IP rate limit (in-memory, restart = reset):
# failed_attempts[ip] = list of timestamps
_failed_attempts: dict[str, list[float]] = {}
LOCKOUT_5_AFTER_N_ATTEMPTS = 5
LOCKOUT_10_AFTER_N_ATTEMPTS = 10
LOCKOUT_5_MIN = 300
LOCKOUT_10_MIN = 600

def auth_enabled() -> bool:
    """Graceful degradation: pokud AUTH_PIN_HASH není nastaven (empty), AUTH JE VYPNUTÝ."""
    return bool(AUTH_PIN_HASH)

def _hash_session_token(token_plaintext: str) -> str:
    return hashlib.sha256(token_plaintext.encode("utf-8")).hexdigest()

def _bcrypt_hash_pin(pin: str) -> str:
    """For setup script; production uses pre-computed AUTH_PIN_HASH."""
    hashed = bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return hashed.decode("utf-8")

def _bcrypt_verify_pin(pin_candidate: str) -> bool:
    if not AUTH_PIN_HASH:
        return False
    try:
        return bcrypt.checkpw(
            pin_candidate.encode("utf-8")[:72],
            AUTH_PIN_HASH.encode("utf-8")
        )
    except Exception:
        return False

def _check_rate_limit(ip: str) -> Tuple[bool, str]:
    """Return (allowed, message). 5 pokusů = lock 5 min, 10 pokusů = lock 10 min."""
    now = time.time()
    attempts = _failed_attempts.get(ip, [])
    # Vyčti starší než 1 hod
    attempts = [a for a in attempts if now - a < 3600]
    n = len(attempts)
    if n >= LOCKOUT_10_AFTER_N_ATTEMPTS:
        last = attempts[-1]
        if now - last < LOCKOUT_10_MIN:
            remaining = int(LOCKOUT_10_MIN - (now - last))
            return False, f"Too many failed attempts. Locked for {remaining}s."
        attempts = attempts[:LOCKOUT_10_AFTER_N_ATTEMPTS - 1]
    elif n >= LOCKOUT_5_AFTER_N_ATTEMPTS:
        last = attempts[-1]
        if now - last < LOCKOUT_5_MIN:
            remaining = int(LOCKOUT_5_MIN - (now - last))
            return False, f"Too many failed attempts. Locked for {remaining}s."
        attempts = attempts[:LOCKOUT_5_AFTER_N_ATTEMPTS - 1]
    _failed_attempts[ip] = attempts
    return True, ""

def _record_failed_attempt(ip: str):
    _failed_attempts.setdefault(ip, []).append(time.time())

def _clear_failed_attempts(ip: str):
    _failed_attempts.pop(ip, None)

def authenticate_pin_and_create_session(
    pin_candidate: str,
    ip: str | None,
    user_agent: str | None,
) -> Tuple[Optional[str], Optional[datetime], str]:
    """Return (token_plaintext, expires_at, error). Token is None if auth failed."""
    if not auth_enabled():
        # Auth disabled – nijak neomezuj; ale login není potřeba.
        return None, None, "auth_disabled"
    # Rate limit
    ip_key = ip or "unknown"
    allowed, err = _check_rate_limit(ip_key)
    if not allowed:
        return None, None, err
    # PIN ověření
    if not _bcrypt_verify_pin(pin_candidate):
        _record_failed_attempt(ip_key)
        return None, None, "invalid_pin"
    _clear_failed_attempts(ip_key)

    # Vytvoř session
    token_plaintext = secrets.token_urlsafe(32)  # ~256 bits
    token_hash = _hash_session_token(token_plaintext)
    now = _utc_now()
    expires_at = now + timedelta(minutes=AUTH_SESSION_TTL_MINUTES)
    db = SessionLocal()
    try:
        sess = AuthSession(
            token_hash=token_hash,
            created_at=now.replace(tzinfo=None),
            expires_at=expires_at.replace(tzinfo=None),
            last_seen_at=now.replace(tzinfo=None),
            ip_address=ip[:50] if ip else None,
            user_agent=user_agent[:500] if user_agent else None,
            revoked=False,
        )
        db.add(sess)
        db.commit()
        return token_plaintext, _ensure_utc_aware(expires_at.replace(tzinfo=None)), ""
    finally:
        db.close()

def validate_session_token(token_plaintext: str | None) -> dict | None:
    """Vrať session_info dict nebo None. Obsahuje is_authenticated=True/False.
    Refreshne last_seen_at každých 5 min (ne na každý request)."""
    if not auth_enabled():
        # Auth disabled = považuj za autentizovaného!
        return {
            "is_authenticated": True,
            "auth_disabled": True,
            "session_id": None,
            "expires_at": None,
        }
    if not token_plaintext:
        return {"is_authenticated": False}
    token_hash = _hash_session_token(token_plaintext)
    now = _utc_now().replace(tzinfo=None)
    db = SessionLocal()
    try:
        sess = (
            db.query(AuthSession)
            .filter(AuthSession.token_hash == token_hash)
            .first()
        )
        if not sess:
            return {"is_authenticated": False}
        if sess.revoked:
            return {"is_authenticated": False}
        if sess.expires_at and sess.expires_at < now:
            return {"is_authenticated": False, "expired": True}
        # Refresh last_seen_at každých 5 min, ne každého requestu
        if (sess.last_seen_at is None or
                (now - sess.last_seen_at).total_seconds() >= 300):
            sess.last_seen_at = now
            db.commit()
        return {
            "is_authenticated": True,
            "session_id": sess.id,
            "expires_at": sess.expires_at.isoformat() if sess.expires_at else None,
            "ip_address": sess.ip_address,
            "auth_disabled": False,
        }
    finally:
        db.close()

def revoke_session_token(token_plaintext: str | None) -> bool:
    """Vrátí True pokud byla session označena revoked."""
    if not token_plaintext or not auth_enabled():
        return False
    token_hash = _hash_session_token(token_plaintext)
    now = _utc_now().replace(tzinfo=None)
    db = SessionLocal()
    try:
        sess = (
            db.query(AuthSession)
            .filter(AuthSession.token_hash == token_hash)
            .first()
        )
        if not sess:
            return False
        sess.revoked = True
        sess.expires_at = now
        db.commit()
        return True
    finally:
        db.close()

def cookie_params(expires_at: datetime | None = None) -> dict:
    params = dict(
        key=AUTH_COOKIE_NAME,
        httponly=AUTH_COOKIE_HTTPONLY,
        secure=AUTH_COOKIE_SECURE,
        samesite=AUTH_COOKIE_SAMESITE,
        path="/",
    )
    if expires_at is not None:
        # Starlette / email.utils.format_datetime s usegmt=True vyžaduje timezone-aware UTC datetime
        params["expires"] = _ensure_utc_aware(expires_at)
    return params
