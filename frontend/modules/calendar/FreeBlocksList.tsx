import { EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { freeBlockLabel, type FreeBlock } from './lib';

/** MRK-32: list of free blocks (pure view; data and controls live in FreeBlocksCard). */
export function FreeBlocksList({ blocks, loading, error, truncated, onRetry }: {
  blocks: FreeBlock[] | null; loading: boolean; error: string | null; truncated?: boolean; onRetry?: () => void;
}) {
  if (loading) return <LoadingState lines={2} />;
  if (error) return <ErrorState message="Volné bloky se nepodařilo načíst." onRetry={onRetry} />;
  if (!blocks || !blocks.length) return <EmptyState>V tento den mezi 7:00 a 22:00 nemáš žádný volný blok této délky.</EmptyState>;
  return <>
    <ul aria-label="Volné bloky" className="space-y-1">
      {blocks.map(block => <li key={block.starts_at} data-free-block className="text-sm tabular-nums">{freeBlockLabel(block)}</li>)}
    </ul>
    {truncated ? <p className="mt-2 text-xs text-ink-muted">Kalendář má v tomto období příliš mnoho událostí – výsledek nemusí být úplný.</p> : null}
  </>;
}
