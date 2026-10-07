"use client";

import { GameImage } from "@/components/games/GameImage";
import { Button, Card, StatusBadge, TextLink } from "@/components/ui";
import { formatDate, formatNumber } from "@/lib/format";
import { cx } from "@/lib/ui";
import { masteryLabel, milestoneStats, type WotMilestone } from "@/lib/wot";
import { MilestoneGallery } from "./MilestoneGallery";

/** Jedna památná bitva: tank (Game Enrichment A), odznak, mapa a datum, statistiky, poznámka, screenshoty. */
export function MilestoneCard({
  milestone: m,
  busy,
  onEdit,
  onToggleFavorite,
  onDelete,
}: {
  milestone: WotMilestone;
  busy?: boolean;
  onEdit: () => void;
  onToggleFavorite: () => void;
  onDelete: () => void;
}) {
  const mastery = masteryLabel(m.mastery);
  const stats = milestoneStats(m);
  const titleId = `wot-milestone-${m.id}`;
  return (
    <Card
      as="li"
      aria-labelledby={titleId}
      data-milestone={m.id}
      data-favorite={m.favorite || undefined}
      className={cx("flex min-w-0 flex-col gap-3", m.favorite && "border-warning/40")}
    >
      <div className="flex items-start gap-3">
        <GameImage kind="tank" name={m.tank} size="sm" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {mastery ? <StatusBadge tone="accent">{mastery}</StatusBadge> : null}
            {m.favorite ? (
              <span data-testid="favorite-marker">
                <StatusBadge tone="warning">
                  <span aria-hidden="true">★</span> Legendární
                </StatusBadge>
              </span>
            ) : null}
          </div>
          <h3 id={titleId} className="mt-1 break-words text-base font-semibold text-ink">
            {m.tank}
          </h3>
          <p className="text-xs text-ink-muted">
            {[m.map_name, m.played_on ? formatDate(m.played_on) : null].filter(Boolean).join(" · ") || "Mapa a datum neuvedeny"}
          </p>
        </div>
      </div>

      {stats.length ? (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {stats.map((s) => (
            <div key={s.key} className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2.5 py-2">
              <dt className="text-[11px] text-ink-muted">{s.label}</dt>
              <dd className="text-base font-semibold tabular-nums text-ink">{formatNumber(s.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {m.notes ? <p className="whitespace-pre-line break-words text-sm text-ink-2">{m.notes}</p> : null}

      <MilestoneGallery shots={m.screenshots} tank={m.tank} />

      {m.replay_ids?.length ? (
        <p className="text-sm" data-testid="milestone-replay-link">
          <TextLink href={`/wot/replays?replay=${m.replay_ids[0]}`}>
            <span aria-hidden="true">▶&nbsp;</span>Replay bitvy{m.replay_ids.length > 1 ? ` (${m.replay_ids.length})` : ""}
          </TextLink>
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap gap-2 border-t border-line-subtle pt-3">
        <Button size="sm" variant="secondary" onClick={onEdit} disabled={busy}>
          Upravit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={onToggleFavorite}
          disabled={busy}
          aria-pressed={m.favorite}
          aria-label={m.favorite ? `Zrušit legendární: ${m.tank}` : `Označit jako legendární: ${m.tank}`}
        >
          <span aria-hidden="true">{m.favorite ? "★" : "☆"}</span> {m.favorite ? "Legendární" : "Oblíbit"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDelete} disabled={busy} aria-label={`Smazat milník ${m.tank}`}>
          Smazat
        </Button>
      </div>
    </Card>
  );
}
