"use client";

import { Card, CardHeader, StatusBadge, TextLink } from "@/components/ui";
import { Skeleton } from "@/components/ui/states";
import { useApiResource, type ApiResource } from "@/hooks/useApiResource";
import { reviewView, type WeeklyPayload } from "@/lib/weeklyReview";

/** Kompaktní vstup na dashboardu; celý přehled a historie jsou na /review. */
export default function WeeklyReviewCard({ index, resource }: { index?: number; resource?: ApiResource<WeeklyPayload> }) {
  const own = useApiResource<WeeklyPayload>(resource ? null : "/weekly-review");
  const { data, loading, status } = resource ?? own;
  const view = data ? reviewView(data) : null;
  return (
    <Card index={index} aria-labelledby="weekly-card-title">
      <CardHeader
        title={<span id="weekly-card-title">Týdenní přehled</span>}
        icon="calendar"
        actions={<TextLink href="/review">Otevřít →</TextLink>}
      />
      {loading ? (
        <div className="space-y-2" role="status" aria-label="Načítám">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-10" />
        </div>
      ) : status === "error" ? (
        <p className="text-sm text-ink-muted">Přehled se nepodařilo načíst.</p>
      ) : view?.kind === "ready" ? (
        <div>
          <p className="text-xs text-ink-muted">{data?.week_label}</p>
          <p className="mt-0.5 break-words font-semibold text-ink">{view.content.headline}</p>
          <p className="mt-1 line-clamp-2 text-sm text-ink-2">{view.content.summary}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {view.content.wins.length ? <StatusBadge tone="success">{view.content.wins.length}× dobře</StatusBadge> : null}
            {view.content.concerns.length ? <StatusBadge tone="warning">{view.content.concerns.length}× pozor</StatusBadge> : null}
            {view.content.forecasts.length ? <StatusBadge tone="ai">{view.content.forecasts.length}× odhad</StatusBadge> : null}
          </div>
        </div>
      ) : (
        <p className="text-sm text-ink-muted">
          {view?.kind === "generating" ? "Přehled se právě vytváří…" : view && "message" in view ? view.message : null}
        </p>
      )}
    </Card>
  );
}
