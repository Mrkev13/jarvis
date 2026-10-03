"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AreaBadge, Button, Drawer, EmptyState, ErrorState, LoadingState, StatusBadge } from "@/components/ui";
import { apiFetch, apiJson, errorMessage } from "@/lib/api";
import { formatDateTime, parseApiInstant } from "@/lib/format";
import { useIncreaseSignal } from "@/lib/motion";
import { cx, severityTone } from "@/lib/ui";

type NotificationItem = {
  id: number;
  area: string;
  title: string;
  message: string;
  severity: "info" | "warning" | "important" | string;
  read: boolean;
  created_at: string | null;
  action_url?: string | null;
  resolved?: boolean;
};

type NotificationSummary = {
  unread: number;
  important: number;
  warning: number;
  info: number;
};

const EMPTY_SUMMARY: NotificationSummary = { unread: 0, important: 0, warning: 0, info: 0 };

/**
 * Zvonek notifikací + boční panel (Roadmap 4B: Drawer – fokus, Escape, návrat fokusu).
 * Souhrn se obnovuje každých 30 s; seznam se načítá při otevření panelu.
 */
export default function NotificationsBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState<NotificationSummary>(EMPTY_SUMMARY);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | "all" | null>(null);

  // UI-only: první úspěšné načtení souhrnu (puls badge až při dalším nárůstu, ne při načtení stránky).
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const unread = summary.unread || 0;
  const unreadIncrease = useIncreaseSignal(unread, summaryLoaded);

  const refreshSummary = useCallback(async () => {
    try {
      const res = await apiFetch("/notifications/summary");
      if (!res.ok) return; // souhrn je doplňková informace – tichá chyba
      const data = (await res.json()) as NotificationSummary;
      setSummary({
        unread: Number(data.unread) || 0,
        important: Number(data.important) || 0,
        warning: Number(data.warning) || 0,
        info: Number(data.info) || 0,
      });
      setSummaryLoaded(true);
    } catch {
      return;
    }
  }, []);

  const refreshList = useCallback(async () => {
    const data = await apiJson<NotificationItem[]>("/notifications");
    setItems(Array.isArray(data) ? data : []);
  }, []);

  async function openPanel() {
    setOpen(true);
    setLoading(true);
    setError(null);
    try {
      await apiFetch("/notifications/generate", { method: "POST" }).catch(() => undefined);
      await Promise.all([refreshSummary(), refreshList()]);
    } catch (err) {
      setError(errorMessage(err, "Notifikace se nepodařilo načíst."));
    } finally {
      setLoading(false);
    }
  }

  async function act(id: number | "all", path: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiJson(path, { method: "PATCH" });
      await Promise.all([refreshSummary(), refreshList()]);
    } catch (err) {
      setError(errorMessage(err, "Akce se nepovedla."));
    } finally {
      setBusyId(null);
    }
  }

  useEffect(() => {
    queueMicrotask(() => void refreshSummary());
    const t = window.setInterval(() => void refreshSummary(), 30000);
    return () => window.clearInterval(t);
  }, [refreshSummary]);

  const sorted = useMemo(
    () =>
      [...items].sort((a, b) => {
        const at = a.created_at ? parseApiInstant(a.created_at).getTime() : 0;
        const bt = b.created_at ? parseApiInstant(b.created_at).getTime() : 0;
        return bt - at;
      }),
    [items],
  );

  return (
    <>
      <button
        type="button"
        aria-label={unread > 0 ? `Notifikace, ${unread} nepřečtených` : "Notifikace"}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : void openPanel())}
        className="motion-press relative grid h-10 w-10 place-items-center rounded-lg border border-line bg-surface text-sm transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
      >
        <span aria-hidden="true" className="select-none">🔔</span>
        {unread > 0 && (
          <span
            // key se mění jen při NÁRŮSTU unread → puls se přehraje, ne při každém obnovení
            key={unreadIncrease}
            aria-hidden="true"
            className={`absolute -right-1.5 -top-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full border border-warning/50 bg-app px-1 text-[11px] font-semibold tabular-nums text-warning ${unreadIncrease > 0 ? "motion-pulse" : ""}`}
          >
            {unread}
          </span>
        )}
      </button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Notifikace"
        description={
          <span className="flex flex-wrap gap-x-2">
            <span>{summary.unread} nepřečtených</span>
            {summary.important ? <span className="text-danger">{summary.important} důležitých</span> : null}
            {summary.warning ? <span className="text-warning">{summary.warning} varování</span> : null}
          </span>
        }
        actions={
          summary.unread > 0 ? (
            <Button size="sm" variant="ghost" busy={busyId === "all"} busyLabel="…" onClick={() => void act("all", "/notifications/read-all")}>
              Přečíst vše
            </Button>
          ) : null
        }
      >
        <div className="space-y-3 p-4" aria-busy={loading}>
          {error ? <ErrorState message={error} onRetry={() => void openPanel()} /> : null}
          {loading && !items.length ? (
            <LoadingState lines={3} label="Načítám notifikace…" />
          ) : !error && sorted.length === 0 ? (
            <EmptyState>Žádné aktivní notifikace.</EmptyState>
          ) : (
            <ul className="space-y-2" aria-label="Seznam notifikací">
              {sorted.map((n) => {
                const sev = severityTone(n.severity);
                const href = n.action_url && n.action_url.startsWith("/") ? n.action_url : null;
                const busy = busyId === n.id;
                return (
                  <li
                    key={n.id}
                    aria-busy={busy || undefined}
                    className={cx(
                      "rounded-[var(--radius-control)] border p-3",
                      n.read ? "border-line-subtle bg-surface/60" : "border-line bg-surface-2",
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      {!n.read ? (
                        <span className="inline-flex items-center gap-1 font-medium text-accent-strong">
                          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent" />
                          Nové
                        </span>
                      ) : (
                        <span className="text-ink-muted">Přečteno</span>
                      )}
                      <StatusBadge tone={sev.tone}>{sev.label}</StatusBadge>
                      <AreaBadge area={n.area} />
                      <time className="ml-auto tabular-nums text-ink-muted" dateTime={n.created_at ?? undefined}>
                        {formatDateTime(n.created_at)}
                      </time>
                    </div>
                    <div className={cx("mt-1.5 break-words font-medium", n.read ? "text-ink-2" : "text-ink")}>{n.title}</div>
                    {n.message ? <p className="mt-0.5 whitespace-pre-wrap break-words text-sm text-ink-muted">{n.message}</p> : null}
                    <div className="mt-2.5 flex flex-wrap gap-2">
                      {href ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setOpen(false);
                            router.push(href);
                          }}
                        >
                          Otevřít
                        </Button>
                      ) : null}
                      {!n.read ? (
                        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(n.id, `/notifications/${n.id}/read`)}>
                          Přečteno
                        </Button>
                      ) : null}
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(n.id, `/notifications/${n.id}/resolve`)}>
                        Vyřešit
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Drawer>
    </>
  );
}
