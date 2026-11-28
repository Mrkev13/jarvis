/**
 * MRK-157: stránka Počítač – typy odpovědi `GET /devices` a čisté pomocné funkce (testy: lib.test.mjs).
 * Backend: backend/modules/computer (docs/computer.md). Žádný token ani hash se do frontendu nikdy nedostane.
 */
import type { Tone } from "../../lib/ui.ts";

export type DeviceApp = { id: string; name: string };
export type DeviceDisk = { name: string; free_gb: number; total_gb: number };
export type DeviceStatus = {
  cpu_percent: number | null; ram_percent: number | null; disks: DeviceDisk[]; running: string[];
  uptime_minutes: number | null;
};
export type DeviceCommand = {
  id: number; kind: "launch_app" | "power" | "power_cancel"; payload: Record<string, unknown>;
  status: "queued" | "delivered" | "succeeded" | "failed" | "expired"; label: string;
  created_at: string | null; completed_at: string | null; result_message: string | null;
};
export type Device = {
  id: number; name: string; platform: string; agent_version: string | null; created_at: string | null;
  last_seen_at: string | null; revoked: boolean; online: boolean; status: DeviceStatus | null; apps: DeviceApp[];
  recent: DeviceCommand[];
};
export type PairingCode = { code: string; expires_at: string };
export type PowerAction = "shutdown" | "sleep" | "lock";

export const POWER_LABELS: Record<PowerAction, string> = { shutdown: "Vypnout", sleep: "Uspat", lock: "Zamknout" };

/** Časovač napájení (sekundy) – stejný strop jako backend (4 h). */
export const DELAY_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: "Hned" },
  { value: 15 * 60, label: "Za 15 min" },
  { value: 30 * 60, label: "Za 30 min" },
  { value: 60 * 60, label: "Za hodinu" },
  { value: 2 * 3600, label: "Za 2 hodiny" },
  { value: 4 * 3600, label: "Za 4 hodiny" },
];

const STATUS_META: Record<DeviceCommand["status"], { label: string; tone: Tone }> = {
  queued: { label: "Čeká na PC", tone: "info" },
  delivered: { label: "Provádí se", tone: "info" },
  succeeded: { label: "Hotovo", tone: "success" },
  failed: { label: "Selhalo", tone: "danger" },
  expired: { label: "Propadlo", tone: "warning" },
};

export function commandStatus(status: DeviceCommand["status"]) {
  return STATUS_META[status] ?? { label: status, tone: "neutral" as Tone };
}

/** Příkaz ještě běží (stránka se má obnovovat častěji). */
export function hasPendingCommand(devices: Device[]): boolean {
  return devices.some((d) => d.recent.some((c) => c.status === "queued" || c.status === "delivered"));
}

/** „před 2 min“, „před 3 h“, „27. 11. 14:05“ – čas od posledního ohlášení PC. */
export function lastSeenLabel(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "zatím se neohlásil";
  const t = Date.parse(iso);
  const secs = Math.max(0, Math.round((now - t) / 1000));
  if (secs < 60) return "právě teď";
  if (secs < 3600) return `před ${Math.floor(secs / 60)} min`;
  if (secs < 24 * 3600) return `před ${Math.floor(secs / 3600)} h`;
  return new Date(t).toLocaleString("cs-CZ", { timeZone: "Europe/Prague", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function uptimeLabel(minutes: number | null | undefined): string {
  if (minutes == null) return "–";
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  if (h < 48) return `${h} h ${minutes % 60} min`;
  return `${Math.floor(h / 24)} dní`;
}

export function pctLabel(v: number | null | undefined): string {
  return v == null ? "–" : `${Math.round(v)} %`;
}

/** „C: 120 GB volno z 476 GB“ + podíl volného místa (0–1) pro ukazatel. */
export function diskLabel(d: DeviceDisk): { text: string; freeShare: number } {
  const fmt = (v: number) => v.toLocaleString("cs-CZ", { maximumFractionDigits: v >= 100 ? 0 : 1 });
  return { text: `${d.name} ${fmt(d.free_gb)} GB volno z ${fmt(d.total_gb)} GB`, freeShare: d.total_gb > 0 ? d.free_gb / d.total_gb : 0 };
}

export function runningNames(d: Device): string[] {
  const byId = new Map(d.apps.map((a) => [a.id, a.name]));
  return (d.status?.running ?? []).map((id) => byId.get(id) ?? id);
}

/** Zbývající minuty platnosti párovacího kódu (0 = propadl). */
export function codeMinutesLeft(expiresAt: string, now: number = Date.now()): number {
  return Math.max(0, Math.ceil((Date.parse(expiresAt) - now) / 60000));
}

export function timeLabel(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("cs-CZ", { timeZone: "Europe/Prague", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function capitalize(text: string): string {
  return text ? text[0].toLocaleUpperCase("cs-CZ") + text.slice(1) : text;
}
