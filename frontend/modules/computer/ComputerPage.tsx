"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  StatusBadge,
  fieldClass,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import {
  DELAY_OPTIONS, POWER_LABELS, codeMinutesLeft, commandStatus, diskLabel, hasPendingCommand, lastSeenLabel, pctLabel,
  runningNames, timeLabel, uptimeLabel, type Device, type PairingCode, type PowerAction,
} from "./lib";

type DevicesResponse = { devices: Device[] };

/**
 * Počítač (MRK-157): spárovaná PC s aplikací „Jarvis pro PC“ (desktop/). Stav, spuštění aplikace ze seznamu PC,
 * vypnutí / uspání / zamknutí s časovačem a historie příkazů. Klik na tlačítko = potvrzení (vypnutí přes dialog);
 * Jarvis v chatu zakládá stejné příkazy až po potvrzení pending akce. docs/computer.md.
 */
export default function ComputerPage() {
  // Čekající příkaz → obnovovat častěji (výsledek z PC přijde do pár sekund). Odvozeno z posledních dat, bez efektu.
  const [fast, setFast] = useState(false);
  const res = useApiResource<DevicesResponse>("/devices", { refreshMs: fast ? 3000 : 15000 });
  const devices = res.data?.devices ?? [];
  const pending = hasPendingCommand(devices);
  if (pending !== fast) setFast(pending);
  const [pairing, setPairing] = useState<PairingCode | null>(null);
  const [pairBusy, setPairBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);

  async function createCode() {
    setPairBusy(true);
    try {
      setPairing(await apiJson<PairingCode>("/devices/pairing-code", { method: "POST" }));
    } catch (e) {
      setNotice({ text: errorMessage(e), ok: false });
    } finally {
      setPairBusy(false);
    }
  }

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · Počítač</HudLabel>}
        title="Počítač"
        subtitle="Ovládání PC přes aplikaci Jarvis pro PC – spuštění aplikací, vypnutí, uspání, zamknutí a stav."
        actions={
          <Button variant="primary" busy={pairBusy} busyLabel="Vytvářím kód…" onClick={() => void createCode()} data-pair-button="">
            Spárovat počítač
          </Button>
        }
      />

      {notice ? (
        <p role="status" aria-live="polite" className={notice.ok ? "mb-4 text-sm text-success" : "mb-4 text-sm text-danger"} data-computer-notice="">
          {notice.text}
        </p>
      ) : null}

      {pairing ? <PairingCard code={pairing} onClose={() => { setPairing(null); void res.reload(); }} /> : null}

      {res.loading && !res.data ? (
        <LoadingState lines={3} label="Načítám počítače…" />
      ) : res.status === "error" && !res.data ? (
        <ErrorState message={res.error ?? "Počítače se nepodařilo načíst."} onRetry={() => void res.reload()} />
      ) : devices.length === 0 ? (
        <EmptyState>
          <p className="font-medium text-ink">Zatím žádný spárovaný počítač.</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-left text-sm text-ink-2">
            <li>Nainstaluj aplikaci Jarvis pro PC (GitHub Actions → Desktop agent → artefakt <code>jarvis-pro-pc-windows</code>).</li>
            <li>Klikni na <strong>Spárovat počítač</strong> a kód opiš do aplikace (platí 10 minut).</li>
          </ol>
        </EmptyState>
      ) : (
        <div className="space-y-6">
          {devices.map((d) => (
            <DeviceCard key={d.id} device={d} onChanged={() => void res.reload()} onNotice={setNotice} />
          ))}
        </div>
      )}
    </ContentContainer>
  );
}

function PairingCard({ code, onClose }: { code: PairingCode; onClose: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(t);
  }, []);
  const left = codeMinutesLeft(code.expires_at, now);
  const hub = typeof window !== "undefined" ? apiBase() : "";
  return (
    <Card className="mb-6" data-pairing-card="">
      <CardHeader title="Párovací kód" description={left > 0 ? `Platí ještě ${left} min a jen jednou.` : "Kód propadl – vytvoř nový."} />
      <p className="mt-2 font-mono text-3xl tracking-[0.2em] text-ink" data-pairing-code="">{code.code}</p>
      <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-ink-2">
        <li>V aplikaci Jarvis pro PC vyplň <strong>Adresu Hubu</strong>{hub ? <>: <code className="break-all" data-pairing-hub="">{hub}</code></> : null}</li>
        <li>Opiš kód, zadej název počítače a klikni na <strong>Spárovat</strong>.</li>
      </ol>
      <div className="mt-4">
        <Button size="sm" variant="secondary" onClick={onClose}>Hotovo</Button>
      </div>
    </Card>
  );
}

/** Adresa API Hubu (stejná, jakou volá frontend) – tu agent potřebuje. */
function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  return (env && /^https?:\/\//.test(env) ? env : window.location.origin).replace(/\/+$/, "");
}

function DeviceCard({ device: d, onChanged, onNotice }: {
  device: Device; onChanged: () => void; onNotice: (n: { text: string; ok: boolean }) => void;
}) {
  const [delay, setDelay] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<PowerAction | null>(null);
  const [revoke, setRevoke] = useState(false);
  const running = runningNames(d);
  const status = d.status;

  async function send(key: string, kind: string, payload: Record<string, unknown>) {
    setBusy(key);
    try {
      const r = await apiJson<{ command: { label: string } }>(`/devices/${d.id}/commands`, jsonBody("POST", { kind, payload }));
      onNotice({ text: `Odesláno: ${r.command.label}. PC ho provede do pár sekund.`, ok: true });
      onChanged();
    } catch (e) {
      onNotice({ text: errorMessage(e), ok: false });
    } finally {
      setBusy(null);
    }
  }

  function power(action: PowerAction) {
    return send(`power-${action}`, "power", { action, delay_seconds: delay });
  }

  return (
    <Card data-device={d.id}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">{d.name}</h2>
          <p className="text-sm text-ink-muted">
            Naposledy {lastSeenLabel(d.last_seen_at)}{d.agent_version ? ` · aplikace ${d.agent_version}` : ""}
          </p>
        </div>
        <StatusBadge tone={d.online ? "success" : "neutral"} dot={d.online} data-device-online={d.online ? "1" : "0"}>
          {d.online ? "Online" : "Offline"}
        </StatusBadge>
      </div>

      {status ? (
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4" data-device-status="">
          <div><dt className="text-ink-muted">Procesor</dt><dd className="tabular-nums text-ink">{pctLabel(status.cpu_percent)}</dd></div>
          <div><dt className="text-ink-muted">Paměť</dt><dd className="tabular-nums text-ink">{pctLabel(status.ram_percent)}</dd></div>
          <div><dt className="text-ink-muted">Zapnuto</dt><dd className="tabular-nums text-ink">{uptimeLabel(status.uptime_minutes)}</dd></div>
          <div><dt className="text-ink-muted">Běží</dt><dd className="text-ink">{running.length ? running.join(", ") : "nic ze seznamu"}</dd></div>
        </dl>
      ) : null}
      {status?.disks.length ? (
        <ul className="mt-3 space-y-1 text-xs text-ink-2" aria-label="Disky">
          {status.disks.map((disk) => {
            const info = diskLabel(disk);
            return (
              <li key={disk.name} className="flex items-center gap-2">
                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                  <span className={info.freeShare < 0.1 ? "block h-full bg-danger" : "block h-full bg-accent"} style={{ width: `${Math.round((1 - info.freeShare) * 100)}%` }} />
                </span>
                <span className="tabular-nums">{info.text}</span>
              </li>
            );
          })}
        </ul>
      ) : null}

      <section className="mt-5" aria-label="Aplikace">
        <h3 className="text-sm font-medium text-ink">Spustit</h3>
        {d.apps.length ? (
          <div className="mt-2 flex flex-wrap gap-2" data-device-apps="">
            {d.apps.map((a) => (
              <Button key={a.id} size="sm" variant="secondary" disabled={!d.online || busy !== null} busy={busy === `app-${a.id}`}
                onClick={() => void send(`app-${a.id}`, "launch_app", { app_id: a.id })} data-launch={a.id}>
                {a.name}
              </Button>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-sm text-ink-muted">Aplikace na PC zatím nic nenahlásila – přidej je v okně Jarvis pro PC.</p>
        )}
      </section>

      <section className="mt-5" aria-label="Napájení">
        <h3 className="text-sm font-medium text-ink">Napájení</h3>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`delay-${d.id}`}>Kdy</label>
          <select id={`delay-${d.id}`} className={fieldClass} value={delay} onChange={(e) => setDelay(Number(e.target.value))} data-power-delay="">
            {DELAY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {(Object.keys(POWER_LABELS) as PowerAction[]).map((a) => (
            <Button key={a} size="sm" variant={a === "shutdown" ? "danger" : "secondary"} disabled={!d.online || busy !== null}
              busy={busy === `power-${a}`} onClick={() => (a === "lock" ? void power(a) : setConfirm(a))} data-power={a}>
              {POWER_LABELS[a]}
            </Button>
          ))}
          <Button size="sm" variant="ghost" disabled={!d.online || busy !== null} busy={busy === "cancel"}
            onClick={() => void send("cancel", "power_cancel", {})} data-power-cancel="">
            Zrušit časovač
          </Button>
        </div>
        {!d.online ? <p className="mt-2 text-xs text-ink-muted">PC je offline – příkazy půjde poslat, až se aplikace zase ohlásí.</p> : null}
      </section>

      <section className="mt-5" aria-label="Poslední příkazy">
        <h3 className="text-sm font-medium text-ink">Poslední příkazy</h3>
        {d.recent.length ? (
          <ul className="mt-2 divide-y divide-line-subtle text-sm" data-device-recent="">
            {d.recent.map((c) => {
              const meta = commandStatus(c.status);
              return (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                  <span className="text-ink">{c.label}<span className="ml-2 text-xs text-ink-muted">{timeLabel(c.created_at)}</span></span>
                  <span className="flex items-center gap-2">
                    {c.result_message && c.status !== "succeeded" ? <span className="text-xs text-ink-muted">{c.result_message}</span> : null}
                    <StatusBadge tone={meta.tone}>{meta.label}</StatusBadge>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-ink-muted">Zatím žádné.</p>
        )}
      </section>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-line-subtle pt-4">
        <Button size="sm" variant="ghost" onClick={() => setRevoke(true)} data-device-revoke="">Odvolat počítač</Button>
      </div>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm ? `${POWER_LABELS[confirm]} počítač „${d.name}“?` : ""}
        message={confirm === "shutdown" ? "Neuložená práce na PC se ztratí. Časovač jde zrušit tady, v aplikaci i z ikony v liště." : "Časovač jde zrušit tady, v aplikaci i z ikony v liště."}
        confirmLabel={confirm ? `${POWER_LABELS[confirm]} ${DELAY_OPTIONS.find((o) => o.value === delay)?.label.toLowerCase() ?? ""}` : ""}
        danger={confirm === "shutdown"}
        onConfirm={() => { const a = confirm; setConfirm(null); if (a) void power(a); }}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={revoke}
        title={`Odvolat počítač „${d.name}“?`}
        message="Token v PC přestane platit hned a čekající příkazy propadnou. Pro další použití ho bude potřeba spárovat znovu."
        confirmLabel="Odvolat"
        onConfirm={async () => {
          try {
            await apiJson(`/devices/${d.id}/revoke`, { method: "POST" });
            onNotice({ text: `Počítač „${d.name}“ odvolán.`, ok: true });
          } catch (e) {
            onNotice({ text: errorMessage(e), ok: false });
          } finally {
            setRevoke(false);
            onChanged();
          }
        }}
        onCancel={() => setRevoke(false)}
      />
    </Card>
  );
}
