'use client';

import { useState } from 'react';
import { Card, CardHeader, fieldClass } from '@/components/ui';
import { useApiResource } from '@/hooks/useApiResource';
import { MODULES } from '@/lib/modules';
import { DayTimelineList } from './DayTimelineList';
import { timelinePath, type DayTimelinePayload } from './lib';

const MODULE_LABELS = Object.fromEntries(MODULES.map(m => [m.id, m.label]));

/** MRK-13: "Můj den" – one deterministic view of a day across modules (read-only, no planning). */
export function DayTimelineCard({ today }: { today: string }) {
  const [day, setDay] = useState(today);
  const resource = useApiResource<DayTimelinePayload>(timelinePath(day));
  return <Card>
    <CardHeader title="Můj den" />
    <label className="mb-3 flex items-center gap-2 text-sm">Den
      <span className="block w-40"><input type="date" value={day} onChange={event => setDay(event.target.value || today)} className={fieldClass} /></span>
    </label>
    <DayTimelineList data={resource.data ?? null} loading={resource.loading} error={resource.error}
      onRetry={() => void resource.reload()} moduleLabels={MODULE_LABELS} />
  </Card>;
}
