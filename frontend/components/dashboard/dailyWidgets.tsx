"use client";

/**
 * MRK-78: jádro denní obrazovky v Řídicím centru – „Co hoří", „Můj den" a „Od včera". Data skládá backend
 * (GET /today, /dashboard, /timeline/day, /changes), výběr bez duplicit lib/controlCenter.ts. Plná verze dne
 * zůstává na /today (odkaz „Dnes →"), plný přehled změn na /changes.
 */
import Link from "next/link";
import { AreaBadge, Card, CardHeader, EmptyState, ErrorState, LoadingState, StatusBadge, TextLink } from "@/components/ui";
import { burningItems, dayItems, latestChanges, nextFreeBlock, type BurningItem } from "@/lib/controlCenter";
import { changeKindLabel, changeKindTone, type ChangeItem } from "@/lib/changes";
import { formatTime } from "@/lib/format";
import { STATUS_META, TYPE_LABELS, untilLabel, type TodayItem } from "@/lib/today";
import { cx } from "@/lib/ui";
import type { WidgetProps } from "./widgets";

const ROW = "rounded-[var(--radius-control)] border border-line-subtle bg-surface-2";
const ROW_LINK =
  "flex items-start gap-3 px-3 py-2.5 transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

function RowShell({
  href,
  children,
  tone,
  className,
}: {
  href: string | null;
  children: React.ReactNode;
  tone?: "danger" | "warning" | "neutral";
  className?: string;
}) {
  const border = tone === "danger" ? "border-l-2 border-l-danger" : tone === "warning" ? "border-l-2 border-l-warning" : null;
  return (
    <li className={cx(ROW, border, className)}>
      {href ? (
        <Link href={href} className={ROW_LINK}>
          {children}
          <span aria-hidden="true" className="shrink-0 self-center text-ink-faint">
            →
          </span>
        </Link>
      ) : (
        <div className="flex items-start gap-3 px-3 py-2.5">{children}</div>
      )}
    </li>
  );
}

const BURNING_TYPE: Record<string, string> = {
  calendar_event: "Moodle",
  notification: "Upozornění",
};
/** Na mobilu jen první tři – „Můj den" pod nimi se musí vejít na první obrazovku (zbytek na /today). */
const BURNING_MOBILE = 3;

function BurningRow({ item, mobileHidden }: { item: BurningItem; mobileHidden?: boolean }) {
  return (
    <RowShell href={item.href} tone={item.tone} className={mobileHidden ? "max-md:hidden" : undefined}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={item.tone === "neutral" ? "info" : item.tone}>{item.label}</StatusBadge>
          <span className="text-xs text-ink-muted">{BURNING_TYPE[item.type] ?? TYPE_LABELS[item.type] ?? "Položka"}</span>
        </div>
        <p className="mt-0.5 break-words text-sm font-medium text-ink">{item.title}</p>
        {item.meta ? <p className="truncate text-xs text-ink-muted">{item.meta}</p> : null}
      </div>
    </RowShell>
  );
}

export function BurningWidget({ today, data, loading, index }: WidgetProps) {
  const waiting = today.loading || loading;
  const items = burningItems(today.data, data?.upcoming);
  const partial = today.data?.errors.attention;
  return (
    <Card index={index} aria-labelledby="burning-title" tone={items.some((i) => i.tone === "danger") ? "danger" : "neutral"}>
      <CardHeader title={<span id="burning-title">Co hoří</span>} icon="alert" actions={<TextLink href="/today">Dnes →</TextLink>} />
      {waiting && !today.data ? (
        <LoadingState lines={3} label="Načítám, co hoří…" />
      ) : today.error && !today.data ? (
        <ErrorState message={`Co hoří se nepodařilo načíst: ${today.error}`} onRetry={() => void today.reload()} retrying={today.refreshing} />
      ) : (
        <>
          {partial ? <p className="mb-2 text-xs text-warning">{partial}</p> : null}
          {items.length ? (
            <>
              <ul className="space-y-2" aria-label="Co hoří">
                {items.map((item, i) => (
                  <BurningRow key={item.ref} item={item} mobileHidden={i >= BURNING_MOBILE} />
                ))}
              </ul>
              {items.length > BURNING_MOBILE ? (
                <p className="mt-2 md:hidden">
                  <TextLink href="/today">{`a ještě ${items.length - BURNING_MOBILE} v režimu Dnes →`}</TextLink>
                </p>
              ) : null}
            </>
          ) : (
            <EmptyState compact>Nic nehoří – nic po termínu a žádný test do 7 dní.</EmptyState>
          )}
        </>
      )}
    </Card>
  );
}

function DayRow({ item }: { item: TodayItem }) {
  const status = STATUS_META[item.status];
  return (
    <RowShell href={item.href}>
      <span className="w-11 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-ink-muted">{item.time ?? "dnes"}</span>
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm text-ink">{item.title}</p>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          {item.status !== "upcoming" ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
          {item.subtitle ? <span className="break-words">{item.subtitle}</span> : null}
        </div>
      </div>
    </RowShell>
  );
}

export function DayWidget({ today, dayTimeline, index, dayExcludeTypes }: WidgetProps) {
  const data = today.data;
  const next = data?.summary.next ?? null;
  const rest = dayItems(data, undefined, dayExcludeTypes).filter((it) => it.id !== next?.id);
  const free = dayTimeline.data?.free_blocks_from?.length ? nextFreeBlock(dayTimeline.data.free_blocks, data?.now_local ?? "") : null;
  const hasFreeSource = Boolean(dayTimeline.data?.free_blocks_from?.length);
  return (
    <Card index={index} aria-labelledby="day-title">
      <CardHeader
        title={<span id="day-title">Můj den</span>}
        icon="sun"
        description={data ? `${data.date_label} · zbývá ${data.summary.remaining}, hotovo ${data.summary.done}` : undefined}
        actions={<TextLink href="/today">Celý den →</TextLink>}
      />
      {today.loading && !data ? (
        <LoadingState lines={3} label="Načítám dnešní den…" />
      ) : today.error && !data ? (
        <ErrorState message={`Dnešní den se nepodařilo načíst: ${today.error}`} onRetry={() => void today.reload()} retrying={today.refreshing} />
      ) : data ? (
        <div className="space-y-3">
          {next ? (
            <Link
              href={next.href ?? "/today"}
              className="block rounded-[var(--radius-control)] border border-accent/40 bg-accent/10 p-3 transition-colors hover:bg-accent/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <span className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-accent-strong">
                <span className="font-semibold uppercase tracking-wide">Další</span>
                <span className="tabular-nums">
                  {next.time}
                  {untilLabel(next.minutes_until) ? ` · ${untilLabel(next.minutes_until)}` : ""}
                </span>
              </span>
              <span className="mt-1 block break-words text-base font-medium text-ink">{next.title}</span>
              {next.subtitle ? <span className="block break-words text-xs text-ink-muted">{next.subtitle}</span> : null}
            </Link>
          ) : (
            <p className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3 text-sm text-ink-muted">Dnes už nic s časem nečeká.</p>
          )}
          {data.errors.timeline ? <p className="text-xs text-warning">{data.errors.timeline}</p> : null}
          {rest.length ? (
            <ul className="space-y-2" aria-label="Dnes dál">
              {rest.map((it) => (
                <DayRow key={it.id} item={it} />
              ))}
            </ul>
          ) : null}
          {hasFreeSource ? (
            <p className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
              <StatusBadge tone="success">Volno</StatusBadge>
              {free ? (
                <span className="tabular-nums">
                  {free.from}–{free.local_end}
                </span>
              ) : (
                <span className="text-ink-muted">dnes už žádný volný blok</span>
              )}
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

function ChangeRow({ item }: { item: ChangeItem }) {
  return (
    <RowShell href={item.href}>
      <time dateTime={item.occurred_at} className="w-11 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-ink-muted">
        {formatTime(item.occurred_at)}
      </time>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <AreaBadge area={item.module_id} />
          <StatusBadge tone={changeKindTone(item.kind)}>{changeKindLabel(item.kind)}</StatusBadge>
        </div>
        <p className="mt-0.5 break-words text-sm text-ink">{item.title}</p>
      </div>
    </RowShell>
  );
}

export function ChangesWidget({ changes, index }: WidgetProps) {
  const items = latestChanges(changes.data?.items);
  const more = (changes.data?.total ?? 0) - items.length;
  return (
    <Card index={index} aria-labelledby="changes-title">
      <CardHeader title={<span id="changes-title">Od včera se změnilo</span>} icon="refresh" actions={<TextLink href="/changes">Vše →</TextLink>} />
      {changes.loading ? (
        <LoadingState lines={3} label="Načítám změny…" />
      ) : changes.error && !changes.data ? (
        <ErrorState message={`Změny se nepodařilo načíst: ${changes.error}`} onRetry={() => void changes.reload()} retrying={changes.refreshing} />
      ) : items.length ? (
        <>
          <ul className="space-y-2" aria-label="Změny za posledních 24 hodin">
            {items.map((item) => (
              <ChangeRow key={item.id} item={item} />
            ))}
          </ul>
          {more > 0 ? <p className="mt-2 text-xs text-ink-muted">a dalších {more} v přehledu změn</p> : null}
        </>
      ) : changes.data ? (
        <EmptyState compact>Za posledních 24 hodin se nic nezměnilo.</EmptyState>
      ) : null}
    </Card>
  );
}
