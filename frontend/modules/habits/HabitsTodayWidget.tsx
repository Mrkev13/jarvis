"use client";

import { Card, CardHeader, EmptyState, LoadingState, Progress, TextLink } from "@/components/ui";
import type { WidgetProps } from "@/components/dashboard/widgets";
import { percent, summaryFrom } from "./lib";

/** Widget Řídicího centra `habits_today` (MRK-21): dnešek a posledních 7 dní – data z GET /dashboard („habits"). */
export function HabitsTodayWidget({ data, loading, index }: WidgetProps) {
  const s = summaryFrom(data);
  return (
    <Card index={index} aria-labelledby="habits-widget-title">
      <CardHeader title={<span id="habits-widget-title">Návyky</span>} icon="check" actions={<TextLink href="/habits">Návyky →</TextLink>} />
      {loading ? (
        <LoadingState lines={2} />
      ) : s && s.total ? (
        <div className="space-y-3 text-sm" data-testid="habits-widget">
          <div>
            <div className="mb-1 flex justify-between gap-2">
              <span className="text-ink-muted">Dnes splněno</span>
              <span className="font-semibold tabular-nums text-ink">
                {s.done} / {s.total}
              </span>
            </div>
            <Progress value={percent(s.done, s.total)} label={`Dnes splněno ${s.done} z ${s.total}`} size="sm" />
            {s.skipped ? <p className="mt-1 text-xs text-ink-muted">Přeskočeno: {s.skipped}</p> : null}
          </div>
          {s.week_expected ? (
            <div className="flex justify-between gap-2 text-xs">
              <span className="text-ink-muted">Posledních 7 dní</span>
              <span className="tabular-nums text-ink-2">
                {s.week_done} / {s.week_expected} ({percent(s.week_done, s.week_expected)} %)
              </span>
            </div>
          ) : null}
        </div>
      ) : s ? (
        <EmptyState compact action={<TextLink href="/habits">Přidat návyk →</TextLink>}>Zatím žádné návyky.</EmptyState>
      ) : null}
    </Card>
  );
}
