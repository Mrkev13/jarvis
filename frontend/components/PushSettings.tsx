"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Card, CardHeader, StatusBadge } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import {
  currentPushEnv,
  detectPushSupport,
  deviceStateLabel,
  readRememberedKey,
  rememberKey,
  SERVER_REASON_TEXT,
  serverKeyMatches,
  STALE_TEXT,
  subscriptionBody,
  subscriptionServerKey,
  syncedState,
  testResultText,
  UNSUPPORTED_TEXT,
  UNVERIFIED_TEXT,
  urlBase64ToUint8Array,
  type DeviceState,
} from "@/lib/push";

type PushConfig = { enabled: boolean; available: boolean; reason: string | null; public_key: string | null };

async function existingSubscription(): Promise<PushSubscription | null> {
  // getRegistration nic neregistruje ani nežádá o oprávnění.
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

async function postJson(path: string, body: unknown): Promise<Response> {
  return apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * Upozornění mimo aplikaci (Web Push) pro TOTO zařízení. Oprávnění se žádá jen po kliknutí na „Zapnout".
 */
export default function PushSettings() {
  const [state, setState] = useState<DeviceState>("checking");
  const [detail, setDetail] = useState<string | null>(null);
  const [config, setConfig] = useState<PushConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const support = detectPushSupport(currentPushEnv());
    if (!support.supported) {
      setState("unsupported");
      setDetail(UNSUPPORTED_TEXT[support.reason]);
      return;
    }
    try {
      const res = await apiFetch("/push/config");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const cfg = (await res.json()) as PushConfig;
      setConfig(cfg);
      if (!cfg.available || !cfg.public_key) {
        setState("server_off");
        setDetail(SERVER_REASON_TEXT[cfg.reason ?? ""] ?? null);
        return;
      }
      if (Notification.permission === "denied") {
        setState("denied");
        setDetail("Povol upozornění pro tento web v nastavení prohlížeče a obnov stránku.");
        return;
      }
      const sub = await existingSubscription();
      if (sub) {
        // MRK-102: klíč, pro který byl odběr opravdu vytvořen (ne aktuální klíč serveru – ten by starý odběr „potvrdil").
        const usedKey = subscriptionServerKey(sub.options?.applicationServerKey, sub.endpoint, readRememberedKey());
        const keyMatches = usedKey ? serverKeyMatches(urlBase64ToUint8Array(usedKey).buffer, cfg.public_key) === true : false;
        if (usedKey && !keyMatches) {
          setState("stale");
          setDetail(STALE_TEXT);
          return;
        }
        // Tichá synchronizace se serverem (bez dotazu na oprávnění); neznámý klíč = server_key se neposílá.
        const body = subscriptionBody(sub.toJSON());
        const sync = await postJson("/push/subscriptions", usedKey ? { ...body, server_key: usedKey } : body);
        const next = syncedState(usedKey, keyMatches, sync.status);
        setState(next);
        setDetail(next === "stale" ? STALE_TEXT : next === "unverified" ? UNVERIFIED_TEXT : null);
        return;
      }
      setState("off");
      setDetail(null);
    } catch {
      setState("off");
      setDetail("Stav se nepodařilo zjistit.");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void refresh());
  }, [refresh]);

  async function enable() {
    if (!config?.public_key) return;
    setBusy(true);
    setMessage(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "off");
        setMessage("Bez povolení upozornění to nepůjde.");
        return;
      }
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
      await navigator.serviceWorker.ready;
      const key = urlBase64ToUint8Array(config.public_key);
      // MRK-102: starý odběr k jiným klíčům serveru nejdřív zrušit, jinak by subscribe() vrátil ten starý.
      const previous = await reg.pushManager.getSubscription();
      if (previous && serverKeyMatches(previous.options?.applicationServerKey, config.public_key) !== true) {
        await previous.unsubscribe();
      }
      let sub: PushSubscription;
      try {
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      } catch {
        // Starý odběr s jiným VAPID klíčem (klíče se změnily) → odhlásit a zkusit jednou znovu.
        await (await reg.pushManager.getSubscription())?.unsubscribe();
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      }
      // nový odběr: prohlížeč ho přijal s klíčem config.public_key (options ho potvrdí, kde ho prohlížeč prozradí)
      const usedKey = subscriptionServerKey(sub.options?.applicationServerKey, sub.endpoint, null) ?? config.public_key;
      const res = await postJson("/push/subscriptions", { ...subscriptionBody(sub.toJSON()), server_key: usedKey });
      if (!res.ok) {
        await sub.unsubscribe();
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      rememberKey(sub.endpoint, usedKey);
      setState("on");
      setDetail(null);
      setMessage("Hotovo. Zkus „Poslat test“.");
    } catch (err) {
      setMessage(err instanceof Error ? `Nepovedlo se: ${err.message}` : "Nepovedlo se zapnout upozornění.");
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    setBusy(true);
    setMessage(null);
    try {
      const sub = await existingSubscription();
      if (!sub) {
        setState("off");
        return;
      }
      const res = await postJson("/push/test", { endpoint: sub.endpoint });
      const data = (await res.json()) as { ok?: boolean; error?: string | null };
      const result = testResultText(Boolean(data.ok), data.error);
      setMessage(result.text);
      if (result.state) {
        setState(result.state);
        if (result.state === "on") setDetail(null);
      }
    } catch {
      setMessage("Test se nepodařilo odeslat.");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setMessage(null);
    try {
      const sub = await existingSubscription();
      if (sub) {
        await postJson("/push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
      setState("off");
      setMessage("Na tomto zařízení vypnuto.");
    } catch {
      setMessage("Vypnutí se nepovedlo.");
    } finally {
      setBusy(false);
    }
  }

  const on = state === "on";
  // odběr existuje, jen není ověřený / push služba odmítla ověření: jde testovat, znovu připojit i vypnout
  const doubtful = state === "unverified" || state === "auth_error";
  return (
    <Card as="section" aria-busy={busy || state === "checking"} aria-labelledby="push-settings">
      <CardHeader title={<span id="push-settings">Upozornění mimo aplikaci</span>} />
      <div className="-mt-2 mb-3">
        <StatusBadge tone={on ? "success" : state === "denied" || state === "stale" || doubtful ? "warning" : "neutral"} dot={on} className="whitespace-normal">
          <span role="status">{deviceStateLabel(state)}</span>
        </StatusBadge>
      </div>
      <div className="flex flex-wrap gap-2">
        {(state === "off" || state === "stale" || doubtful) && (
          <Button variant={doubtful ? "secondary" : "primary"} size="sm" busy={busy} busyLabel="Připojuji…" onClick={() => void enable()}>
            {state === "off" ? "Zapnout na tomto zařízení" : "Znovu připojit"}
          </Button>
        )}
        {(on || doubtful) && (
          <>
            <Button size="sm" disabled={busy} onClick={() => void sendTest()}>
              Poslat test
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void disable()}>
              Vypnout na tomto zařízení
            </Button>
          </>
        )}
      </div>
      {detail && <p className="mt-3 text-sm text-ink-muted">{detail}</p>}
      {message && (
        <p className="mt-3 text-sm text-ink-2" aria-live="polite">
          {message}
        </p>
      )}
      <p className="mt-3 text-xs text-ink-muted">
        Připomínky se vždy ukážou i ve zvonku aplikace. Upozornění mimo aplikaci posílá server přes push službu
        prohlížeče; zastaralé (starší než 12 h) ani už vyřízené se neposílají.
      </p>
    </Card>
  );
}
