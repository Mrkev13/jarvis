"use client";

import { GameImage } from "@/components/games/GameImage";
import { CompletionState } from "@/components/motion/CompletionState";
import { Button, EntityRow, Progress, StatusBadge } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import { staggerStyle } from "@/lib/motion";
import { cx, priorityTone } from "@/lib/ui";
import { grindProgress, grindStatusMeta, type WotGrind } from "@/lib/wot";

/**
 * Aktivní grind: tank (Game Enrichment A), průběh, zbývající XP a výslovné „Splněno".
 * `celebrating` = právě splněno na serveru → 100 % + krátké „GRIND COMPLETE" (při omezeném pohybu statické).
 */
export function GrindRow({
  grind: g,
  index,
  celebrating,
  busy,
  onEdit,
  onDelete,
  onComplete,
}: {
  grind: WotGrind;
  index: number;
  celebrating?: boolean;
  busy?: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onComplete: () => void;
}) {
  const priority = priorityTone(g.priority);
  const status = grindStatusMeta(celebrating ? "completed" : g.status);
  const progress = celebrating ? 100 : grindProgress(g);
  return (
    <EntityRow
      searchTarget={g.id != null ? `grind-${g.id}` : undefined}
      style={staggerStyle(index)}
      className={cx("motion-card", celebrating && "border-accent/60")}
      tone={celebrating ? "accent" : "neutral"}
      leading={<GameImage kind="tank" name={g.tank} size="sm" />}
      badges={
        <>
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          <StatusBadge tone={priority.tone}>Priorita: {priority.label}</StatusBadge>
          <CompletionState
            as="span"
            complete={Boolean(celebrating)}
            className="rounded-md"
            label={
              <span
                data-testid="grind-complete"
                className="font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-accent-strong"
              >
                Grind complete
              </span>
            }
          >
            {null}
          </CompletionState>
        </>
      }
      title={g.tank}
      meta={
        <span className="tabular-nums">
          {celebrating ? (
            "Splněno – 0 XP zbývá"
          ) : (
            <>
              Zbývá <span className="font-medium text-ink">{formatNumber(g.xp_remaining)} XP</span>
              {g.xp_start ? <span className="text-ink-muted"> z {formatNumber(g.xp_start)}</span> : null}
            </>
          )}
        </span>
      }
      actions={
        celebrating ? null : (
          <>
            <Button size="sm" variant="success" onClick={onComplete} disabled={busy} aria-label={`Splněno: ${g.tank}`}>
              Splněno
            </Button>
            <Button size="sm" variant="secondary" onClick={onEdit} disabled={busy}>
              Upravit
            </Button>
            <Button size="sm" variant="ghost" onClick={onDelete} disabled={busy} aria-label={`Smazat grind ${g.tank}`}>
              Smazat
            </Button>
          </>
        )
      }
    >
      {progress !== null ? (
        <div className="mt-2 flex items-center gap-3">
          <Progress value={progress} tone={celebrating ? "accent" : undefined} label={`Průběh grindu ${g.tank}: ${progress} %`} className="flex-1" />
          <span className="w-10 text-right text-xs font-semibold tabular-nums text-ink-2">{progress} %</span>
        </div>
      ) : null}
    </EntityRow>
  );
}
