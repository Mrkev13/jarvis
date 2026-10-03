"""Externí doručení notifikací (Roadmap 3.0 Phase E) – oddělené od zazvonění připomínek.

Tok (vše bez LLM):
1. Phase D zazvoní připomínku → vznikne běžná notifikace (`notification_type="reminder"`). To se nemění;
   když externí doručení selže, interní notifikace i zvonek fungují dál.
2. `enqueue_deliveries` (idempotentní) z nedávných nevyřešených reminder notifikací vytvoří řádky `deliveries`
   = jedna notifikace × kanál × cíl (unikátní dedupe klíč) → výskyt připomínky nejvýš jednou na zařízení.
3. `process_deliveries` řádky odesílá: podmíněný claim pending → sending (žádné dvojí odeslání mezi
   procesy), odeslání mimo transakci, pak sent / další pokus (ohraničený backoff) / failed. Stav je v DB,
   takže restart nic neztratí; přerušené `sending` se po 10 min vrátí do pending (Topic hlavička zajistí,
   že push služba případný duplikát nahradí místo zobrazení dvakrát).

Kanály jsou pluginy (`DeliveryProvider`): teď Web Push (VAPID); další (ntfy, e-mail…) jen přidá provider.
Logují se jen id, kanál, pokus, stav a kategorie chyby – nikdy endpointy, klíče ani obsah.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

from sqlalchemy import update as _sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import webpush
from models import Delivery, Notification, PushSubscription
from time_utils import utc_now

logger = logging.getLogger("standa_hub.delivery")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s [delivery] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

CHANNEL_WEBPUSH = "webpush"
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (60, 300, 900, 3600)  # po 1., 2., 3., 4. neúspěchu
MAX_RETRY_AFTER = 3600
ENQUEUE_LOOKBACK = timedelta(hours=12)
MAX_AGE = timedelta(hours=12)  # starší připomínku už ven neposílat (zastaralá)
SENDING_STALE_AFTER = timedelta(minutes=10)
PUSH_TTL_SECONDS = 12 * 3600
BATCH = 50

DEFAULT_PUSH_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
    ".push.apple.com",
    ".notify.windows.com",
)


def external_delivery_enabled() -> bool:
    return os.environ.get("EXTERNAL_DELIVERY_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    permanent: bool = False
    error: str | None = None  # kategorie (http_410, network:Timeout, …), nikdy obsah
    message_id: str | None = None
    retry_after: int | None = None
    target_gone: bool = False


class DeliveryProvider(Protocol):
    channel: str

    def is_configured(self) -> bool: ...

    def targets(self, db: Session) -> list[tuple[int, datetime]]: ...

    def send(self, db: Session, target_id: int, message: dict, dedupe_key: str) -> DeliveryResult: ...


# ===== Web Push provider =====

class WebPushProvider:
    channel = CHANNEL_WEBPUSH

    def __init__(self, private_key: str | None = None, public_key: str | None = None, contact: str | None = None,
                 http_post=None):
        self.private_key = (private_key if private_key is not None else os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY", "")).strip()
        self.public_key = (public_key if public_key is not None else os.environ.get("WEB_PUSH_VAPID_PUBLIC_KEY", "")).strip()
        self.contact = (contact if contact is not None else os.environ.get("WEB_PUSH_CONTACT", "")).strip() \
            or "mailto:admin@localhost"
        self.http_post = http_post

    def config_problem(self) -> str | None:
        if not self.private_key or not self.public_key:
            return "not_configured"
        try:
            priv = webpush.private_key_from_b64u(self.private_key)
            if webpush.b64u_encode(webpush._public_bytes(priv.public_key())) != self.public_key:
                return "key_mismatch"
        except Exception:  # noqa: BLE001
            return "invalid_keys"
        return None

    def is_configured(self) -> bool:
        return self.config_problem() is None

    def targets(self, db: Session) -> list[tuple[int, datetime]]:
        rows = db.query(PushSubscription.id, PushSubscription.created_at).filter(PushSubscription.disabled_at.is_(None)).all()
        return [(sid, created) for sid, created in rows]

    def send(self, db: Session, target_id: int, message: dict, dedupe_key: str) -> DeliveryResult:
        sub = db.get(PushSubscription, target_id)
        if sub is None or sub.disabled_at is not None:
            return DeliveryResult(False, permanent=True, error="target_gone", target_gone=True)
        try:
            body = webpush.encrypt(json.dumps(message, ensure_ascii=False).encode("utf-8"), sub.p256dh, sub.auth)
            auth = webpush.vapid_authorization(sub.endpoint, self.private_key, self.public_key, self.contact)
        except ValueError:
            return DeliveryResult(False, permanent=True, error="invalid_subscription", target_gone=True)
        resp = webpush.send(sub.endpoint, body, auth, ttl=PUSH_TTL_SECONDS, topic=webpush.topic_for(dedupe_key),
                            http_post=self.http_post)
        return classify(resp)


def classify(resp: webpush.PushResponse) -> DeliveryResult:
    """Odpověď push služby → výsledek. 404/410 = odběr zanikl; jiné 4xx = trvalá chyba; 429/5xx/síť = znovu."""
    if resp.status in (200, 201, 202):
        return DeliveryResult(True, message_id=resp.message_id)
    if resp.status is None:
        return DeliveryResult(False, error=resp.error or "network")
    if resp.status in (404, 410):
        return DeliveryResult(False, permanent=True, error=f"http_{resp.status}", target_gone=True)
    if resp.status == 429 or resp.status >= 500:
        return DeliveryResult(False, error=f"http_{resp.status}", retry_after=resp.retry_after)
    return DeliveryResult(False, permanent=True, error=f"http_{resp.status}")


def configured_providers() -> list[DeliveryProvider]:
    if not external_delivery_enabled():
        return []
    provider = WebPushProvider()
    return [provider] if provider.is_configured() else []


# ===== odběry =====

def _allowed_hosts() -> tuple[str, ...]:
    extra = tuple(h.strip().lower() for h in os.environ.get("WEB_PUSH_EXTRA_HOSTS", "").split(",") if h.strip())
    return DEFAULT_PUSH_HOSTS + extra


def _host_allowed(host: str) -> bool:
    host = host.lower()
    for allowed in _allowed_hosts():
        if allowed.startswith(".") and host.endswith(allowed):
            return True
        if host == allowed:
            return True
    return False


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def validate_subscription(endpoint, keys) -> tuple[str, str, str]:
    """Odběr z prohlížeče → (endpoint, p256dh, auth). Backend na endpoint posílá POST, proto jen https
    a jen známé push služby (žádné SSRF na vnitřní síť); klíče musí být platný P-256 bod a 16 B auth."""
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError("Neplatný endpoint odběru.")
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Endpoint odběru musí být https URL push služby.")
    if not _host_allowed(parts.hostname):
        raise ValueError("Endpoint nepatří známé push službě (WEB_PUSH_EXTRA_HOSTS pro další).")
    if not isinstance(keys, dict):
        raise ValueError("Chybí klíče odběru.")
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    try:
        raw_p = webpush.b64u_decode(p256dh)
        raw_a = webpush.b64u_decode(auth)
    except Exception:  # noqa: BLE001
        raise ValueError("Klíče odběru nejsou base64url.") from None
    if len(raw_p) != 65 or raw_p[0] != 0x04 or len(raw_a) != 16:
        raise ValueError("Neplatné klíče odběru.")
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw_p)
    except ValueError:
        raise ValueError("Klíč p256dh není bod křivky P-256.") from None
    return endpoint, webpush.b64u_encode(raw_p), webpush.b64u_encode(raw_a)


def upsert_subscription(db: Session, endpoint, keys, user_agent: str | None = None, now: datetime | None = None) -> PushSubscription:
    endpoint, p256dh, auth = validate_subscription(endpoint, keys)
    now = now or utc_now()
    h = endpoint_hash(endpoint)
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint_hash == h).first()
    if sub is None:
        sub = PushSubscription(endpoint_hash=h, endpoint=endpoint, created_at=now, failure_count=0)
        db.add(sub)
    sub.p256dh, sub.auth = p256dh, auth
    sub.user_agent = (user_agent or "")[:255] or None
    sub.disabled_at = None
    sub.failure_count = 0
    db.flush()
    logger.info("subscription upserted id=%s", sub.id)
    return sub


def find_subscription(db: Session, endpoint) -> PushSubscription | None:
    if not isinstance(endpoint, str) or not endpoint:
        return None
    return db.query(PushSubscription).filter(PushSubscription.endpoint_hash == endpoint_hash(endpoint)).first()


def remove_subscription(db: Session, endpoint) -> bool:
    """Odhlášení: smaže odběr a jeho nevyřízená doručení přepne na skipped (nic se už nepošle)."""
    sub = find_subscription(db, endpoint)
    if sub is None:
        return False
    db.execute(
        _sql_update(Delivery)
        .where(Delivery.channel == CHANNEL_WEBPUSH, Delivery.target_id == sub.id,
               Delivery.status.in_(("pending", "sending")))
        .values(status="skipped", last_error="unsubscribed")
    )
    logger.info("subscription removed id=%s", sub.id)
    db.delete(sub)
    return True


def subscription_view(sub: PushSubscription) -> dict:
    return {
        "id": sub.id,
        "host": urlsplit(sub.endpoint).hostname,
        "endpoint_hash": sub.endpoint_hash[:16],
        "user_agent": (sub.user_agent or "")[:80],
        "created_at": sub.created_at.isoformat() + "Z" if sub.created_at else None,
        "last_success_at": sub.last_success_at.isoformat() + "Z" if sub.last_success_at else None,
        "disabled": sub.disabled_at is not None,
        "failure_count": int(sub.failure_count or 0),
    }


# ===== fronta a odesílání =====

def notification_message(n: Notification) -> dict:
    return {"title": n.title, "body": (n.message or "")[:300], "url": n.action_url or "/reminders",
            "tag": f"standa-{n.source_type}-{n.source_id}", "ts": n.created_at.isoformat() + "Z" if n.created_at else None}


def enqueue_deliveries(db: Session, providers: list[DeliveryProvider], now: datetime | None = None) -> int:
    """Pro nedávné nevyřešené reminder notifikace založí chybějící doručení. Idempotentní (unikátní klíč)."""
    if not providers:
        return 0
    now = now or utc_now()
    notes = (
        db.query(Notification)
        .filter(Notification.notification_type == "reminder", Notification.resolved == False,  # noqa: E712
                Notification.created_at >= now - ENQUEUE_LOOKBACK)
        .order_by(Notification.id)
        .all()
    )
    created = 0
    for provider in providers:
        targets = provider.targets(db)
        for n in notes:
            for target_id, since in targets:
                if since is not None and n.created_at < since:
                    continue  # zařízení se přihlásilo až po zaznění → staré připomínky na něj neposílat
                key = f"{n.dedupe_key}|{provider.channel}|{target_id}"[:250]
                if db.query(Delivery.id).filter(Delivery.dedupe_key == key).first():
                    continue
                try:
                    with db.begin_nested():
                        db.add(Delivery(notification_id=n.id, channel=provider.channel, target_id=target_id,
                                        dedupe_key=key, status="pending", attempts=0, next_attempt_at=now,
                                        created_at=now))
                    created += 1
                except IntegrityError:
                    pass  # souběžný proces ho založil dřív
    db.commit()
    return created


def _recover_stale_sending(db: Session, now: datetime) -> int:
    res = db.execute(
        _sql_update(Delivery)
        .where(Delivery.status == "sending", Delivery.last_attempt_at < now - SENDING_STALE_AFTER)
        .values(status="pending", next_attempt_at=now, last_error="interrupted")
    )
    db.commit()
    return int(res.rowcount or 0)


def _finish(db: Session, d: Delivery, status: str, now: datetime, *, error: str | None = None,
            message_id: str | None = None, next_at: datetime | None = None) -> None:
    d.status = status
    d.last_error = error[:120] if error else None
    if message_id:
        d.provider_message_id = message_id[:200]
    if status == "sent":
        d.sent_at = now
    if next_at is not None:
        d.next_attempt_at = next_at
    db.commit()
    logger.info("delivery id=%s channel=%s attempt=%s status=%s error=%s",
                d.id, d.channel, d.attempts, status, error or "-")


def _deliver_one(db: Session, delivery_id: int, providers: dict[str, DeliveryProvider], now: datetime) -> str:
    d = db.get(Delivery, delivery_id)
    if d is None or d.status != "pending":
        return "skipped"
    n = db.get(Notification, d.notification_id)
    if n is None or n.resolved:
        _finish(db, d, "skipped", now, error="notification_resolved")  # uživatel už vyřídil v aplikaci
        return "skipped"
    if n.created_at and now - n.created_at > MAX_AGE:
        _finish(db, d, "skipped", now, error="expired")
        return "skipped"
    provider = providers.get(d.channel)
    if provider is None:
        _finish(db, d, "skipped", now, error="channel_disabled")
        return "skipped"
    claimed = db.execute(
        _sql_update(Delivery)
        .where(Delivery.id == d.id, Delivery.status == "pending")
        .values(status="sending", attempts=Delivery.attempts + 1, last_attempt_at=now)
    )
    db.commit()
    if claimed.rowcount != 1:
        return "skipped"  # jiný proces byl rychlejší
    db.refresh(d)
    try:
        result = provider.send(db, d.target_id, notification_message(n), d.dedupe_key)
    except Exception as exc:  # noqa: BLE001 - chyba providera = přechodná, zkusí se znovu
        db.rollback()
        result = DeliveryResult(False, error=f"exception:{type(exc).__name__}")
    db.refresh(d)
    sub = db.get(PushSubscription, d.target_id) if d.channel == CHANNEL_WEBPUSH and d.target_id else None
    if result.ok:
        if sub is not None:
            sub.last_success_at, sub.failure_count = now, 0
        _finish(db, d, "sent", now, message_id=result.message_id)
        return "sent"
    if sub is not None:
        sub.failure_count = int(sub.failure_count or 0) + 1
    if result.permanent:
        if result.target_gone and sub is not None:
            sub.disabled_at = now
        _finish(db, d, "failed", now, error=result.error or "permanent")
        return "failed"
    if d.attempts >= MAX_ATTEMPTS:
        _finish(db, d, "failed", now, error=f"exhausted:{result.error or 'transient'}")
        return "failed"
    delay = BACKOFF_SECONDS[min(d.attempts, len(BACKOFF_SECONDS)) - 1]
    if result.retry_after:
        delay = max(delay, min(int(result.retry_after), MAX_RETRY_AFTER))
    _finish(db, d, "pending", now, error=result.error or "transient", next_at=now + timedelta(seconds=delay))
    return "retry"


def process_deliveries(db: Session, providers: list[DeliveryProvider], now: datetime | None = None) -> dict:
    now = now or utc_now()
    stats = {"recovered": _recover_stale_sending(db, now), "sent": 0, "retry": 0, "failed": 0, "skipped": 0,
             "errors": 0}
    by_channel = {p.channel: p for p in providers}
    ids = [
        did for (did,) in db.query(Delivery.id)
        .filter(Delivery.status == "pending", Delivery.next_attempt_at <= now)
        .order_by(Delivery.next_attempt_at, Delivery.id)
        .limit(BATCH)
        .all()
    ]
    for did in ids:
        try:
            stats[_deliver_one(db, did, by_channel, now)] += 1
        except Exception as exc:  # noqa: BLE001 - jedno doručení nesmí zastavit ostatní
            db.rollback()
            stats["errors"] += 1
            logger.warning("delivery id=%s bookkeeping failed: %s", did, type(exc).__name__)
    return stats


def run_delivery_cycle(db: Session, providers: list[DeliveryProvider] | None = None, now: datetime | None = None) -> dict:
    """Scheduler: založ chybějící doručení a odešli splatná. Bez providerů nic nedělá."""
    providers = configured_providers() if providers is None else providers
    if not providers:
        return {"enqueued": 0, "sent": 0}
    now = now or utc_now()
    enqueued = enqueue_deliveries(db, providers, now)
    stats = process_deliveries(db, providers, now)
    return {"enqueued": enqueued, **stats}


def delivery_summary(db: Session, limit: int = 10) -> list[dict]:
    rows = db.query(Delivery).order_by(Delivery.id.desc()).limit(limit).all()
    return [{"id": d.id, "channel": d.channel, "status": d.status, "attempts": d.attempts,
             "last_error": d.last_error, "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
             "sent_at": d.sent_at.isoformat() + "Z" if d.sent_at else None} for d in rows]
