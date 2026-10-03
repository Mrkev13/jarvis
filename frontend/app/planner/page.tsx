"use client";

import { useState } from "react";
import {
  Button,
  ContentContainer,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  Tabs,
} from "@/components/ui";
import { DailyPlanCard, GoalReviewCard, WeeklyPlanCard, type GoalReview, type PlannerPlan } from "@/components/PlannerCards";
import { useApiResource } from "@/hooks/useApiResource";

type Mode = "daily" | "weekly" | "goal_review";

const MODES: Array<{ value: Mode; label: string }> = [
  { value: "daily", label: "Dnes" },
  { value: "weekly", label: "Týden" },
  { value: "goal_review", label: "Cíle" },
];

export default function PlannerPage() {
  const [mode, setMode] = useState<Mode>("daily");
  const plan = useApiResource<PlannerPlan | GoalReview>(`/planner?mode=${mode}`);

  // Při přepnutí režimu se nezobrazuje plán z předchozího režimu.
  const current = plan.data && plan.data.mode === mode ? plan.data : null;

  return (
    <ContentContainer width="narrow">
      <PageHeader
        eyebrow={<HudLabel>Modul · plánovač</HudLabel>}
        title="Plánovač"
        subtitle="Doporučení jen z uložených dat – termíny, cíle, práce a finance."
        actions={
          <Button size="sm" onClick={() => void plan.reload()} busy={plan.refreshing} busyLabel="Obnovuji…" disabled={plan.loading}>
            Obnovit
          </Button>
        }
      />

      <Tabs id="planner-mode" label="Režim plánu" items={MODES} value={mode} onChange={setMode} />

      <div role="tabpanel" id="planner-mode-panel" aria-labelledby={`planner-mode-${mode}`} aria-busy={plan.loading || plan.refreshing}>
        {plan.error && !current ? (
          <ErrorState message={plan.error} onRetry={() => void plan.reload()} retrying={plan.refreshing} />
        ) : !current ? (
          <LoadingState lines={4} label="Načítám plán…" />
        ) : (
          <>
            {plan.error ? <ErrorState className="mb-4" message={plan.error} onRetry={() => void plan.reload()} /> : null}
            {current.mode === "daily" ? <DailyPlanCard plan={current} headingLevel="h2" /> : null}
            {current.mode === "weekly" ? <WeeklyPlanCard plan={current} headingLevel="h2" /> : null}
            {current.mode === "goal_review" ? <GoalReviewCard plan={current} headingLevel="h2" /> : null}
          </>
        )}
      </div>
    </ContentContainer>
  );
}
