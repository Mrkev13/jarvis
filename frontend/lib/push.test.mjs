// Phase E: detekce podpory Web Push a tvar požadavků – bez prohlížeče.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  detectPushSupport, deviceStateLabel, serverKeyMatches, subscriptionBody, testResultText, urlBase64ToUint8Array,
} from "./push.ts";

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

// MRK-102: after a server move with new VAPID keys the phone kept the old subscription and showed "connected".
const KEY_A = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4";
const KEY_B = "BDd3_hVL9fZi9Ybo2UUzA284WG5FZR30_95YeZJsiApwXKpNcF1rRPF3foIiBHXRdJI2Qhumhf6_LFTeZaNndIo";

test("subscription key is compared byte by byte with the server's current key", () => {
  const usedA = urlBase64ToUint8Array(KEY_A).buffer;
  assert.equal(serverKeyMatches(usedA, KEY_A), true);
  assert.equal(serverKeyMatches(usedA, KEY_B), false, "old key after a server move");
  assert.equal(serverKeyMatches(new Uint8Array(10).buffer, KEY_A), false);
  assert.equal(serverKeyMatches(null, KEY_A), null, "browser does not reveal the key: undecided, server decides");
  assert.equal(serverKeyMatches(undefined, KEY_A), null);
});

test("test push results are explained, rejected subscriptions ask to reconnect", () => {
  assert.deepEqual(testResultText(true, null).stale, false);
  for (const error of ["http_401", "http_403", "http_404", "http_410", "not_subscribed"]) {
    const r = testResultText(false, error);
    assert.equal(r.stale, true, error);
    assert.match(r.text, /Znovu připojit/);
  }
  assert.equal(testResultText(false, "http_503").stale, false);
  assert.match(testResultText(false, "network").text, /network/);
  assert.match(deviceStateLabel("stale"), /znovu připojit/);
});

// MRK-102 review: the key sent to the server must be the one the subscription was really created with.
test("subscription key comes from the subscription, never from the server's current key", async () => {
  const { keyToBase64Url, subscriptionServerKey } = await import("./push.ts");
  const bufA = urlBase64ToUint8Array(KEY_A).buffer;
  assert.equal(keyToBase64Url(bufA), KEY_A, "round trip without padding");
  assert.equal(keyToBase64Url(null), null);
  assert.equal(keyToBase64Url(new ArrayBuffer(0)), null);
  const ep = "https://fcm.googleapis.com/x";
  assert.equal(subscriptionServerKey(bufA, ep, { endpoint: ep, key: KEY_B }), KEY_A, "browser's own key wins");
  assert.equal(subscriptionServerKey(null, ep, { endpoint: ep, key: KEY_B }), KEY_B, "remembered key for the same endpoint");
  assert.equal(subscriptionServerKey(null, ep, { endpoint: "https://fcm.googleapis.com/other", key: KEY_B }), null,
    "a key remembered for another subscription says nothing");
  assert.equal(subscriptionServerKey(undefined, ep, null), null, "unknown → nothing is claimed");
});

test("401/403 explain both causes and still offer reconnecting", () => {
  for (const error of ["http_401", "http_403"]) {
    const r = testResultText(false, error);
    assert.match(r.text, /ověření serveru/);
    assert.match(r.text, /WEB_PUSH_/);
  }
});
