import { EmptyState, EntityList, EntityRow, StatusBadge } from '@/components/ui';
import { eventState, eventTime, isActive, type CalendarEvent } from './lib';

export function CalendarList({ events, sources, empty }: {
  events: CalendarEvent[]; sources: Record<number, string>; empty: string;
}) {
  if (!events.length) return <EmptyState>{empty}</EmptyState>;
  return <EntityList label="Události kalendáře">
    {events.map(event => <EntityRow key={event.key ?? event.id} searchTarget={`event-${event.id}`}
      title={event.title} muted={!isActive(event)}
      badges={<>
        <StatusBadge tone={isActive(event) ? 'info' : 'warning'}>{eventState(event)}</StatusBadge>
        <StatusBadge>{sources[event.source_id] ?? 'ICS'}</StatusBadge>
        {event.recurring ? <StatusBadge>Opakuje se</StatusBadge> : null}
      </>}
      meta={[eventTime(event), event.location].filter(Boolean).join(' · ')} />)}
  </EntityList>;
}
