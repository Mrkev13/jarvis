"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { IconName } from "@/lib/icons";
import Link from "next/link";
import { JarvisAvatar } from "@/components/jarvis/JarvisAvatar";
import { useOpenQuickAdd } from "@/components/quick-add/QuickAddProvider";
import {
  AccentLine,
  AreaBadge,
  Button,
  Card,
  CardHeader,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  StatusBadge,
  TextLink,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { useTodayActions, type RowError, type TodayNotice } from "@/hooks/useTodayActions";
import {
  actionLabel,
  groupTimeline,
  isEmptyDay,
  itemsLabel,
  moduleAction,
  normalizeToday,
  SEVERITY_META,
  shortDate,
  STATUS_META,
  TYPE_LABELS,
  untilLabel,
  type SnoozeOption,
  type TodayActionId,
  type TodayItem,
  type TodayPayload,
} from "@/lib/today";
import { cx } from "@/lib/ui";

const CORE_ACTIONS: TodayActionId[] = ["complete", "snooze", "record_result"];

type ActionsCtx = {
  busyKey: string | null;
  rowErrors: Record<string, RowError>;
  snoozeOptions: SnoozeOption[];
  run: (item: TodayItem, action: TodayActionId, option?: SnoozeOption) => Promise<void>;
};
const ActionsContext = createContext<ActionsCtx | null>(null);

/**
 * Režim Dnes (Roadmap 4G): „Co dnes potřebuje moji pozornost?" Jeden sloupec, jeden dotaz (GET /today),
 * deterministicky. Řídicí centrum = celý život napříč moduly; Dnes = jen to, na čem záleží dnes.
 */
export default function TodayPage() {
  const resource = useApiResource<unknown>("/today");
  const openQuickAdd = useOpenQuickAdd();
  const data: TodayPayload | null = resource.data ? normalizeToday(resource.data) : null;
  // Roadmap 4H: akce z řádků → po úspěchu jedno obnovení GET /today (žádné dotazování na pozadí)
  const actions = useTodayActions(resource.reload);

  const addButton = (
    <Button variant="primary" onClick={openQuickAdd} aria-haspopup="dialog">
      <span aria-hidden="true">+</span> Přidat
    </Button>
  );

  return (
    <ContentContainer width="narrow">
      <PageHeader
        eyebrow={
          <span className="inline-flex items-center gap-2">
            <JarvisAvatar state="idle" size="sm" />
            <HudLabel>Standa Hub · režim dnes</HudLabel>
          </span>
        }
        title="Dnes"
        subtitle={data ? capitalize(data.date_label) : "Co dnes potřebuje tvou pozornost."}
        actions={
          <>
            {addButton}
            <Button variant="secondary" onClick={() => void resource.reload()} busy={resource.refreshing} busyLabel="Obnovuji…">
              Obnovit
            </Button>
          </>
        }
      />

      <ActionNotice notice={actions.notice} busy={actions.busyKey === "undo"} onDismiss={actions.dismissNotice} />

      {resource.loading ? (
        <LoadingState lines={4} label="Načítám dnešek…" />
      ) : resource.status === "error" || !data ? (
        <ErrorState message={resource.error ?? "Dnešek se nepodařilo načíst."} onRetry={() => void resource.reload()} retrying={resource.refreshing} />
      ) : isEmptyDay(data) ? (
        <EmptyDay data={data} addButton={addButton} />
      ) : (
        <ActionsContext.Provider value={{ busyKey: actions.busyKey, rowErrors: actions.rowErrors, snoozeOptions: data.snooze_options, run: actions.run }}>
          {resource.error ? <ErrorState message={`Obnovení selhalo: ${resource.error}`} /> : null}
          <DaySummary data={data} />
          <Section id="attention" title="Vyžaduje pozornost" icon="alert" error={data.errors.attention}>
            {data.attention.length ? (
              <ItemList label="Vyžaduje pozornost" items={data.attention} />
            ) : (
              <EmptyState compact>Nic po termínu ani k vyřízení.</EmptyState>
            )}
          </Section>
          <Section
            id="plan"
            title="Dnešní plán"
            icon="target"
            error={data.errors.priorities}
            actions={<TextLink href="/planner">Plánovač →</TextLink>}
            description="Priority z denního plánovače (co není v časové ose ani v pozornosti)."
          >
            {data.priorities.length ? (
              <ItemList label="Dnešní plán" items={data.priorities} />
            ) : (
              <EmptyState compact>Plánovač dnes nic dalšího nenavrhuje.</EmptyState>
            )}
          </Section>
          <Section id="timeline" title="Časová osa" icon="clock" error={data.errors.timeline}>
            <Timeline data={data} />
          </Section>
          <Upcoming data={data} />
        </ActionsContext.Provider>
      )}
    </ContentContainer>
  );
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function DaySummary({ data }: { data: TodayPayload }) {
  const { next, remaining, attention, done } = data.summary;
  return (
    <Card aria-labelledby="today-next-title" className="overflow-hidden p-0 md:p-0">
      <AccentLine />
      <div className="p-4 md:p-5">
        <HudLabel as="p" tone="accent">
          Teď {data.now_local}
        </HudLabel>
        <h2 id="today-next-title" className="mt-1 text-lg font-semibold text-ink md:text-xl">
          {next ? (
            <>
              Další: {next.title} v {next.time}
            </>
          ) : remaining ? (
            "Na dnešek nic s pevným časem nezbývá"
          ) : (
            "Dnešní termíny jsou vyřízené"
          )}
        </h2>
        {next ? (
          <p className="mt-0.5 text-sm text-ink-2">
            {untilLabel(next.minutes_until)}
            {next.subtitle ? ` · ${next.subtitle}` : ""}
            {next.href ? (
              <>
                {" · "}
                <Link href={next.href} className="text-accent-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70">
                  Otevřít<span className="sr-only"> {next.title}</span>
                </Link>
              </>
            ) : null}
          </p>
        ) : null}
        <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
          <Stat label="zbývá dnes" value={remaining} />
          <Stat label="pozornost" value={attention} tone={attention ? "warning" : undefined} />
          <Stat label="hotovo" value={done} />
        </dl>
      </div>
    </Card>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "warning" }) {
  return (
    <div className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2 py-2">
      <dt className="text-[11px] text-ink-muted">{label}</dt>
      <dd className={cx("text-xl font-semibold tabular-nums", tone === "warning" ? "text-warning" : "text-ink")}>{value}</dd>
    </div>
  );
}

function Section({
  id,
  title,
  icon,
  description,
  actions,
  error,
  children,
}: {
  id: string;
  title: string;
  icon: IconName;
  description?: string;
  actions?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <Card aria-labelledby={`today-${id}-title`} data-section={id}>
      <CardHeader title={<span id={`today-${id}-title`}>{title}</span>} icon={icon} description={description} actions={actions} />
      {/* chyba jednoho zdroje: jen tahle sekce, ostatní běží dál */}
      {error ? <ErrorState message={error} /> : children}
    </Card>
  );
}

function ItemList({ label, items, nextId }: { label: string; items: TodayItem[]; nextId?: string | null }) {
  return (
    <ul aria-label={label} className="space-y-2">
      {items.map((it) => (
        <TodayRow key={it.id} item={it} isNext={it.id === nextId} />
      ))}
    </ul>
  );
}

function TodayRow({ item, isNext }: { item: TodayItem; isNext?: boolean }) {
  const status = STATUS_META[item.status];
  const quiet = item.status === "done" || item.status === "past";
  const ctx = useContext(ActionsContext);
  const [snoozeOpen, setSnoozeOpen] = useState(false);
  const rowError = ctx?.rowErrors[item.id];
  const actions = ctx ? item.actions : [];
  const body = (
    <div className="flex min-h-11 items-start gap-3">
      {item.time && item.status !== "overdue" ? (
        <span className={cx("w-12 shrink-0 pt-0.5 font-mono text-sm tabular-nums", isNext ? "text-accent-strong" : "text-ink-2")}>{item.time}</span>
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          {isNext ? (
            <StatusBadge tone="accent" dot>
              Další
            </StatusBadge>
          ) : null}
          {item.severity && !quiet ? <StatusBadge tone={SEVERITY_META[item.severity].tone}>{SEVERITY_META[item.severity].label}</StatusBadge> : null}
          {item.type !== "planner" && item.type !== "notification" ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
          {item.priority ? <StatusBadge tone="accent">Plán #{item.priority}</StatusBadge> : null}
          {item.area ? <AreaBadge area={item.area} /> : null}
        </div>
        <div className={cx("break-words font-medium text-ink", item.status === "done" && "line-through decoration-ink-faint")}>
          <span className="sr-only">{TYPE_LABELS[item.type] ?? "Položka"}: </span>
          {item.title}
        </div>
        {item.subtitle ? <div className="mt-0.5 break-words text-sm text-ink-muted">{item.subtitle}</div> : null}
      </div>
    </div>
  );
  const box = cx(
    "rounded-[var(--radius-control)] border px-3 py-2.5 transition-colors md:px-4",
    isNext ? "border-accent/50 bg-accent/5" : item.status === "overdue" ? "border-danger/30 bg-danger/5" : "border-line-subtle bg-surface-2",
    item.href && "hover:border-accent/40",
    quiet && "opacity-70",
  );
  return (
    <li
      data-item={item.id}
      data-status={item.status}
      data-actionable={actions.length ? "" : undefined}
      aria-current={isNext ? "true" : undefined}
    >
      <div className={box}>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          {item.href ? (
            <Link
              href={item.href}
              className="block min-w-0 flex-1 rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              {body}
            </Link>
          ) : (
            <div className="min-w-0 flex-1">{body}</div>
          )}
          {actions.length && ctx ? (
            <RowActions item={item} ctx={ctx} snoozeOpen={snoozeOpen} onToggleSnooze={() => setSnoozeOpen((o) => !o)} />
          ) : null}
        </div>
        {snoozeOpen && ctx && actions.includes("snooze") ? (
          <SnoozeOptions item={item} ctx={ctx} onClose={() => setSnoozeOpen(false)} />
        ) : null}
        {rowError && ctx ? (
          <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <span className="min-w-0 flex-1">{rowError.message}</span>
            <Button size="sm" variant="secondary" disabled={ctx.busyKey !== null} onClick={() => void ctx.run(item, rowError.action, rowError.option)}>
              Zkusit znovu
            </Button>
          </div>
        ) : null}
      </div>
    </li>
  );
}

/** Nejvýš jedna hlavní akce + „Odložit"; výsledek zkoušky = odkaz do Školy (žádný editor v Dnes). */
function RowActions({ item, ctx, snoozeOpen, onToggleSnooze }: { item: TodayItem; ctx: ActionsCtx; snoozeOpen: boolean; onToggleSnooze: () => void }) {
  const locked = ctx.busyKey !== null;
  const snoozeId = `snooze-${item.id.replace(":", "-")}`;
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-1.5 sm:pt-0.5">
      {item.actions.includes("complete") ? (
        <Button
          size="sm"
          variant="secondary"
          data-action-primary=""
          aria-label={actionLabel(item, "complete")}
          busy={ctx.busyKey === `${item.id}:complete`}
          busyLabel="Ukládám…"
          disabled={locked}
          onClick={() => void ctx.run(item, "complete")}
        >
          <span aria-hidden="true">✓</span> {moduleAction(item, "complete")?.button ?? "Hotovo"}
        </Button>
      ) : null}
      {/* MRK-21: další akce modulů z manifestu (např. „Přeskočit" u návyku) – jedna obecná cesta */}
      {item.actions
        .filter((a) => !CORE_ACTIONS.includes(a))
        .map((a) => {
          const declared = moduleAction(item, a);
          return declared ? (
            <Button
              key={a}
              size="sm"
              variant={declared.primary ? "secondary" : "ghost"}
              data-action-primary={declared.primary ? "" : undefined}
              aria-label={actionLabel(item, a)}
              busy={ctx.busyKey === `${item.id}:${a}`}
              busyLabel="Ukládám…"
              disabled={locked}
              onClick={() => void ctx.run(item, a)}
            >
              {declared.button}
            </Button>
          ) : null;
        })}
      {item.actions.includes("snooze") && ctx.snoozeOptions.length ? (
        <Button
          size="sm"
          variant="ghost"
          aria-label={actionLabel(item, "snooze")}
          aria-expanded={snoozeOpen}
          aria-controls={snoozeId}
          data-snooze-toggle={item.id}
          busy={ctx.busyKey === `${item.id}:snooze`}
          busyLabel="Odkládám…"
          disabled={locked}
          onClick={onToggleSnooze}
        >
          Odložit
        </Button>
      ) : null}
      {item.actions.includes("record_result") && item.href ? (
        <Link
          href={item.href}
          data-action-primary=""
          aria-label={actionLabel(item, "record_result")}
          className="inline-flex min-h-9 items-center rounded-[var(--radius-control)] px-3 text-sm text-accent-strong hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 pointer-coarse:min-h-11"
        >
          Zapsat výsledek →
        </Link>
      ) : null}
    </div>
  );
}

/** Pevné volby odložení (spočítané serverem v pražském čase). Esc zavře a vrátí fokus na „Odložit". */
function SnoozeOptions({ item, ctx, onClose }: { item: TodayItem; ctx: ActionsCtx; onClose: () => void }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, []);
  const back = () => {
    onClose();
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-snooze-toggle="${CSS.escape(item.id)}"]`)?.focus());
  };
  return (
    <div
      ref={ref}
      id={`snooze-${item.id.replace(":", "-")}`}
      role="group"
      aria-label={`Odložit „${item.title}“ – na kdy?`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          back();
        }
      }}
      className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line-subtle pt-2"
    >
      <span className="mr-1 text-xs text-ink-muted">Odložit na:</span>
      {ctx.snoozeOptions.map((o) => (
        <Button
          key={o.id}
          size="sm"
          variant="secondary"
          aria-label={`${o.label}: ${item.title}`}
          disabled={ctx.busyKey !== null}
          onClick={() => {
            onClose();
            void ctx.run(item, "snooze", o);
          }}
        >
          {o.label}
        </Button>
      ))}
      <Button size="sm" variant="ghost" onClick={back}>
        Zrušit
      </Button>
    </div>
  );
}

/** Výsledek poslední akce: oznámení čtečce, u dokončení úkolu „Vrátit" (existující undo). */
function ActionNotice({ notice, busy, onDismiss }: { notice: TodayNotice | null; busy: boolean; onDismiss: () => void }) {
  return (
    <div role="status" aria-live="polite" data-today-notice="" tabIndex={-1} className="focus:outline-none">
      {notice ? (
        <div
          className={cx(
            "flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border px-4 py-2.5 text-sm",
            notice.tone === "success" ? "border-success/35 bg-success/10 text-ink" : notice.tone === "warning" ? "border-warning/40 bg-warning/10 text-ink" : "border-danger/40 bg-danger/10 text-danger",
          )}
        >
          <span aria-hidden="true">{notice.tone === "success" ? "✓" : "!"}</span>
          <span className="min-w-0 flex-1">{notice.message}</span>
          {notice.undo ? (
            <Button size="sm" variant="secondary" onClick={notice.undo} busy={busy} busyLabel="Vracím…">
              Vrátit
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onDismiss} aria-label="Zavřít oznámení">
            ×
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function Timeline({ data }: { data: TodayPayload }) {
  const { timed, untimed, done } = groupTimeline(data.timeline);
  const nextId = data.summary.next?.id ?? null;
  if (!timed.length && !untimed.length && !done.length) {
    return <EmptyState compact>Na dnešek nemáš žádný termín ani připomínku.</EmptyState>;
  }
  return (
    <div className="space-y-4">
      {timed.length ? <ItemList label="Dnes s časem" items={timed} nextId={nextId} /> : null}
      {untimed.length ? (
        <div>
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">Během dne</h3>
          <ItemList label="Během dne" items={untimed} />
        </div>
      ) : null}
      {done.length ? (
        <details className="group">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-[var(--radius-control)] text-sm text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70">
            <span aria-hidden="true" className="transition-transform group-open:rotate-90">
              ›
            </span>
            Hotovo ({itemsLabel(done.length)})
          </summary>
          <div className="mt-2">
            <ItemList label="Hotovo" items={done} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function Upcoming({ data, compact }: { data: TodayPayload; compact?: boolean }) {
  if (data.errors.upcoming) return <Section id="upcoming" title="Potom" icon="calendar" error={data.errors.upcoming}>{null}</Section>;
  if (!data.upcoming.length) return null;
  return (
    <Card aria-labelledby="today-upcoming-title" data-section="upcoming" className={compact ? "text-left" : undefined}>
      <CardHeader title={<span id="today-upcoming-title">Potom</span>} icon="calendar" description="Nejbližší termíny v dalších dnech." />
      <ul aria-label="Potom" className="space-y-2">
        {data.upcoming.map((it) => (
          <li key={it.id} data-item={it.id}>
            <Link
              href={it.href ?? "#"}
              className="flex min-h-11 items-center gap-3 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-3 py-2 text-sm transition-colors hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              <span className="w-20 shrink-0 whitespace-nowrap font-mono text-xs tabular-nums text-ink-2">{shortDate(it.date)}</span>
              <span className="min-w-0 flex-1 truncate text-ink">
                <span className="sr-only">{TYPE_LABELS[it.type] ?? "Položka"}: </span>
                {it.title}
              </span>
              {it.time ? <span className="shrink-0 font-mono text-xs tabular-nums text-ink-muted">{it.time}</span> : null}
              <AreaBadge area={it.area} className="hidden sm:inline-flex" />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function EmptyDay({ data, addButton }: { data: TodayPayload; addButton: React.ReactNode }) {
  return (
    <>
      <EmptyState
        action={
          <div className="flex flex-wrap justify-center gap-2">
            {addButton}
            <TextLink href="/planner">Plánovač →</TextLink>
          </div>
        }
      >
        <span data-testid="today-empty">Dnes nemáš nic naplánovaného.</span>
      </EmptyState>
      <Upcoming data={data} compact />
    </>
  );
}
