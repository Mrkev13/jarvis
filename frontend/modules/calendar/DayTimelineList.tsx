import { EmptyState, ErrorState, LoadingState, StatusBadge } from '@/components/ui';
import { dayRows, formatDuration, timelineTime, type DayTimelinePayload, type TimelineItem } from './lib';
import { nowLineIndex, pragueNow } from '@/lib/hudModules';

function ItemRow({ item, moduleLabel }: { item: TimelineItem; moduleLabel: string }) {
  const done = item.status === 'done' || item.status === 'past';
  return <li data-timeline-item={item.kind} className={`flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm ${done ? 'opacity-70' : ''}`}>
    {item.local_start ? <span className="w-24 shrink-0 tabular-nums text-ink-muted">{timelineTime(item)}</span> : null}
    {item.href ? <a href={item.href} className="font-medium hover:underline">{item.title}</a> : <span className="font-medium">{item.title}</span>}
    <StatusBadge>{moduleLabel}</StatusBadge>
    {item.subtitle ? <span className="text-ink-muted">{item.subtitle}</span> : null}
  </li>;
}

/** MRK-13: day view – all-day/deadlines on top, then timed items with free gaps in between (pure view). */
export function DayTimelineList({ data, loading, error, onRetry, moduleLabels, nowMs = null }: {
  data: DayTimelinePayload | null; loading: boolean; error: string | null; onRetry?: () => void;
  moduleLabels: Record<string, string>;
  /** MRK-134: aktuální čas (ms) pro rysku „teď"; null = bez rysky */
  nowMs?: number | null;
}) {
  if (loading) return <LoadingState lines={3} />;
  if (error) return <ErrorState message="Den se nepodařilo načíst." onRetry={onRetry} />;
  if (!data) return null;
  const label = (item: TimelineItem) => moduleLabels[item.module_id ?? ''] ?? 'Obecné';
  const rows = dayRows(data);
  // MRK-134: dnešní den má rysku „teď" jako skener (jen když je zobrazený den dnešek v pražském čase)
  const now = nowMs === null ? null : pragueNow(new Date(nowMs));
  const nowAt = now && nowMs !== null && data.date === now.date ? nowLineIndex(rows.map(r => Date.parse(r.type === 'item' ? r.item.starts_at ?? '' : r.block.starts_at)), nowMs) : -1;
  const nowLine = <li key="now-line" data-now-line="" aria-label={`Teď ${now?.time ?? ''}`} className="now-line"><span className="now-line-time">{now?.time}</span></li>;
  if (!data.all_day_items.length && !rows.length) return <EmptyState>Na tento den nic nemáš.</EmptyState>;
  return <div className="space-y-3">
    {data.all_day_items.length ? <section aria-label="Celý den a termíny">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Celý den a termíny</h3>
      <ul className="space-y-1">{data.all_day_items.map(item => <ItemRow key={item.id} item={item} moduleLabel={label(item)} />)}</ul>
    </section> : null}
    {rows.length ? <section aria-label="Během dne">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Během dne</h3>
      <ul className="space-y-1">{rows.flatMap((row, i) => {
        const el = row.type === 'item'
          ? <ItemRow key={row.key} item={row.item} moduleLabel={label(row.item)} />
          : <li key={row.key} data-free-gap className="flex flex-wrap gap-x-2 rounded border border-dashed border-line px-2 py-0.5 text-sm text-ink-muted">
              <span className="w-24 shrink-0 tabular-nums">{row.block.local_start}–{row.block.local_end}</span>
              <span>Volno · {formatDuration(row.block.duration_minutes)}</span>
            </li>;
        return i === nowAt ? [nowLine, el] : [el];
      })}{nowAt === rows.length ? nowLine : null}</ul>
    </section> : null}
    {data.truncated ? <p className="text-xs text-ink-muted">Den má příliš mnoho položek – přehled nemusí být úplný.</p> : null}
  </div>;
}
