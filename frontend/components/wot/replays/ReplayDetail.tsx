"use client";

import { GameImage } from "@/components/games/GameImage";
import { MilestoneGallery } from "@/components/wot/MilestoneGallery";
import { Button, buttonClass, Drawer, StatusBadge } from "@/components/ui";
import { useTankNameForTag } from "@/hooks/useGameAssets";
import { apiUrl } from "@/lib/api";
import { formatDate, formatNumber, formatTime } from "@/lib/format";
import { masteryLabel } from "@/lib/wot";
import { formatFileSize, parserStatusMeta, replayStats, replayTitle, resultMeta, tankTagShort, type WotReplay } from "@/lib/wotReplays";
import { FavoriteMarker, ReplayTags } from "./ReplayRow";

/** Detail replaye v bočním panelu: tank, mapa, datum, statistiky, štítky, poznámka, Mko, soubor, stažení. */
export function ReplayDetail({
  replay: r,
  open,
  onClose,
  onEdit,
  onDelete,
}: {
  replay: WotReplay | null;
  open: boolean;
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const resolved = useTankNameForTag(r?.tank_tag);
  if (!r) return null;
  const title = replayTitle(r, resolved);
  const mastery = masteryLabel(r.mastery);
  const result = resultMeta(r.battle_result);
  const status = parserStatusMeta(r.parser_status);
  const stats = replayStats(r);
  return (
    <Drawer open={open} onClose={onClose} title="Detail replaye">
      <div className="space-y-5 p-4" data-testid="replay-detail" data-replay={r.id}>
        <div className="flex items-start gap-3">
          <GameImage kind="tank" name={title} size="md" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {r.favorite ? <FavoriteMarker /> : null}
              {mastery ? <StatusBadge tone="accent">{mastery}</StatusBadge> : null}
              {result ? <StatusBadge tone={result.tone}>{result.label}</StatusBadge> : null}
            </div>
            <h3 className="mt-1 break-words text-lg font-semibold text-ink">{title}</h3>
            <p className="text-sm text-ink-muted">
              {[r.map_name, r.played_at ? `${formatDate(r.played_at)} ${formatTime(r.played_at)}` : null].filter(Boolean).join(" · ") || "Mapa a datum neuvedeny"}
            </p>
          </div>
        </div>

        {stats.length ? (
          <dl className="grid grid-cols-2 gap-2">
            {stats.map((s) => (
              <div key={s.key} className="rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2.5 py-2">
                <dt className="text-[11px] text-ink-muted">{s.label}</dt>
                <dd className="text-base font-semibold tabular-nums text-ink">{formatNumber(s.value)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-ink-muted">Statistiky zatím nejsou vyplněné.</p>
        )}

        <ReplayTags tags={r.tags} />
        {r.notes ? <p className="whitespace-pre-line break-words text-sm text-ink-2">{r.notes}</p> : null}

        <section aria-label="Propojené Mko" className="space-y-2 border-t border-line-subtle pt-4">
          <h4 className="text-sm font-semibold text-ink">Mko / milník</h4>
          {r.milestone ? (
            <>
              <p className="text-sm text-ink-2" data-testid="replay-detail-milestone">
                {r.milestone.tank}
                {r.milestone.mastery ? ` · ${masteryLabel(r.milestone.mastery)}` : ""}
                {r.milestone.map_name ? ` · ${r.milestone.map_name}` : ""}
                {r.milestone.played_on ? ` · ${formatDate(r.milestone.played_on)}` : ""}
              </p>
              <MilestoneGallery shots={r.milestone.screenshots} tank={r.milestone.tank} />
            </>
          ) : (
            <p className="text-sm text-ink-muted">Bez propojení – Mko jde vybrat v úpravě.</p>
          )}
        </section>

        <section aria-label="Soubor" className="space-y-2 border-t border-line-subtle pt-4">
          <h4 className="text-sm font-semibold text-ink">Soubor</h4>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-ink-muted">Název</dt>
            <dd className="min-w-0 break-all text-ink-2" data-testid="replay-filename">{r.original_filename ?? "–"}</dd>
            <dt className="text-ink-muted">Velikost</dt>
            <dd className="tabular-nums text-ink-2">{formatFileSize(r.file_size)}</dd>
            {r.tank_tag ? (
              <>
                <dt className="text-ink-muted">Vozidlo</dt>
                <dd className="min-w-0 break-all text-ink-2">{tankTagShort(r.tank_tag)}</dd>
              </>
            ) : null}
            {r.game_version ? (
              <>
                <dt className="text-ink-muted">Verze hry</dt>
                <dd className="text-ink-2">{r.game_version}</dd>
              </>
            ) : null}
            <dt className="text-ink-muted">Nahráno</dt>
            <dd className="text-ink-2">{r.uploaded_at ? `${formatDate(r.uploaded_at)} ${formatTime(r.uploaded_at)}` : "–"}</dd>
          </dl>
          <div className="flex flex-wrap items-center gap-2" data-parser-status={r.parser_status}>
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <span className="text-xs text-ink-muted">{status.hint}</span>
          </div>
          {r.parser_warnings.length && r.parser_status !== "parsed" ? (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-muted">
              {r.parser_warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </section>

        <div className="flex flex-wrap gap-2 border-t border-line-subtle pt-4">
          <a href={apiUrl(r.download_url)} download className={buttonClass("primary", "sm")} data-testid="replay-download">
            Stáhnout originál
          </a>
          <Button size="sm" variant="secondary" onClick={onEdit}>
            Upravit údaje
          </Button>
          <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Smazat replay ${title}`}>
            Smazat
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
