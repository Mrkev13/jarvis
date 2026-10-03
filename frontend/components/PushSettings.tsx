"use client";

import { useCallback, useEffect, useState } from "react";
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
    <section
      aria-busy={busy || state === "checking"}
      className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-5 flex flex-col gap-3"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="font-semibold">Upozornění mimo aplikaci</h2>
          <p className={`text-sm mt-0.5 ${on ? "text-emerald-300" : "text-zinc-400"}`} role="status">
            {deviceStateLabel(state)}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {state === "off" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void enable()}
              className="motion-press rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 px-3 py-2 text-sm font-medium text-white"
            >
              Zapnout na tomto zařízení
            </button>
          )}
          {on && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => void sendTest()}
                className="motion-press rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-3 py-2 text-sm"
              >
                Poslat test
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void disable()}
                className="motion-press rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-3 py-2 text-sm"
              >
                Vypnout na tomto zařízení
              </button>
            </>
          )}
        </div>
      </div>
      {detail && <p className="text-sm text-zinc-400">{detail}</p>}
      {message && <p className="text-sm text-zinc-300" aria-live="polite">{message}</p>}
      <p className="text-xs text-zinc-500">
        Připomínky se vždy ukážou i ve zvonku aplikace. Upozornění mimo aplikaci posílá server přes push službu
        prohlížeče; zastaralé (starší než 12 h) ani už vyřízené se neposílají.
      </p>
    </section>
  );
}
