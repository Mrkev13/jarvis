"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AreaBadge,
  Button,
  ContentContainer,
  EmptyState,
  ErrorState,
  FilterBar,
  FilterChips,
  FilterSelect,
  HudLabel,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { useDomainEvents } from "@/hooks/useDomainEvents";
import { dayHeading } from "@/lib/activity";
import {
  CHANGE_PERIODS,
  changeKindLabel,
  changeKindTone,
  changesQuery,
  createRefetchScheduler,
  DEFAULT_PERIOD,
  groupChangesByDay,
  keepKnownFilters,
  type ChangeItem,
  type ChangePeriod,
  type ChangesResponse,
} from "@/lib/changes";
import { formatNumber, formatTime, plural, pragueDayKey } from "@/lib/format";
import { toggleInList } from "@/lib/filters";
import { cx } from "@/lib/ui";

const PERIOD_OPTIONS = CHANGE_PERIODS.map((p) => ({ value: p.value, label: p.label }));

function ChangeRow({ item }: { item: ChangeItem }) {
  const body = (
    <>
      <time dateTime={item.occurred_at} className="w-11 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-ink-muted">
        {formatTime(item.occurred_at)}
      </time>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <AreaBadge area={item.module_id} />
          <StatusBadge tone={changeKindTone(item.kind)}>{changeKindLabel(item.kind)}</StatusBadge>
        </div>
        <p className="break-words text-sm text-ink">{item.title}</p>
        {item.summary ? <p className="mt-0.5 break-words text-xs text-ink-faint">{item.summary}</p> : null}
      </div>
    </>
  );
  return (
    <li data-testid="change-item" data-source={item.source} className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2">
      {item.href ? (
        <Link href={item.href} className="flex items-start gap-3 p-3 transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {body}
          <span aria-hidden="true" className="shrink-0 self-center text-ink-faint">
            →
          </span>
        </Link>
      ) : (
        <div className="flex items-start gap-3 p-3">{body}</div>
      )}
    </li>
  );
}

export default function ChangesPage() {
  const [period, setPeriod] = useState<ChangePeriod>(DEFAULT_PERIOD);
  // Začátek období se počítá od chvíle výběru (ne při každém vykreslení) – URL se sama nemění, žádný polling.
  const [anchor, setAnchor] = useState(() => Date.now());
  const [selected, setSelected] = useState<string[]>([]);
  const query = changesQuery(period, selected, anchor);
  const res = useApiResource<ChangesResponse>(`/changes?${query}`, { debounceMs: 150 });

  // MRK-19: nová doménová událost (i z jiného zařízení) nebo reset streamu → načíst znovu (sdružené).
  const reload = res.reload;
  const schedulerRef = useRef<ReturnType<typeof createRefetchScheduler> | null>(null);
  useEffect(() => {
    const scheduler = createRefetchScheduler(() => void reload());
    schedulerRef.current = scheduler;
    return () => {
      scheduler.cancel();
      schedulerRef.current = null;
    };
  }, [reload]);
  useDomainEvents({ onEvent: () => schedulerRef.current?.trigger(), onReset: () => schedulerRef.current?.trigger() });

  const filters = useMemo(() => res.data?.filters ?? [], [res.data]);
  // Vybraný modul, který v nových datech nemá žádnou změnu (jiné období, smazání), se z výběru odebere – jinak by
  // dotaz dál filtroval a stránka tvrdila „nic se nezměnilo" bez možnosti filtr zrušit. Filtry na `module`
  // nezávisí, takže stačí porovnat s poslední odpovědí (úprava stavu při vykreslení, ne v efektu).
  if (res.data && selected.some((id) => !filters.some((f) => f.id === id))) {
    setSelected(keepKnownFilters(selected, filters));
  }
  const chipOptions = useMemo(() => filters.map((f) => ({ value: f.id, label: `${f.label} (${formatNumber(f.count)})` })), [filters]);
  const visibleSelected = keepKnownFilters(selected, filters);
  const items = useMemo(() => res.data?.items ?? [], [res.data]);
  const groups = useMemo(() => groupChangesByDay(items), [items]);
  const todayKey = pragueDayKey(new Date());
  const total = res.data?.total ?? 0;
  const hidden = Math.max(0, total - items.length);
  const scanCapped = Boolean(res.data?.truncated) && hidden === 0;

  const choosePeriod = (value: string) => {
    setPeriod(value as ChangePeriod);
    setAnchor(Date.now());
  };
  const reset = () => {
    setSelected([]);
    choosePeriod(DEFAULT_PERIOD);
  };

  return (
    <ContentContainer width="narrow">
      <PageHeader
        eyebrow={<HudLabel>Přehled · změny</HudLabel>}
        title="Co se změnilo"
        subtitle="Co se za zvolené období stalo napříč moduly – splněné úkoly, nové záznamy i úpravy, bez technického šumu."
      />

      <FilterBar
        label="Filtry změn"
        activeCount={(period !== DEFAULT_PERIOD ? 1 : 0) + (visibleSelected.length ? 1 : 0)}
        onReset={reset}
        result={res.data ? `${formatNumber(total)} ${plural(total, "změna", "změny", "změn")}` : null}
      >
        <FilterSelect label="Období" value={period} onChange={choosePeriod} options={PERIOD_OPTIONS} />
        {chipOptions.length > 1 || visibleSelected.length ? (
          <FilterChips
            label="Modul"
            options={chipOptions}
            selected={visibleSelected}
            onToggle={(id) => setSelected(toggleInList(visibleSelected, id, filters.map((f) => f.id)))}
          />
        ) : null}
      </FilterBar>

      <section aria-label="Změny" aria-busy={res.loading || res.refreshing} className={cx("space-y-6", res.refreshing && "opacity-70 transition-opacity")}>
        {res.error && !res.data ? (
          <ErrorState message={res.error} onRetry={() => void res.reload()} retrying={res.refreshing} />
        ) : res.loading || !res.data ? (
          <LoadingState lines={5} label="Načítám změny…" />
        ) : groups.length === 0 ? (
          <EmptyState
            action={
              visibleSelected.length || period !== DEFAULT_PERIOD ? (
                <Button size="sm" onClick={reset}>
                  Zrušit filtry
                </Button>
              ) : undefined
            }
          >
            {visibleSelected.length ? "Ve vybraných modulech se za toto období nic nezměnilo." : "Za toto období se nic nezměnilo."}
          </EmptyState>
        ) : (
          <>
            {res.error ? <ErrorState message={res.error} onRetry={() => void res.reload()} /> : null}
            {groups.map(([day, dayItems]) => (
              <section key={day} aria-labelledby={`changes-day-${day}`} className="space-y-2">
                <div className="flex items-center gap-3">
                  <h2 id={`changes-day-${day}`} className="text-sm font-semibold text-ink-2">
                    {dayHeading(day, todayKey)}
                  </h2>
                  <span aria-hidden="true" className="h-px flex-1 bg-line-subtle" />
                  <span className="text-xs tabular-nums text-ink-muted">{dayItems.length}</span>
                </div>
                <ul className="space-y-2">
                  {dayItems.map((item) => (
                    <ChangeRow key={item.id} item={item} />
                  ))}
                </ul>
              </section>
            ))}
            {hidden > 0 ? (
              <p data-testid="changes-more" className="text-center text-xs text-ink-muted">
                … a {plural(hidden, "další", "další", "dalších")} {formatNumber(hidden)} {plural(hidden, "změna", "změny", "změn")} – zužte
                období nebo modul,{" "}
                nebo otevřete <Link href="/activity" className="underline">Aktivitu</Link>.
              </p>
            ) : null}
            {scanCapped ? (
              <p data-testid="changes-more" className="text-center text-xs text-ink-muted">
                Za toto období je změn příliš mnoho, starší se nenačetly – zužte období nebo otevřete{" "}
                <Link href="/activity" className="underline">Aktivitu</Link>.
              </p>
            ) : null}
          </>
        )}
      </section>
    </ContentContainer>
  );
}
