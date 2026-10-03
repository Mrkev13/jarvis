"""Web Push bez třetích stran (Roadmap 3.0 Phase E): RFC 8291 šifrování + RFC 8292 VAPID.

Jen knihovna `cryptography` (+ `requests` pro HTTP). Žádný účet u poskytovatele: zprávu doručí push služba
prohlížeče (Google FCM, Mozilla autopush, Apple, Microsoft) podle `endpoint` z odběru v prohlížeči.

Klíče (VAPID) jen z prostředí: `WEB_PUSH_VAPID_PRIVATE_KEY` (32 B skalár, base64url) a
`WEB_PUSH_VAPID_PUBLIC_KEY` (65 B nekomprimovaný bod, base64url). Vygeneruje `scripts/generate_vapid_keys.py`.
Nic z toho (ani odběry) se neloguje.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
MAX_PAYLOAD = 3000  # bezpečně pod limitem push služeb (4 KB po zašifrování)


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    s = str(text or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def private_key_from_b64u(text: str) -> ec.EllipticCurvePrivateKey:
    raw = b64u_decode(text)
    if len(raw) != 32:
        raise ValueError("VAPID privátní klíč musí být 32 B (base64url)")
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def generate_keypair() -> tuple[str, str]:
    """(privátní, veřejný) klíč pro VAPID v base64url – jen pro skript, nikdy do Gitu."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u_encode(private_raw), b64u_encode(_public_bytes(key.public_key()))


def encrypt(
    plaintext: bytes,
    ua_public_b64u: str,
    auth_secret_b64u: str,
    *,
    server_private: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """RFC 8291 (aes128gcm, jeden záznam). server_private/salt jen pro testovací vektory."""
    ua_public = b64u_decode(ua_public_b64u)
    auth_secret = b64u_decode(auth_secret_b64u)
    if len(ua_public) != 65 or ua_public[0] != 0x04 or len(auth_secret) != 16:
        raise ValueError("Neplatné klíče odběru (p256dh / auth)")
    if len(plaintext) > MAX_PAYLOAD:
        raise ValueError("Zpráva je pro Web Push příliš dlouhá")
    as_private = server_private or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(as_private.public_key())
    salt = salt or os.urandom(16)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = as_private.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, ecdh_secret, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02 = poslední záznam, bez paddingu
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


def vapid_authorization(endpoint: str, private_b64u: str, public_b64u: str, contact: str, now: int | None = None) -> str:
    """RFC 8292: `vapid t=<JWT ES256>, k=<veřejný klíč>`; aud = origin endpointu, platnost 12 h."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(now or time.time()) + 12 * 3600, "sub": contact}
    header = {"typ": "JWT", "alg": "ES256"}
    signing_input = (
        b64u_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64u_encode(json.dumps(claims, separators=(",", ":")).encode())
    )
    der = private_key_from_b64u(private_b64u).sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    jwt = signing_input + "." + b64u_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={public_b64u}"


def topic_for(key: str) -> str:
    """Topic hlavička (max 32 znaků base64url): push služba nahradí nedoručenou zprávu se stejným tématem."""
    return b64u_encode(hashlib.sha256(key.encode("utf-8")).digest())[:32]


@dataclass(frozen=True)
class PushResponse:
    status: int | None  # None = síťová chyba
    message_id: str | None = None
    retry_after: int | None = None
    error: str | None = None  # kategorie, nikdy obsah odpovědi


def send(
    endpoint: str,
    body: bytes,
    authorization: str,
    *,
    ttl: int,
    topic: str | None = None,
    urgency: str = "high",
    timeout: float = 10.0,
    http_post=None,
) -> PushResponse:
    import requests

    headers = {
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(int(ttl)),
        "Urgency": urgency,
        "Authorization": authorization,
    }
    if topic:
        headers["Topic"] = topic
    post = http_post or requests.post
    try:
        resp = post(endpoint, data=body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return PushResponse(None, error=f"network:{type(exc).__name__}")
    retry_after = None
    raw_retry = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
    if raw_retry and str(raw_retry).isdigit():
        retry_after = int(raw_retry)
    location = resp.headers.get("Location") if getattr(resp, "headers", None) else None
    message_id = location.rsplit("/", 1)[-1][:200] if location else None
    return PushResponse(resp.status_code, message_id=message_id, retry_after=retry_after)
