"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Card, CardHeader, StatusBadge } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import {
  currentPushEnv,
  detectPushSupport,
  deviceStateLabel,
  SERVER_REASON_TEXT,
  subscriptionBody,
  UNSUPPORTED_TEXT,
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
        // Tichá synchronizace se serverem (bez dotazu na oprávnění).
        const sync = await postJson("/push/subscriptions", subscriptionBody(sub.toJSON()));
        setState(sync.ok ? "on" : "off");
      } else {
        setState("off");
      }
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
      let sub: PushSubscription;
      try {
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      } catch {
        // Starý odběr s jiným VAPID klíčem (klíče se změnily) → odhlásit a zkusit jednou znovu.
        await (await reg.pushManager.getSubscription())?.unsubscribe();
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      }
      const res = await postJson("/push/subscriptions", subscriptionBody(sub.toJSON()));
      if (!res.ok) {
        await sub.unsubscribe();
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      setState("on");
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
      setMessage(data.ok ? "Test odeslán – upozornění by mělo za chvíli přijít." : `Test selhal (${data.error ?? "?"}).`);
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
  return (
    <Card as="section" aria-busy={busy || state === "checking"} aria-labelledby="push-settings">
      <CardHeader title={<span id="push-settings">Upozornění mimo aplikaci</span>} />
      <div className="-mt-2 mb-3">
        <StatusBadge tone={on ? "success" : state === "denied" ? "warning" : "neutral"} dot={on} className="whitespace-normal">
          <span role="status">{deviceStateLabel(state)}</span>
        </StatusBadge>
      </div>
      <div className="flex flex-wrap gap-2">
        {state === "off" && (
          <Button variant="primary" size="sm" busy={busy} busyLabel="Zapínám…" onClick={() => void enable()}>
            Zapnout na tomto zařízení
          </Button>
        )}
        {on && (
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
