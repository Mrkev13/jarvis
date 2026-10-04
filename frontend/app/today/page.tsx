"use client";

import Link from "next/link";
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
import {
  groupTimeline,
  isEmptyDay,
  itemsLabel,
  normalizeToday,
  SEVERITY_META,
  shortDate,
  STATUS_META,
  TYPE_LABELS,
  untilLabel,
  type TodayItem,
  type TodayPayload,
} from "@/lib/today";
import { cx } from "@/lib/ui";

/**
 * Režim Dnes (Roadmap 4G): „Co dnes potřebuje moji pozornost?" Jeden sloupec, jeden dotaz (GET /today),
 * deterministicky. Řídicí centrum = celý život napříč moduly; Dnes = jen to, na čem záleží dnes.
 */
export default function TodayPage() {
  const resource = useApiResource<unknown>("/today");
  const openQuickAdd = useOpenQuickAdd();
  const data: TodayPayload | null = resource.data ? normalizeToday(resource.data) : null;

  const addButton = (
    <Button variant="primary" onClick={openQuickAdd} aria-haspopup="dialog">
      <span aria-hidden="true">+</span> Přidat
    </Button>
  );

  return (
    <ContentContainer width="narrow">
      <PageHeader
        eyebrow={<HudLabel>Standa Hub · režim dnes</HudLabel>}
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

      {resource.loading ? (
        <LoadingState lines={4} label="Načítám dnešek…" />
      ) : resource.status === "error" || !data ? (
        <ErrorState message={resource.error ?? "Dnešek se nepodařilo načíst."} onRetry={() => void resource.reload()} retrying={resource.refreshing} />
      ) : isEmptyDay(data) ? (
        <EmptyDay data={data} addButton={addButton} />
      ) : (
        <>
          {resource.error ? <ErrorState message={`Obnovení selhalo: ${resource.error}`} /> : null}
          <DaySummary data={data} />
          <Section id="attention" title="Vyžaduje pozornost" icon="⚠️" error={data.errors.attention}>
            {data.attention.length ? (
              <ItemList label="Vyžaduje pozornost" items={data.attention} />
            ) : (
              <EmptyState compact>Nic po termínu ani k vyřízení.</EmptyState>
            )}
          </Section>
          <Section
            id="plan"
            title="Dnešní plán"
            icon="🎯"
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
          <Section id="timeline" title="Časová osa" icon="🕒" error={data.errors.timeline}>
            <Timeline data={data} />
          </Section>
          <Upcoming data={data} />
        </>
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
  icon: string;
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
    "block rounded-[var(--radius-control)] border px-3 py-2.5 md:px-4",
    isNext ? "border-accent/50 bg-accent/5" : item.status === "overdue" ? "border-danger/30 bg-danger/5" : "border-line-subtle bg-surface-2",
    quiet && "opacity-70",
  );
  return (
    <li data-item={item.id} data-status={item.status} aria-current={isNext ? "true" : undefined}>
      {item.href ? (
        <Link
          href={item.href}
          className={cx(box, "transition-colors hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70")}
        >
          {body}
        </Link>
      ) : (
        <div className={box}>{body}</div>
      )}
    </li>
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
  if (data.errors.upcoming) return <Section id="upcoming" title="Potom" icon="📅" error={data.errors.upcoming}>{null}</Section>;
  if (!data.upcoming.length) return null;
  return (
    <Card aria-labelledby="today-upcoming-title" data-section="upcoming" className={compact ? "text-left" : undefined}>
      <CardHeader title={<span id="today-upcoming-title">Potom</span>} icon="📅" description="Nejbližší termíny v dalších dnech." />
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
