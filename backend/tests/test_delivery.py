"""Phase E: externí doručení – fronta, retry, dedupe, izolace chyb, Web Push provider (fake HTTP), odběry.

Žádný reálný poskytovatel ani síť; čas se injektuje.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import delivery_service as ds  # noqa: E402
import reminder_service as rs  # noqa: E402
import scheduler_service  # noqa: E402
import webpush  # noqa: E402
from database import Base  # noqa: E402
from models import Delivery, Notification, PushSubscription, Reminder  # noqa: E402
from tests.fakes import FakeProvider  # noqa: E402
from tests.test_webpush import RFC, decrypt  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0)
UA_PUBLIC, UA_AUTH = RFC["ua_public"], RFC["auth"]
ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-1"


class DeliveryTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self):
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def fire(self, title="fyzio", minutes=5, at=None, **kw):
        """Vytvoří připomínku a zazvoní ji (Phase D) → interní notifikace."""
        def go(db):
            r = rs.create_from_spec(db, rs.build_spec(title, in_minutes=minutes, now=NOW, **kw))
            db.commit()
            rs.process_due_reminders(db, now=at or NOW + timedelta(minutes=minutes))
            return r.id
        return self.q(go)

    def cycle(self, providers, now):
        return self.q(lambda db: ds.run_delivery_cycle(db, providers, now=now))

    def deliveries(self):
        return self.q(lambda db: db.query(Delivery).order_by(Delivery.id).all())


class QueueTestCase(DeliveryTestBase):
    def test_success_is_sent_once(self):
        self.fire()
        p = FakeProvider()
        stats = self.cycle([p], NOW + timedelta(minutes=6))
        self.assertEqual((stats["enqueued"], stats["sent"]), (1, 1))
        for _ in range(3):  # opakované běhy / restart
            self.cycle([p], NOW + timedelta(minutes=7))
        self.assertEqual(len(p.calls), 1)
        [d] = self.deliveries()
        self.assertEqual((d.status, d.attempts, d.provider_message_id), ("sent", 1, "m1"))
        target, message, key = p.calls[0]
        self.assertEqual(message["title"], "⏰ fyzio")
        self.assertEqual(message["url"], "/reminders")
        self.assertTrue(key.endswith("|fake|1"))

    def test_two_processors_cannot_both_send(self):
        self.fire()
        p = FakeProvider()
        self.q(lambda db: ds.enqueue_deliveries(db, [p], NOW + timedelta(minutes=6)))
        [d] = self.deliveries()
        db1, db2 = self.Session(), self.Session()
        try:
            r1 = ds._deliver_one(db1, d.id, {"fake": p}, NOW + timedelta(minutes=6))
            r2 = ds._deliver_one(db2, d.id, {"fake": p}, NOW + timedelta(minutes=6))
        finally:
            db1.close()
            db2.close()
        self.assertEqual((r1, r2), ("sent", "skipped"))
        self.assertEqual(len(p.calls), 1)

    def test_transient_failure_retries_with_backoff_and_survives_restart(self):
        self.fire()
        p = FakeProvider(results=[ds.DeliveryResult(False, error="http_503"), ds.DeliveryResult(True)])
        t0 = NOW + timedelta(minutes=6)
        self.cycle([p], t0)
        [d] = self.deliveries()
        self.assertEqual((d.status, d.attempts, d.last_error), ("pending", 1, "http_503"))
        self.assertEqual(d.next_attempt_at, t0 + timedelta(seconds=60))
        self.cycle([FakeProvider(results=[]), ], t0 + timedelta(seconds=30))  # ještě ne (jiná instance = restart)
        self.assertEqual(len(p.calls), 1)
        self.cycle([p], t0 + timedelta(seconds=61))
        [d] = self.deliveries()
        self.assertEqual((d.status, d.attempts), ("sent", 2))

    def test_retry_after_header_is_respected(self):
        self.fire()
        p = FakeProvider(results=[ds.DeliveryResult(False, error="http_429", retry_after=600)])
        t0 = NOW + timedelta(minutes=6)
        self.cycle([p], t0)
        self.assertEqual(self.deliveries()[0].next_attempt_at, t0 + timedelta(seconds=600))

    def test_retries_are_bounded(self):
        self.fire()
        p = FakeProvider(results=[ds.DeliveryResult(False, error="network:Timeout")] * ds.MAX_ATTEMPTS)
        t = NOW + timedelta(minutes=6)
        for _ in range(ds.MAX_ATTEMPTS + 3):
            self.cycle([p], t)
            t += timedelta(hours=2)
            if self.deliveries()[0].status != "pending":
                break
        [d] = self.deliveries()
        self.assertEqual((d.status, d.attempts), ("failed", ds.MAX_ATTEMPTS))
        self.assertTrue(d.last_error.startswith("exhausted:"))
        self.assertEqual(len(p.calls), ds.MAX_ATTEMPTS)

    def test_permanent_failure_stops(self):
        self.fire()
        p = FakeProvider(results=[ds.DeliveryResult(False, permanent=True, error="http_400")])
        self.cycle([p], NOW + timedelta(minutes=6))
        self.cycle([p], NOW + timedelta(hours=3))
        [d] = self.deliveries()
        self.assertEqual((d.status, d.last_error, d.attempts), ("failed", "http_400", 1))
        self.assertEqual(len(p.calls), 1)

    def test_one_failing_delivery_does_not_block_another(self):
        self.fire()
        p = FakeProvider(targets=[(1, None), (2, None)], results=[RuntimeError("boom"), ds.DeliveryResult(True)])
        stats = self.cycle([p], NOW + timedelta(minutes=6))
        self.assertEqual((stats["sent"], stats["retry"]), (1, 1))
        self.assertEqual({d.target_id: d.status for d in self.deliveries()}, {1: "pending", 2: "sent"})

    def test_internal_notification_survives_external_failure(self):
        rid = self.fire()
        p = FakeProvider(results=[ds.DeliveryResult(False, permanent=True, error="http_403")])
        self.cycle([p], NOW + timedelta(minutes=6))
        [n] = self.q(lambda db: db.query(Notification).filter_by(source_id=rid).all())
        self.assertFalse(n.resolved)
        self.assertEqual(self.q(lambda db: db.get(Reminder, rid).status), "fired")

    def test_disabled_delivery_creates_nothing(self):
        self.fire()
        self.assertEqual(self.cycle([], NOW + timedelta(minutes=6)), {"enqueued": 0, "sent": 0})
        self.assertEqual(self.deliveries(), [])
        with patch.dict(os.environ, {"EXTERNAL_DELIVERY_ENABLED": "false", "WEB_PUSH_VAPID_PRIVATE_KEY": "x",
                                     "WEB_PUSH_VAPID_PUBLIC_KEY": "y"}):
            self.assertEqual(ds.configured_providers(), [])
        with patch.dict(os.environ, {"WEB_PUSH_VAPID_PRIVATE_KEY": "", "WEB_PUSH_VAPID_PUBLIC_KEY": ""}):
            self.assertEqual(ds.configured_providers(), [])

    def test_each_recurring_occurrence_gets_one_delivery(self):
        def go(db):
            rs.create_from_spec(db, rs.build_spec("léky", recurrence="daily", time_local="08:00", now=NOW))
            db.commit()
        self.q(go)
        p = FakeProvider()
        for day in (5, 6):
            at = datetime(2026, 10, day, 6, 0)
            self.q(lambda db: rs.process_due_reminders(db, now=at))
            self.cycle([p], at + timedelta(seconds=30))
            self.cycle([p], at + timedelta(minutes=2))
        self.assertEqual(len(p.calls), 2)
        self.assertEqual(len({d.dedupe_key for d in self.deliveries()}), 2)

    def test_overdue_after_downtime_delivers_once_and_stale_ones_expire(self):
        self.fire(at=NOW + timedelta(hours=3))  # zazněla se zpožděním po výpadku
        p = FakeProvider()
        self.cycle([p], NOW + timedelta(hours=3, minutes=1))
        self.assertEqual(len(p.calls), 1)
        self.fire(title="stará", minutes=5)
        self.q(lambda db: ds.enqueue_deliveries(db, [p], NOW + timedelta(minutes=6)))
        self.q(lambda db: ds.process_deliveries(db, [p], NOW + timedelta(hours=13)))  # backend neběžel 13 h
        statuses = {d.status for d in self.deliveries()}
        self.assertIn("skipped", statuses)
        self.assertEqual(len(p.calls), 1, "zastaralá připomínka se ven neposílá")

    def test_resolved_notification_is_not_pushed(self):
        rid = self.fire()
        p = FakeProvider()
        self.q(lambda db: ds.enqueue_deliveries(db, [p], NOW + timedelta(minutes=6)))

        def done(db):
            rs.complete(db, db.get(Reminder, rid))
            db.commit()
        self.q(done)
        self.q(lambda db: ds.process_deliveries(db, [p], NOW + timedelta(minutes=7)))
        self.assertEqual(p.calls, [])
        self.assertEqual(self.deliveries()[0].last_error, "notification_resolved")

    def test_device_subscribed_later_gets_no_old_reminders(self):
        self.fire()
        p = FakeProvider(targets=[(1, NOW + timedelta(minutes=30))])
        self.cycle([p], NOW + timedelta(minutes=31))
        self.assertEqual(self.deliveries(), [])

    def test_interrupted_sending_is_recovered(self):
        self.fire()
        p = FakeProvider()
        self.q(lambda db: ds.enqueue_deliveries(db, [p], NOW + timedelta(minutes=6)))

        def crash(db):
            d = db.query(Delivery).one()
            d.status, d.attempts, d.last_attempt_at = "sending", 1, NOW + timedelta(minutes=6)
            db.commit()
        self.q(crash)
        self.q(lambda db: ds.process_deliveries(db, [p], NOW + timedelta(minutes=10)))
        self.assertEqual(p.calls, [], "ještě ne – mohl běžet jiný proces")
        stats = self.q(lambda db: ds.process_deliveries(db, [p], NOW + timedelta(minutes=17)))
        self.assertEqual((stats["recovered"], stats["sent"]), (1, 1))

    def test_scheduler_job_and_lazy_firing_do_not_duplicate(self):
        def go(db):
            rs.create_from_spec(db, rs.build_spec("fyzio", in_minutes=1, now=datetime(2020, 1, 1)))
            db.commit()
            rs.process_due_reminders(db)  # lazy cesta (čtení notifikací) už zazvonila
        self.q(go)
        p = FakeProvider()
        with patch.object(scheduler_service, "SessionLocal", self.Session), \
                patch.object(ds, "configured_providers", lambda: [p]), \
                patch.object(ds, "MAX_AGE", timedelta(days=36500)), \
                patch.object(ds, "ENQUEUE_LOOKBACK", timedelta(days=36500)):
            scheduler_service._run_reminders_job()
            scheduler_service._run_reminders_job()
            self.q(lambda db: rs.process_due_reminders(db))
            scheduler_service._run_reminders_job()
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(self.q(lambda db: db.query(Notification).count()), 1)

    def test_scheduler_delivery_failure_does_not_affect_reminders(self):
        def go(db):
            rs.create_from_spec(db, rs.build_spec("fyzio", in_minutes=1, now=datetime(2020, 1, 1)))
            db.commit()
        self.q(go)

        def broken():
            raise RuntimeError("provider config exploded")

        with patch.object(scheduler_service, "SessionLocal", self.Session), \
                patch.object(ds, "configured_providers", broken):
            scheduler_service._run_reminders_job()
        self.assertEqual(self.q(lambda db: db.query(Reminder).one().status), "fired")


class FakeHttp:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.requests = []

    def __call__(self, url, data, headers, timeout):
        self.requests.append((url, data, headers))

        class R:
            pass
        r = R()
        r.status_code = self.statuses.pop(0)
        r.headers = {"Location": "https://fcm.googleapis.com/m/xyz"} if r.status_code == 201 else {}
        return r


class WebPushProviderTestCase(DeliveryTestBase):
    def setUp(self):
        super().setUp()
        self.private, self.public = webpush.generate_keypair()

    def subscribe(self, endpoint=ENDPOINT):
        def go(db):
            sub = ds.upsert_subscription(db, endpoint, {"p256dh": UA_PUBLIC, "auth": UA_AUTH}, "Firefox", now=NOW)
            db.commit()
            return sub.id
        return self.q(go)

    def provider(self, http):
        return ds.WebPushProvider(self.private, self.public, "mailto:me@example.com", http_post=http)

    def test_sends_encrypted_payload_the_browser_can_read(self):
        self.subscribe()
        self.fire()
        http = FakeHttp(201)
        stats = self.cycle([self.provider(http)], NOW + timedelta(minutes=6))
        self.assertEqual(stats["sent"], 1)
        url, body, headers = http.requests[0]
        self.assertEqual(url, ENDPOINT)
        self.assertTrue(headers["Authorization"].startswith("vapid t="))
        self.assertEqual(len(headers["Topic"]), 32)
        payload = json.loads(decrypt(body, RFC["ua_private"], UA_AUTH))
        self.assertEqual(payload["title"], "⏰ fyzio")
        sub = self.q(lambda db: db.query(PushSubscription).one())
        self.assertIsNotNone(sub.last_success_at)
        self.assertEqual(self.deliveries()[0].provider_message_id, "xyz")

    def test_gone_subscription_is_disabled_and_not_used_again(self):
        self.subscribe()
        self.fire()
        http = FakeHttp(410)
        self.cycle([self.provider(http)], NOW + timedelta(minutes=6))
        [d] = self.deliveries()
        self.assertEqual((d.status, d.last_error), ("failed", "http_410"))
        self.assertIsNotNone(self.q(lambda db: db.query(PushSubscription).one().disabled_at))
        self.fire(title="další")
        self.cycle([self.provider(http)], NOW + timedelta(minutes=7))
        self.assertEqual(len(self.deliveries()), 1, "zaniklé zařízení nedostane další doručení")

    def test_status_classification(self):
        cases = {201: (True, False, False), 503: (False, False, False), 429: (False, False, False),
                 413: (False, True, False), 401: (False, True, True), 403: (False, True, True),
                 404: (False, True, True), 410: (False, True, True)}
        for status, (ok, permanent, gone) in cases.items():
            with self.subTest(status=status):
                r = ds.classify(webpush.PushResponse(status))
                # MRK-102: 401/403 = subscription of other VAPID keys, never deliverable -> disabled like 404/410
                self.assertEqual((r.ok, r.permanent, r.target_gone), (ok, permanent, gone))
        self.assertFalse(ds.classify(webpush.PushResponse(None, error="network:Timeout")).permanent)

    def test_unsubscribe_skips_pending_and_stops_sending(self):
        self.subscribe()
        self.fire()
        http = FakeHttp()
        self.q(lambda db: ds.enqueue_deliveries(db, [self.provider(http)], NOW + timedelta(minutes=6)))

        def unsub(db):
            self.assertTrue(ds.remove_subscription(db, ENDPOINT))
            db.commit()
        self.q(unsub)
        self.cycle([self.provider(http)], NOW + timedelta(minutes=7))
        self.assertEqual(http.requests, [])
        self.assertEqual(self.deliveries()[0].status, "skipped")
        self.assertFalse(self.q(lambda db: ds.remove_subscription(db, ENDPOINT)))

    def test_config_problems(self):
        self.assertEqual(ds.WebPushProvider("", "", "").config_problem(), "not_configured")
        self.assertEqual(ds.WebPushProvider("abc", self.public, "").config_problem(), "invalid_keys")
        other_private, _ = webpush.generate_keypair()
        self.assertEqual(ds.WebPushProvider(other_private, self.public, "").config_problem(), "key_mismatch")
        self.assertIsNone(ds.WebPushProvider(self.private, self.public, "").config_problem())


class SubscriptionValidationTestCase(unittest.TestCase):
    def test_valid_known_push_services(self):
        for url in (ENDPOINT, "https://updates.push.services.mozilla.com/wpush/v2/abc",
                    "https://web.push.apple.com/QH8...", "https://wns2-par02p.notify.windows.com/w/?token=x"):
            with self.subTest(url=url):
                self.assertEqual(ds.validate_subscription(url, {"p256dh": UA_PUBLIC, "auth": UA_AUTH})[0], url)

    def test_rejects_ssrf_and_bad_input(self):
        keys = {"p256dh": UA_PUBLIC, "auth": UA_AUTH}
        bad = [
            ("http://fcm.googleapis.com/fcm/send/x", keys),  # bez TLS
            ("https://127.0.0.1/x", keys), ("https://10.0.0.5/x", keys), ("https://localhost/x", keys),
            ("https://evil.example.com/x", keys), ("https://fcm.googleapis.com.evil.com/x", keys),
            ("https://user:pw@fcm.googleapis.com/x", keys),
            ("https://fcm.googleapis.com/" + "a" * 3000, keys),
            (ENDPOINT, {"p256dh": "abc", "auth": UA_AUTH}),
            (ENDPOINT, {"p256dh": UA_PUBLIC, "auth": "abc"}),
            (ENDPOINT, {"p256dh": webpush.b64u_encode(b"\x04" + b"\x01" * 64), "auth": UA_AUTH}),  # není bod křivky
            (ENDPOINT, None), (None, keys),
        ]
        for endpoint, k in bad:
            with self.subTest(endpoint=str(endpoint)[:60], keys=k):
                with self.assertRaises(ValueError):
                    ds.validate_subscription(endpoint, k)

    def test_extra_hosts_from_env(self):
        with patch.dict(os.environ, {"WEB_PUSH_EXTRA_HOSTS": "push.example.org"}):
            ds.validate_subscription("https://push.example.org/x", {"p256dh": UA_PUBLIC, "auth": UA_AUTH})


if __name__ == "__main__":
    unittest.main()
