// Phase E: detekce podpory Web Push a tvar požadavků – bez prohlížeče.
import assert from "node:assert/strict";
import { test } from "node:test";

import { detectPushSupport, deviceStateLabel, subscriptionBody, urlBase64ToUint8Array } from "./push.ts";

const ok = {
  isSecureContext: true, hasServiceWorker: true, hasPushManager: true, hasNotification: true,
  userAgent: "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0", standalone: false,
};

test("supported in a secure context with all APIs", () => {
  assert.deepEqual(detectPushSupport(ok), { supported: true });
});

test("plain http over the Tailscale IP is reported as insecure", () => {
  assert.deepEqual(detectPushSupport({ ...ok, isSecureContext: false }), { supported: false, reason: "insecure" });
});

test("iOS Safari outside the home-screen app explains how to install", () => {
  const ios = { ...ok, userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", hasPushManager: false };
  assert.deepEqual(detectPushSupport(ios), { supported: false, reason: "ios_needs_install" });
  assert.deepEqual(detectPushSupport({ ...ios, standalone: true, hasPushManager: true }), { supported: true });
});

test("missing APIs have their own reasons", () => {
  assert.equal(detectPushSupport({ ...ok, hasServiceWorker: false }).reason, "no_service_worker");
  assert.equal(detectPushSupport({ ...ok, hasPushManager: false }).reason, "no_push");
  assert.equal(detectPushSupport({ ...ok, hasNotification: false }).reason, "no_notifications");
});

test("VAPID key decoding", () => {
  const bytes = urlBase64ToUint8Array("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4");
  assert.equal(bytes.length, 65);
  assert.equal(bytes[0], 4);
});

test("subscription body keeps only endpoint and keys", () => {
  const body = subscriptionBody({ endpoint: "https://fcm.googleapis.com/x", expirationTime: null,
    keys: { p256dh: "BCV", auth: "BTB" } });
  assert.deepEqual(body, { endpoint: "https://fcm.googleapis.com/x", keys: { p256dh: "BCV", auth: "BTB" } });
  assert.throws(() => subscriptionBody({ endpoint: "http://x", keys: { p256dh: "a", auth: "b" } }));
  assert.throws(() => subscriptionBody(null));
});

test("state labels", () => {
  assert.match(deviceStateLabel("on"), /Připojeno/);
  assert.match(deviceStateLabel("denied"), /zakázaná/);
});
