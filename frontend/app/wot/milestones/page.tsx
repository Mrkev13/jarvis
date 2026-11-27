"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { MilestoneCard } from "@/components/wot/MilestoneCard";
import { MilestoneForm } from "@/components/wot/MilestoneForm";
import {
  AreaBadge,
  Button,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  PageSection,
  TextLink,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiFetch, jsonBody } from "@/lib/api";
import { pragueDayKey } from "@/lib/format";
import { sortMilestones, type WotGrind, type WotMilestone } from "@/lib/wot";

/**
 * MRK-152: M-ka a nejlepší bitvy – památné bitvy se statistikami a screenshoty (dřív dole na /wot). Přidání, úprava,
 * oblíbení a smazání beze změny; `?milestone=<id>` (odkaz z „Co se změnilo“) na kartu rovnou posune.
 */
function Milestones() {
  const params = useSearchParams();
  const focusId = Number(params.get("milestone")) || null;
  const milestonesRes = useApiResource<WotMilestone[]>("/wot/milestones");
  const grindsRes = useApiResource<WotGrind[]>("/wot/grinds");
  const milestones = sortMilestones(milestonesRes.data ?? []);
  const [form, setForm] = useState<{ open: boolean; milestone: WotMilestone | null }>({ open: false, milestone: null });
  const [deleting, setDeleting] = useState<WotMilestone | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [todayIso] = useState(() => pragueDayKey(new Date()));
  const knownTanks = [...new Set([...(grindsRes.data ?? []).map((g) => g.tank), ...milestones.map((m) => m.tank)])].sort((a, b) =>
    a.localeCompare(b, "cs"),
  );

  useEffect(() => {
    if (!focusId || milestonesRes.loading) return;
    document.querySelector(`[data-milestone="${focusId}"]`)?.scrollIntoView({ block: "center" });
  }, [focusId, milestonesRes.loading]);

  async function toggleFavorite(m: WotMilestone) {
    setBusy(m.id);
    setError(null);
    try {
      const res = await apiFetch(`/wot/milestones/${m.id}`, jsonBody("PATCH", { favorite: !m.favorite }));
      if (!res.ok) throw new Error("favorite failed");
      await milestonesRes.reload();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se změnit oblíbení.");
    } finally {
      setBusy(null);
    }
  }

  async function confirmDelete() {
    const m = deleting;
    if (!m) return;
    try {
      const res = await apiFetch(`/wot/milestones/${m.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("delete failed");
      await milestonesRes.reload();
    } catch (err) {
      console.error(err);
      setError("Milník se nepodařilo smazat.");
    } finally {
      setDeleting(null);
    }
  }

  const addButton = (
    <Button size="sm" variant="primary" onClick={() => setForm({ open: true, milestone: null })} aria-haspopup="dialog">
      Přidat Mko
    </Button>
  );

  return (
    <ContentContainer className="theme-wot">
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Tanks</HudLabel>}
        title="M-ka a nejlepší bitvy"
        subtitle="Památné bitvy se statistikami a screenshoty."
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <AreaBadge area="wot" />
            <TextLink href="/wot">← World of Tanks</TextLink>
          </span>
        }
        actions={addButton}
      />
      {error ? <ErrorState message={error} /> : null}
      <PageSection labelledBy="wot-milestones" title="Mka & nejlepší bitvy" description={`${milestones.length} záznamů`}>
        {milestonesRes.loading ? (
          <LoadingState lines={2} label="Načítám milníky…" />
        ) : milestonesRes.status === "error" ? (
          <ErrorState message="Milníky se nepodařilo načíst." onRetry={() => void milestonesRes.reload()} />
        ) : milestones.length === 0 ? (
          <EmptyState action={addButton}>Zatím žádné uložené Mko ani památná bitva.</EmptyState>
        ) : (
          <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2" aria-label="Milníky">
            {milestones.map((m) => (
              <MilestoneCard
                key={m.id}
                milestone={m}
                busy={busy === m.id}
                onEdit={() => setForm({ open: true, milestone: m })}
                onToggleFavorite={() => void toggleFavorite(m)}
                onDelete={() => setDeleting(m)}
              />
            ))}
          </ul>
        )}
      </PageSection>
      <ConfirmDialog
        open={deleting != null}
        title={`Smazat milník ${deleting?.tank ?? ""}?`}
        message="Smaže se záznam i všechny jeho screenshoty. Tato akce je nevratná."
        confirmLabel="Smazat milník"
        busyLabel="Mažu…"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
      <MilestoneForm
        open={form.open}
        milestone={form.milestone}
        knownTanks={knownTanks}
        today={todayIso}
        onClose={() => setForm({ open: false, milestone: null })}
        onSaved={() => milestonesRes.reload()}
      />
    </ContentContainer>
  );
}

export default function WotMilestonesPage() {
  return (
    <Suspense fallback={null}>
      <Milestones />
    </Suspense>
  );
}
