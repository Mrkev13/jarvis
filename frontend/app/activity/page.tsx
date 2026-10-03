"use client";

import { useMemo, useState } from "react";
import {
  AreaBadge,
  Button,
  ContentContainer,
  EmptyState,
  ErrorState,
  fieldClass,
  FilterBar,
  FilterChips,
  FilterSelect,
  HudLabel,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import {
  ACTIVITY_ACTIONS,
  ACTIVITY_AREAS,
  activityActionLabel,
  activityQuery,
  dayHeading,
  EMPTY_ACTIVITY_FILTERS,
  groupByDay,
  type ActivityFilters,
} from "@/lib/activity";
import { apiJson, errorMessage } from "@/lib/api";
import { areaMeta } from "@/lib/areas";
import { countActiveFilters, toggleInList } from "@/lib/filters";
import { formatNumber, formatTime, plural, pragueDayKey } from "@/lib/format";
import { cx, type Tone } from "@/lib/ui";

type ActivityItem = {
  id: number;
  timestamp: string;
  area: string;
  action_type: string;
  entity_type: string | null;
  entity_id: number | null;
  summary: string;
  user_context: string | null;
};

type ActivityResponse = { items: ActivityItem[]; total: number; limit: number; offset: number };
type ActivityDetail = ActivityItem & { delta: unknown };

const PAGE_LIMIT = 20;
const AREA_OPTIONS = ACTIVITY_AREAS.map((a) => ({ value: a, label: areaMeta(a).label }));
const ACTION_OPTIONS = [{ value: "all", label: "Všechny" }, ...ACTIVITY_ACTIONS.map((a) => ({ value: a, label: activityActionLabel(a) }))];

function actionTone(actionType: string): Tone {
  if (actionType === "error") return "danger";
  if (actionType === "delete" || actionType === "reject") return "warning";
  return "neutral";
}

/** Změna z auditu: {pole: {old, new}} jako tabulka, jinak JSON. */
function DeltaView({ delta }: { delta: unknown }) {
  if (delta == null) return <p className="text-xs text-ink-muted">Záznam neobsahuje podrobnosti o změně.</p>;
  const entries = typeof delta === "object" && !Array.isArray(delta) ? Object.entries(delta as Record<string, unknown>) : [];
  const isDiff = entries.length > 0 && entries.every(([, v]) => v && typeof v === "object" && ("old" in v || "new" in v));
  if (!isDiff) {
    return (
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-control)] bg-app p-3 font-mono text-xs text-ink-2">
        {JSON.stringify(delta, null, 2)}
      </pre>
    );
  }
  const show = (v: unknown) => (v == null || v === "" ? "–" : typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
      {entries.map(([field, v]) => {
        const { old, new: next } = v as { old?: unknown; new?: unknown };
        return (
          <div key={field} className="contents">
            <dt className="font-mono text-ink-muted">{field}</dt>
            <dd className="min-w-0 break-words text-ink-2">
              {old !== undefined && show(old) !== show(next) ? (
                <>
                  <span className="text-ink-muted line-through decoration-ink-faint">{show(old)}</span>
                  <span aria-hidden="true" className="mx-1.5 text-ink-faint">→</span>
                  <span className="sr-only"> změněno na </span>
                </>
              ) : null}
              <span className="text-ink">{show(next)}</span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<{ status: "loading" | "ok" | "error"; data?: ActivityDetail; error?: string } | null>(null);
  const detailId = `activity-detail-${item.id}`;

  async function loadDetail() {
    setDetail({ status: "loading" });
    try {
      setDetail({ status: "ok", data: await apiJson<ActivityDetail>(`/activity/${item.id}`) });
    } catch (err) {
      setDetail({ status: "error", error: errorMessage(err, "Podrobnosti se nepodařilo načíst.") });
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && (!detail || detail.status === "error")) void loadDetail();
  }

  return (
    <li className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2">
      <div className="flex items-start gap-3 p-3">
        <time dateTime={item.timestamp} className="w-11 shrink-0 pt-0.5 font-mono text-xs tabular-nums text-ink-muted">
          {formatTime(item.timestamp)}
        </time>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <AreaBadge area={item.area} />
            <StatusBadge tone={actionTone(item.action_type)}>{activityActionLabel(item.action_type)}</StatusBadge>
          </div>
          <p className="break-words text-sm text-ink">{item.summary}</p>
          {item.entity_type || item.user_context ? (
            <p className="mt-0.5 break-words font-mono text-[11px] text-ink-faint">
              {item.entity_type ? `${item.entity_type}${item.entity_id != null ? ` #${item.entity_id}` : ""}` : null}
              {item.entity_type && item.user_context ? " · " : null}
              {item.user_context ? `zdroj: ${item.user_context === "manual" ? "ručně" : item.user_context}` : null}
            </p>
          ) : null}
        </div>
        <Button size="sm" variant="ghost" aria-expanded={open} aria-controls={detailId} onClick={toggle} className="shrink-0">
          {open ? "Skrýt" : "Detail"}
        </Button>
      </div>
      {open ? (
        <div id={detailId} className="border-t border-line-subtle px-3 py-3" aria-busy={detail?.status === "loading"}>
          {!detail || detail.status === "loading" ? (
            <LoadingState lines={1} label="Načítám podrobnosti…" />
          ) : detail.status === "error" ? (
            <ErrorState message={detail.error} onRetry={() => void loadDetail()} />
          ) : (
            <DeltaView delta={detail.data?.delta} />
          )}
        </div>
      ) : null}
    </li>
  );
}

export default function ActivityPage() {
  const [filters, setFilters] = useState<ActivityFilters>(EMPTY_ACTIVITY_FILTERS);
  const query = activityQuery(filters, PAGE_LIMIT, 0);
  // Psaní do hledání a přepínání filtrů se načítá s malým zpožděním (žádný dotaz na každý znak).
  const first = useApiResource<ActivityResponse>(`/activity?${query}`, { debounceMs: 300 });
  // Další stránky („Načíst další") patří jen k aktuálnímu dotazu.
  const [more, setMore] = useState<{ query: string; items: ActivityItem[]; total: number } | null>(null);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  const extra = more && more.query === query ? more : null;
  const items = useMemo(() => [...(first.data?.items ?? []), ...(extra?.items ?? [])], [first.data, extra]);
  const total = extra?.total ?? first.data?.total ?? 0;
  const hasMore = items.length < total;
  const groups = useMemo(() => groupByDay(items), [items]);
  const todayKey = pragueDayKey(new Date());

  const update = (patch: Partial<ActivityFilters>) => {
    setMoreError(null);
    setFilters((f) => ({ ...f, ...patch }));
  };
  const active = countActiveFilters({ ...filters });

  async function loadMore() {
    if (moreBusy || !hasMore) return;
    setMoreBusy(true);
    setMoreError(null);
    try {
      const data = await apiJson<ActivityResponse>(`/activity?${activityQuery(filters, PAGE_LIMIT, items.length)}`);
      setMore({ query, items: [...(extra?.items ?? []), ...data.items], total: data.total });
    } catch (err) {
      setMoreError(errorMessage(err, "Nepodařilo se načíst další záznamy."));
    } finally {
      setMoreBusy(false);
    }
  }

  return (
    <ContentContainer width="narrow">
      <PageHeader
        eyebrow={<HudLabel>Systém · audit</HudLabel>}
        title="Aktivita"
        subtitle="Časová osa změn napříč moduly – co se kdy vytvořilo, upravilo nebo smazalo."
      />

      <FilterBar
        label="Filtry aktivity"
        search={{ value: filters.q, onChange: (q) => update({ q }), placeholder: "Hledat v popisu…", label: "Hledat v popisu" }}
        activeCount={active}
        onReset={() => update(EMPTY_ACTIVITY_FILTERS)}
        result={
          first.data ? `Zobrazeno ${formatNumber(items.length)} z ${formatNumber(total)} ${plural(total, "záznamu", "záznamů", "záznamů")}` : null
        }
      >
        <FilterChips
          label="Oblast"
          options={AREA_OPTIONS}
          selected={filters.areas}
          onToggle={(a) => update({ areas: toggleInList(filters.areas, a, ACTIVITY_AREAS) })}
        />
        <FilterSelect label="Typ akce" value={filters.actionType} onChange={(actionType) => update({ actionType })} options={ACTION_OPTIONS} />
        <div className="min-w-[9rem] flex-1 space-y-1 sm:flex-none">
          <label htmlFor="activity-from" className="block text-xs font-medium text-ink-2">
            Od
          </label>
          <input id="activity-from" type="date" value={filters.fromDate} onChange={(e) => update({ fromDate: e.target.value })} className={fieldClass} />
        </div>
        <div className="min-w-[9rem] flex-1 space-y-1 sm:flex-none">
          <label htmlFor="activity-to" className="block text-xs font-medium text-ink-2">
            Do
          </label>
          <input id="activity-to" type="date" value={filters.toDate} onChange={(e) => update({ toDate: e.target.value })} className={fieldClass} />
        </div>
      </FilterBar>

      <section aria-label="Časová osa" aria-busy={first.loading || first.refreshing} className={cx("space-y-6", first.refreshing && "opacity-70 transition-opacity")}>
        {first.error && !first.data ? (
          <ErrorState message={first.error} onRetry={() => void first.reload()} retrying={first.refreshing} />
        ) : first.loading || !first.data ? (
          <LoadingState lines={5} label="Načítám aktivitu…" />
        ) : groups.length === 0 ? (
          <EmptyState
            action={
              active > 0 ? (
                <Button size="sm" onClick={() => update(EMPTY_ACTIVITY_FILTERS)}>
                  Zrušit filtry
                </Button>
              ) : undefined
            }
          >
            {active > 0 ? "Filtrům neodpovídá žádný záznam." : "Zatím žádné záznamy aktivity."}
          </EmptyState>
        ) : (
          <>
            {first.error ? <ErrorState message={first.error} onRetry={() => void first.reload()} /> : null}
            {groups.map(([day, dayItems]) => (
              <section key={day} aria-labelledby={`activity-day-${day}`} className="space-y-2">
                <div className="flex items-center gap-3">
                  <h2 id={`activity-day-${day}`} className="text-sm font-semibold text-ink-2">
                    {dayHeading(day, todayKey)}
                  </h2>
                  <span aria-hidden="true" className="h-px flex-1 bg-line-subtle" />
                  <span className="text-xs tabular-nums text-ink-muted">{dayItems.length}</span>
                </div>
                <ul className="space-y-2">
                  {dayItems.map((item) => (
                    <ActivityRow key={item.id} item={item} />
                  ))}
                </ul>
              </section>
            ))}
            {moreError ? <ErrorState message={moreError} onRetry={() => void loadMore()} /> : null}
            <div className="flex justify-center">
              {hasMore ? (
                <Button onClick={() => void loadMore()} busy={moreBusy} busyLabel="Načítám…">
                  Načíst další
                </Button>
              ) : (
                <p className="text-xs text-ink-muted">Vše načteno.</p>
              )}
            </div>
          </>
        )}
      </section>
    </ContentContainer>
  );
}
