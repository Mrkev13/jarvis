"use client";

import { GameImage } from "@/components/games/GameImage";
import { Button, EntityRow, StatusBadge } from "@/components/ui";
import { useTankNameForTag } from "@/hooks/useGameAssets";
import { formatDate, formatNumber } from "@/lib/format";
import { masteryLabel } from "@/lib/wot";
import { parserStatusMeta, replayTitle, resultMeta, tagLabel, type WotReplay } from "@/lib/wotReplays";

/** Štítky replaye jako malé čipy (text, ne jen barva). */
export function ReplayTags({ tags }: { tags: string[] }) {
  if (!tags.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Štítky">
      {tags.map((t) => (
        <li key={t} data-tag={t} className="rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] text-ink-2">
          {tagLabel(t)}
        </li>
      ))}
    </ul>
  );
}

/** Oblíbený = značka ★ s textem (žádné pořadí ani skóre). */
export function FavoriteMarker() {
  return (
    <span data-testid="replay-favorite">
      <StatusBadge tone="warning">
        <span aria-hidden="true">★</span> Oblíbený
      </StatusBadge>
    </span>
  );
}

/** Řádek knihovny: tank (Game Enrichment A), mapa a datum, hlavní statistiky, štítky, propojení s Mkem. */
export function ReplayRow({
  replay: r,
  busy,
  onOpen,
  onToggleFavorite,
}: {
  replay: WotReplay;
  busy?: boolean;
  onOpen: () => void;
  onToggleFavorite: () => void;
}) {
  const resolved = useTankNameForTag(r.tank_tag);
  const title = replayTitle(r, resolved);
  const mastery = masteryLabel(r.mastery);
  const result = resultMeta(r.battle_result);
  const status = parserStatusMeta(r.parser_status);
  const stats = [
    r.damage != null ? `${formatNumber(r.damage)} dmg` : null,
    r.assist != null ? `${formatNumber(r.assist)} asist.` : null,
    r.kills != null ? `${r.kills} zničení` : null,
  ].filter(Boolean);
  return (
    <EntityRow
      searchTarget={`replay-${r.id}`}
      busy={busy}
      className={r.favorite ? "border-warning/40" : undefined}
      leading={<GameImage kind="tank" name={title} size="sm" />}
      badges={
        <>
          {r.favorite ? <FavoriteMarker /> : null}
          {mastery ? <StatusBadge tone="accent">{mastery}</StatusBadge> : null}
          {result ? <StatusBadge tone={result.tone}>{result.label}</StatusBadge> : null}
          {r.parser_status !== "parsed" ? (
            <span data-parser-status={r.parser_status}>
              <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            </span>
          ) : null}
          {r.milestone ? (
            <span data-testid="replay-milestone-link">
              <StatusBadge tone="info">Mko: {r.milestone.tank}</StatusBadge>
            </span>
          ) : null}
        </>
      }
      title={
        <button
          type="button"
          onClick={onOpen}
          className="relative text-left hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 after:absolute after:-inset-y-3 after:inset-x-0 after:content-['']"
        >
          {title}
        </button>
      }
      meta={
        <span className="tabular-nums">
          {[r.map_name, r.played_at ? formatDate(r.played_at) : null].filter(Boolean).join(" · ") || "Mapa a datum neuvedeny"}
          {stats.length ? <span className="text-ink-2"> · {stats.join(" · ")}</span> : null}
        </span>
      }
      actions={
        <>
          <Button size="sm" variant="secondary" onClick={onOpen} aria-label={`Detail replaye: ${title}`}>
            Detail
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onToggleFavorite}
            disabled={busy}
            aria-pressed={r.favorite}
            aria-label={r.favorite ? `Zrušit oblíbení: ${title}` : `Oblíbit replay: ${title}`}
          >
            <span aria-hidden="true">{r.favorite ? "★" : "☆"}</span>
          </Button>
        </>
      }
    >
      <ReplayTags tags={r.tags} />
    </EntityRow>
  );
}
