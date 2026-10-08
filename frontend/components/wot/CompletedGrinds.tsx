"use client";

import { useState } from "react";
import { GameImage } from "@/components/games/GameImage";
import { Button, Card, CardHeader, EmptyState, Icon } from "@/components/ui";
import { formatDate, formatNumber } from "@/lib/format";
import { durationLabel, sortCompletions, type CompletedGrind } from "@/lib/wot";

const VISIBLE = 5;

/** Splněné grindy – kompaktní historie (posledních 5, zbytek na rozbalení). */
export function CompletedGrinds({ items, highlightId }: { items: CompletedGrind[]; highlightId?: string | null }) {
  const [showAll, setShowAll] = useState(false);
  const sorted = sortCompletions(items);
  const shown = showAll ? sorted : sorted.slice(0, VISIBLE);
  return (
    <Card as="section" aria-labelledby="wot-completed" data-section="wot-completed">
      <CardHeader
        title={<span id="wot-completed">Splněné grindy</span>}
        description={sorted.length ? `${sorted.length} celkem` : undefined}
      />
      {sorted.length === 0 ? (
        <EmptyState compact>Zatím žádný splněný grind. Až nějaký dokončíš, objeví se tady.</EmptyState>
      ) : (
        <>
          <ul className="divide-y divide-line-subtle" aria-label="Splněné grindy">
            {shown.map((c) => {
              const duration = durationLabel(c.duration_days);
              return (
                <li key={c.id} data-completion={c.id} className={highlightId === c.id ? "bg-accent/5" : undefined}>
                  <div className="flex items-center gap-3 py-2.5">
                    <GameImage kind="tank" name={c.tank} size="xs" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-ink">{c.tank}</div>
                      <div className="text-xs text-ink-muted">
                        {c.completed_at ? `Splněno ${formatDate(c.completed_at)}` : "Splněno · datum neznámé"}
                        {duration ? ` · ${duration}` : ""}
                        {c.xp_start ? ` · ${formatNumber(c.xp_start)} XP` : ""}
                      </div>
                    </div>
                    <Icon name="check" size="sm" className="text-success" />
                  </div>
                </li>
              );
            })}
          </ul>
          {sorted.length > VISIBLE ? (
            <Button size="sm" variant="ghost" className="mt-2" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Zobrazit méně" : `Zobrazit všechny (${sorted.length})`}
            </Button>
          ) : null}
        </>
      )}
    </Card>
  );
}
