"""Vygeneruje VAPID klíče pro Web Push (Phase E). Výstup patří do backend/.env – NIKDY do Gitu.

Spuštění z kořene repa:  python backend/scripts/generate_vapid_keys.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from webpush import generate_keypair  # noqa: E402

private_key, public_key = generate_keypair()
print("# Web Push (Phase E) – vlož do backend/.env, necommituj")
print(f"WEB_PUSH_VAPID_PRIVATE_KEY={private_key}")
print(f"WEB_PUSH_VAPID_PUBLIC_KEY={public_key}")
print("WEB_PUSH_CONTACT=mailto:you@example.com")
