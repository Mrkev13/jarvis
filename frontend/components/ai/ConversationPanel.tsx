"use client";

import { useEffect, useRef, useState } from "react";
import { Button, ConfirmDialog, EmptyState, ErrorState, fieldClass, LoadingState } from "@/components/ui";
import type { Conversation } from "@/lib/aiChat";
import { formatDateTime } from "@/lib/format";
import { cx } from "@/lib/ui";

function ConversationRow({
  conversation: c,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(c.title);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const renameRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  if (editing) {
    return (
      <li>
        <form
          className="flex items-center gap-1.5 rounded-[var(--radius-control)] border border-accent/40 bg-surface-2 p-1.5"
          onSubmit={async (e) => {
            e.preventDefault();
            setSaving(true);
            const ok = await onRename(title);
            setSaving(false);
            if (ok) {
              setEditing(false);
              queueMicrotask(() => renameRef.current?.focus());
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setEditing(false);
              queueMicrotask(() => renameRef.current?.focus());
            }
          }}
        >
          <label className="sr-only" htmlFor={`conv-title-${c.id}`}>
            Nový název chatu
          </label>
          <input
            id={`conv-title-${c.id}`}
            ref={inputRef}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={cx(fieldClass, "min-h-9 py-1")}
          />
          <Button type="submit" size="sm" variant="primary" busy={saving} busyLabel="…" disabled={!title.trim()}>
            Uložit
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)} aria-label="Zrušit přejmenování">
            ✕
          </Button>
        </form>
      </li>
    );
  }

  return (
    <li className={cx("group relative flex items-center rounded-[var(--radius-control)] transition-colors", active ? "bg-surface-2" : "hover:bg-surface")}>
      {active ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" /> : null}
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className="min-h-11 min-w-0 flex-1 rounded-[var(--radius-control)] px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
      >
        <span className={cx("block truncate text-sm", active ? "font-medium text-ink" : "text-ink-2")}>{c.title}</span>
        <span className="block text-[11px] tabular-nums text-ink-faint">{formatDateTime(new Date(c.updatedAt).toISOString())}</span>
      </button>
      {/* akce: na myši při najetí / fokusu, na dotyku vždy */}
      <div className="flex shrink-0 items-center opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100 pointer-coarse:opacity-100">
        <button
          ref={renameRef}
          type="button"
          onClick={() => {
            setTitle(c.title);
            setEditing(true);
          }}
          aria-label={`Přejmenovat chat ${c.title}`}
          className="grid h-9 w-9 place-items-center rounded-md text-ink-muted hover:bg-hover hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 pointer-coarse:h-11 pointer-coarse:w-11"
        >
          <span aria-hidden="true">✎</span>
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Smazat chat ${c.title}`}
          className="grid h-9 w-9 place-items-center rounded-md text-ink-muted hover:bg-danger/10 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 pointer-coarse:h-11 pointer-coarse:w-11"
        >
          <span aria-hidden="true">🗑</span>
        </button>
      </div>
    </li>
  );
}

/**
 * Konverzace AI asistenta – stejný obsah v postranním panelu (≥ lg) i v Draweru (mobil/tablet):
 * nový chat, obnovení, výběr, přejmenování na místě, smazání přes ConfirmDialog.
 */
export function ConversationPanel({
  conversations,
  activeId,
  loading,
  refreshing,
  error,
  creating,
  onNew,
  onRefresh,
  onSelect,
  onRename,
  onDelete,
  showHeading = true,
}: {
  conversations: Conversation[];
  activeId: number | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  creating: boolean;
  onNew: () => void;
  onRefresh: () => void;
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => Promise<boolean>;
  onDelete: (id: number) => Promise<void>;
  showHeading?: boolean;
}) {
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {showHeading ? <h2 className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink-muted">Konverzace</h2> : null}
      <div className="flex items-center gap-2">
        <Button variant="secondary" onClick={onNew} busy={creating} busyLabel="Zakládám…" className="flex-1">
          + Nový chat
        </Button>
        <Button variant="ghost" onClick={onRefresh} busy={refreshing} busyLabel="Obnovuji…" disabled={loading}>
          Obnovit
        </Button>
      </div>
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1" aria-busy={loading || refreshing}>
        {loading && !conversations.length ? (
          <LoadingState lines={3} label="Načítám konverzace…" />
        ) : error && !conversations.length ? (
          <ErrorState message={error} onRetry={onRefresh} />
        ) : !conversations.length ? (
          <EmptyState compact>Zatím žádné konverzace.</EmptyState>
        ) : (
          <>
            {error ? <ErrorState className="mb-2" message={error} /> : null}
            <ul className="space-y-0.5" aria-label="Seznam konverzací">
              {conversations.map((c) => (
                <ConversationRow
                  key={c.id}
                  conversation={c}
                  active={c.id === activeId}
                  onSelect={() => onSelect(c.id)}
                  onRename={(t) => onRename(c.id, t)}
                  onDelete={() => setDeleting(c)}
                />
              ))}
            </ul>
          </>
        )}
      </div>
      <ConfirmDialog
        open={deleting !== null}
        title={`Smazat chat „${deleting?.title ?? ""}“?`}
        message="Smaže se celá konverzace včetně zpráv. Změny, které AI už provedla, zůstanou."
        confirmLabel="Smazat chat"
        busyLabel="Mažu…"
        danger
        onCancel={() => setDeleting(null)}
        onConfirm={async () => {
          if (deleting) await onDelete(deleting.id);
          setDeleting(null);
        }}
      />
    </div>
  );
}
