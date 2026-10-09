'use client';

import { useState } from 'react';
import { Card, CardHeader, fieldClass } from '@/components/ui';
import { useApiResource } from '@/hooks/useApiResource';
import { FreeBlocksList } from './FreeBlocksList';
import { FREE_BLOCK_MINUTES, freeBlocksPath, type FreeBlocksPayload } from './lib';

/** MRK-32: free time for one day (07:00–22:00) from active calendar occurrences. Read-only, no planning. */
export function FreeBlocksCard({ today }: { today: string }) {
  const [day, setDay] = useState(today);
  const [minMinutes, setMinMinutes] = useState(30);
  const resource = useApiResource<FreeBlocksPayload>(freeBlocksPath(day, minMinutes));
  return <Card>
    <CardHeader title="Volné bloky" />
    <div className="mb-3 flex flex-wrap gap-3 text-sm">
      <label className="flex items-center gap-2">Den
        <span className="block w-40"><input type="date" value={day} onChange={event => setDay(event.target.value || today)} className={fieldClass} /></span>
      </label>
      <label className="flex items-center gap-2">Alespoň
        <span className="block w-28"><select value={minMinutes} onChange={event => setMinMinutes(Number(event.target.value))} className={fieldClass}>
          {FREE_BLOCK_MINUTES.map(minutes => <option key={minutes} value={minutes}>{minutes} min</option>)}
        </select></span>
      </label>
    </div>
    <FreeBlocksList blocks={resource.data?.blocks ?? null} loading={resource.loading} error={resource.error}
      truncated={resource.data?.truncated} onRetry={() => void resource.reload()} />
  </Card>;
}
