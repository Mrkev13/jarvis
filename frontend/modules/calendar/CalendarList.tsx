import { EmptyState, EntityList, EntityRow, StatusBadge } from '@/components/ui';
import { eventState, eventTime, type CalendarEvent } from './lib';

export function CalendarList({ events, sources, empty }: {
  events: CalendarEvent[]; sources: Record<number, string>; empty: string;
}) {
  if (!events.length) return <EmptyState>{empty}</EmptyState>;
  return <EntityList label="Události kalendáře">
    {events.map(event => <EntityRow key={event.id} searchTarget={`event-${event.id}`}
      title={event.title} muted={event.status === 'cancelled'}
      badges={<>
        <StatusBadge tone={event.status === 'cancelled' ? 'warning' : 'info'}>{eventState(event)}</StatusBadge>
        <StatusBadge>{sources[event.source_id] ?? 'ICS'}</StatusBadge>
        {event.rrule ? <StatusBadge>Opakování – první výskyt</StatusBadge> : null}
      </>}
      meta={[eventTime(event), event.location].filter(Boolean).join(' · ')} />)}
  </EntityList>;
}
