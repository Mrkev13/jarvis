"""Phase E: Web Push kryptografie a HTTP odeslání – bez sítě (fake HTTP klient)."""
import json
import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import requests  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

import webpush as wp  # noqa: E402

# RFC 8291, Appendix A
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru"
            "3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def decrypt(body: bytes, ua_private_b64u: str, auth_b64u: str) -> bytes:
    """Strana prohlížeče (RFC 8291) – nezávislé ověření, že zprávu jde přečíst."""
    salt, idlen = body[:16], body[20]
    as_public = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    ua_private = wp.private_key_from_b64u(ua_private_b64u)
    ua_public = wp._public_bytes(ua_private.public_key())
    as_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    ecdh = ua_private.exchange(ec.ECDH(), as_key)
    ikm = wp._hkdf(wp.b64u_decode(auth_b64u), ecdh, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = wp._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = wp._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return padded[: padded.rindex(b"\x02")]


class CryptoTestCase(unittest.TestCase):
    def test_rfc8291_appendix_a_vector(self):
        body = wp.encrypt(RFC["plaintext"], RFC["ua_public"], RFC["auth"],
                          server_private=wp.private_key_from_b64u(RFC["as_private"]),
                          salt=wp.b64u_decode(RFC["salt"]))
        self.assertEqual(wp.b64u_encode(body), RFC["body"])

    def test_random_encryption_round_trips(self):
        body = wp.encrypt(b'{"title":"\xe2\x8f\xb0 fyzio"}', RFC["ua_public"], RFC["auth"])
        self.assertEqual(decrypt(body, RFC["ua_private"], RFC["auth"]), b'{"title":"\xe2\x8f\xb0 fyzio"}')
        self.assertNotEqual(body, wp.encrypt(b"x", RFC["ua_public"], RFC["auth"]))

    def test_invalid_keys_and_oversized_payload(self):
        with self.assertRaises(ValueError):
            wp.encrypt(b"x", wp.b64u_encode(b"\x04" + b"\x00" * 10), RFC["auth"])
        with self.assertRaises(ValueError):
            wp.encrypt(b"x", RFC["ua_public"], wp.b64u_encode(b"short"))
        with self.assertRaises(ValueError):
            wp.encrypt(b"x" * (wp.MAX_PAYLOAD + 1), RFC["ua_public"], RFC["auth"])
        with self.assertRaises(ValueError):
            wp.private_key_from_b64u("abc")

    def test_vapid_jwt_is_valid_es256_for_endpoint_origin(self):
        private, public = wp.generate_keypair()
        header = wp.vapid_authorization("https://fcm.googleapis.com/fcm/send/abc", private, public,
                                        "mailto:me@example.com", now=1_800_000_000)
        token = header.split("t=", 1)[1].split(",", 1)[0]
        self.assertTrue(header.endswith(f"k={public}"))
        head_b64, claims_b64, sig_b64 = token.split(".")
        claims = json.loads(wp.b64u_decode(claims_b64))
        self.assertEqual(claims, {"aud": "https://fcm.googleapis.com", "exp": 1_800_000_000 + 12 * 3600,
                                  "sub": "mailto:me@example.com"})
        self.assertEqual(json.loads(wp.b64u_decode(head_b64)), {"typ": "JWT", "alg": "ES256"})
        sig = wp.b64u_decode(sig_b64)
        pub_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), wp.b64u_decode(public))
        pub_key.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                       f"{head_b64}.{claims_b64}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_topic_is_short_and_stable(self):
        self.assertEqual(wp.topic_for("reminder:1:x|webpush|3"), wp.topic_for("reminder:1:x|webpush|3"))
        self.assertLessEqual(len(wp.topic_for("x" * 500)), 32)


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


class SendTestCase(unittest.TestCase):
    def test_success_with_message_id_and_headers(self):
        seen = {}

        def post(url, data, headers, timeout):
            seen.update(url=url, headers=headers, timeout=timeout)
            return FakeResponse(201, {"Location": "https://push.example/m/abc123"})

        r = wp.send("https://push.example/sub", b"body", "vapid t=x, k=y", ttl=600, topic="t1", http_post=post)
        self.assertEqual((r.status, r.message_id), (201, "abc123"))
        self.assertEqual(seen["headers"]["Content-Encoding"], "aes128gcm")
        self.assertEqual((seen["headers"]["TTL"], seen["headers"]["Topic"]), ("600", "t1"))

    def test_network_error_and_retry_after(self):
        def boom(*a, **k):
            raise requests.ConnectionError("down")

        r = wp.send("https://push.example/sub", b"b", "a", ttl=60, http_post=boom)
        self.assertEqual((r.status, r.error), (None, "network:ConnectionError"))
        r = wp.send("https://push.example/sub", b"b", "a", ttl=60,
                    http_post=lambda *a, **k: FakeResponse(429, {"Retry-After": "120"}))
        self.assertEqual((r.status, r.retry_after), (429, 120))


if __name__ == "__main__":
    unittest.main()
