'use client';

import { useState } from 'react';
import { Button, EmptyState, ErrorState, LoadingState, StatusBadge, fieldClass } from '@/components/ui';
import { useApiResource } from '@/hooks/useApiResource';
import { MAX_FIND_CHARS, contentPath, contentSummary, locationLabel, type MaterialContent } from './materialsLib';

/** MRK-44: omezený náhled textu jednoho materiálu a hledání v něm (žádný prohlížeč dokumentů). */
export function MaterialReader({ materialId, initialQuery }: { materialId: number; initialQuery?: string | null }) {
  const [draft, setDraft] = useState(initialQuery ?? '');
  const [query, setQuery] = useState((initialQuery ?? '').trim());
  const content = useApiResource<MaterialContent>(contentPath(materialId, query));
  const data = content.data;
  return <div className="mt-4 space-y-3" data-testid="material-reader">
    <form role="search" aria-label="Hledat v materiálu" className="flex flex-wrap items-end gap-2"
      onSubmit={event => { event.preventDefault(); setQuery(draft.trim()); }}>
      <label className="min-w-0 flex-1 space-y-1">
        <span className="block text-xs font-medium text-ink-2">Najít v materiálu</span>
        <input type="search" value={draft} maxLength={MAX_FIND_CHARS} placeholder="např. rekurze"
          onChange={event => setDraft(event.target.value)} className={`${fieldClass} pointer-coarse:min-h-11`} />
      </label>
      <Button type="submit" variant="secondary" size="sm">Hledat</Button>
      {query ? <Button type="button" variant="ghost" size="sm" onClick={() => { setDraft(''); setQuery(''); }}>Začátek</Button> : null}
    </form>
    {content.loading ? <LoadingState lines={3} label="Načítám text…" /> : null}
    {content.error ? <ErrorState message="Text materiálu se nepodařilo načíst." onRetry={() => void content.reload()} /> : null}
    {data ? <>
      <p role="status" className="text-xs text-ink-muted">{contentSummary(data)}
        {data.extraction_truncated ? ' Text dokumentu je zkrácený na limit extrakce.' : ''}</p>
      {data.text_status === 'available' && data.chunks.length
        ? <ol className="space-y-2" aria-label="Části textu">
            {data.chunks.map(chunk => <li key={chunk.index} className="rounded-card border border-line bg-surface p-3 text-sm text-ink-2">
              <div className="mb-1 flex flex-wrap gap-1.5">
                {locationLabel(chunk.location) ? <StatusBadge tone="info">{locationLabel(chunk.location)}</StatusBadge> : null}
                {chunk.matched_terms?.length ? <StatusBadge>shoda: {chunk.matched_terms.join(', ')}</StatusBadge> : null}
              </div>
              <p className="whitespace-pre-line break-words">{chunk.text}</p>
            </li>)}
          </ol>
        : data.text_status === 'available' ? <EmptyState>Zkus jiné slovo.</EmptyState> : null}
      {!query && data.outline?.length ? <details className="text-sm text-ink-2">
        <summary className="cursor-pointer text-ink-muted">Obsah ({data.outline.length})</summary>
        <ul className="mt-2 space-y-1">{data.outline.map(o => <li key={`${o.kind}-${o.number}`}>
          <span className="text-ink-muted">{o.kind === 'slide' ? 'Snímek' : 'Strana'} {o.number}:</span> {o.label}
        </li>)}</ul>
      </details> : null}
    </> : null}
  </div>;
}
