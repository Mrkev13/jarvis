"use client";

import Link from "next/link";
import { Button, Card, CardHeader, EmptyState, ErrorState, LoadingState, Progress, StatusBadge, TextLink } from "@/components/ui";
import type { WidgetProps } from "@/components/dashboard/widgets";
import { useTodayActions } from "@/hooks/useTodayActions";
import { actionLabel, moduleAction, type TodayItem } from "@/lib/today";
import { cx } from "@/lib/ui";
import { habitDetail, habitResolution, habitTodayItems, percent, STATE_META, summaryFrom } from "./lib";

/**
 * Widget Řídicího centra `habits_today` (MRK-21, MRK-104): dnešní návyky se **Splnit** / **Přeskočit** jedním
 * klepnutím. Položky a povolené akce dává GET /today (stejně jako režim Dnes), akce běží přes `useTodayActions`
 * (endpoint z manifestu, audit + doménová událost na backendu, chyba = hláška u řádku se „Zkusit znovu").
 * Týdenní souhrn zůstává z GET /dashboard („habits").
 */
export function HabitsTodayWidget({ data, today, index }: WidgetProps) {
  const actions = useTodayActions(today.reload);
  const items = habitTodayItems(today.data);
  // přeskočené se nepočítají jako splněné (stejně jako týdenní souhrn)
  const done = items.filter((it) => habitResolution(it) === "done").length;
  const week = summaryFrom(data);
  const busy = actions.busyKey !== null;

  return (
    <Card index={index} aria-labelledby="habits-widget-title">
      <CardHeader title={<span id="habits-widget-title">Návyky</span>} icon="check" actions={<TextLink href="/habits">Návyky →</TextLink>} />
      {today.loading && !today.data ? (
        <LoadingState lines={2} label="Načítám návyky…" />
      ) : today.error && !today.data ? (
        <ErrorState message={`Návyky se nepodařilo načíst: ${today.error}`} onRetry={() => void today.reload()} retrying={today.refreshing} />
      ) : items.length ? (
        <div className="space-y-3 text-sm" data-testid="habits-widget">
          <div>
            <div className="mb-1 flex justify-between gap-2">
              <span className="text-ink-muted">Dnes splněno</span>
              <span className="font-semibold tabular-nums text-ink">
                {done} / {items.length}
              </span>
            </div>
            <Progress value={percent(done, items.length)} label={`Dnes splněno ${done} z ${items.length}`} size="sm" />
          </div>
          <div role="status" aria-live="polite" data-today-notice="" tabIndex={-1} className="focus:outline-none">
            {actions.notice ? (
              <p className={cx("text-xs", actions.notice.tone === "success" ? "text-success" : actions.notice.tone === "warning" ? "text-warning" : "text-danger")}>
                {actions.notice.message}
              </p>
            ) : null}
          </div>
          <ul className="space-y-2" aria-label="Dnešní návyky">
            {items.map((item) => (
              <HabitRow key={item.id} item={item} busyKey={actions.busyKey} locked={busy} error={actions.rowErrors[item.id]} onRun={(a) => void actions.run(item, a)} />
            ))}
          </ul>
          {week?.week_expected ? (
            <div className="flex justify-between gap-2 text-xs">
              <span className="text-ink-muted">Posledních 7 dní</span>
              <span className="tabular-nums text-ink-2">
                {week.week_done} / {week.week_expected} ({percent(week.week_done, week.week_expected)} %)
              </span>
            </div>
          ) : null}
        </div>
      ) : today.data ? (
        <EmptyState compact action={<TextLink href="/habits">Přidat návyk →</TextLink>}>
          Na dnešek žádný návyk.
        </EmptyState>
      ) : null}
    </Card>
  );
}

function HabitRow({
  item,
  busyKey,
  locked,
  error,
  onRun,
}: {
  item: TodayItem;
  busyKey: string | null;
  locked: boolean;
  error?: { message: string; action: string };
  onRun: (action: string) => void;
}) {
  const resolution = habitResolution(item);
  const open = resolution === null;
  const detail = habitDetail(item);
  const complete = moduleAction(item, "complete");
  const skip = moduleAction(item, "skip");
  return (
    <li
      data-item={item.id}
      data-actionable={open && item.actions.length ? "" : undefined}
      className={cx("rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-3 py-2", !open && "opacity-75")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          {item.href ? (
            <Link href={item.href} className="break-words font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              {item.title}
            </Link>
          ) : (
            <span className="break-words font-medium text-ink">{item.title}</span>
          )}
          {detail ? <p className="text-xs text-ink-muted">{detail}</p> : null}
        </div>
        {open ? (
          <div className="flex shrink-0 gap-1.5">
            {item.actions.includes("complete") && complete ? (
              <Button
                size="sm"
                variant="secondary"
                data-action-primary=""
                className="min-h-11 min-w-11"
                aria-label={actionLabel(item, "complete")}
                busy={busyKey === `${item.id}:complete`}
                busyLabel="Ukládám…"
                disabled={locked}
                onClick={() => onRun("complete")}
              >
                <span aria-hidden="true">✓</span> {complete.button}
              </Button>
            ) : null}
            {item.actions.includes("skip") && skip ? (
              <Button
                size="sm"
                variant="ghost"
                className="min-h-11"
                aria-label={actionLabel(item, "skip")}
                busy={busyKey === `${item.id}:skip`}
                busyLabel="Ukládám…"
                disabled={locked}
                onClick={() => onRun("skip")}
              >
                {skip.button}
              </Button>
            ) : null}
          </div>
        ) : (
          <StatusBadge tone={STATE_META[resolution].tone}>{STATE_META[resolution].label}</StatusBadge>
        )}
      </div>
      {error ? (
        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-danger" role="alert">
          {error.message}
          <Button size="sm" variant="ghost" disabled={locked} onClick={() => onRun(error.action)}>
            Zkusit znovu
          </Button>
        </p>
      ) : null}
    </li>
  );
}
