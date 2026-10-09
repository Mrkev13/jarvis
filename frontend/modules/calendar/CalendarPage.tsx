'use client';

import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button, Card, CardHeader, ContentContainer, EmptyState, ErrorState, LoadingState, PageHeader } from '@/components/ui';
import { useApiResource } from '@/hooks/useApiResource';
import { apiJson, jsonBody } from '@/lib/api';
import { CalendarList } from './CalendarList';
import { groupEvents, type CalendarPayload } from './lib';

export default function CalendarPage() {
  const selected = useSearchParams().get('event');
  const eventId = selected && /^[1-9][0-9]*$/.test(selected) ? selected : null;
  const calendar = useApiResource<CalendarPayload>(`/calendar${eventId ? `?event=${eventId}` : ''}`);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  async function sync() {
    setSyncing(true); setSyncError(null); setNotice(null);
    try {
      const result = await apiJson<{ created: number; updated: number; cancelled: number; errors: number }>('/calendar/sync', jsonBody('POST', {}));
      setNotice(`Přidáno ${result.created}, změněno ${result.updated}, zrušeno ${result.cancelled}.${result.errors ? ` ${result.errors} položek se nepodařilo načíst.` : ''}`);
      await calendar.reload();
    } catch {
      setSyncError('Synchronizace se nepovedla. Uložené události zůstaly zachované.');
    } finally { setSyncing(false); }
  }
  const data = calendar.data;
  const groups = groupEvents(data?.events ?? [], data?.today ?? '');
  const sources = Object.fromEntries((data?.sources ?? []).map(source => [source.id, source.name]));
  return <ContentContainer>
    <PageHeader title="Kalendář" subtitle="Události dnes a v příštích týdnech."
      actions={<Button variant="secondary" busy={syncing} disabled={!data?.moodle_configured} onClick={() => void sync()}>Synchronizovat</Button>} />
    {notice ? <p role="status" className="text-sm text-ink-muted">{notice}</p> : null}
    {syncError ? <ErrorState message={syncError} /> : null}
    {calendar.loading ? <LoadingState lines={4} /> : null}
    {calendar.error ? <ErrorState message="Kalendář se nepodařilo načíst." onRetry={() => void calendar.reload()} /> : null}
    {data ? <>
      {!data.moodle_configured ? <EmptyState>Zdroj ještě není připojený. Uložené události můžeš dál prohlížet.</EmptyState> : null}
      <Card><CardHeader title="Dnes" icon="calendar" /><CalendarList events={groups.today} sources={sources} empty="Dnes nemáš žádné události." /></Card>
      <Card><CardHeader title="Nadcházející" /><CalendarList events={groups.upcoming} sources={sources} empty="Žádné nadcházející události." /></Card>
      {groups.cancelled.length ? <Card><CardHeader title="Zrušené" /><CalendarList events={groups.cancelled} sources={sources} empty="" /></Card> : null}
      {groups.past.length ? <Card><CardHeader title="Nedávné a vybrané události" /><CalendarList events={groups.past} sources={sources} empty="" /></Card> : null}
    </> : null}
  </ContentContainer>;
}
