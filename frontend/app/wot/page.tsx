"use client";

import { useEffect, useRef, useState } from "react";
import { GameImage } from "@/components/games/GameImage";
import { CompletedGrinds } from "@/components/wot/CompletedGrinds";
import { GrindRow } from "@/components/wot/GrindRow";
import { MilestoneCard } from "@/components/wot/MilestoneCard";
import { MilestoneForm } from "@/components/wot/MilestoneForm";
import {
  AreaBadge,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  EntityList,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  StatGrid,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiFetch, jsonBody } from "@/lib/api";
import { formatNumber, plural, pragueDayKey } from "@/lib/format";
import { prefersReducedMotion } from "@/lib/motion";
import {
  activeGrinds,
  grindSummary,
  celebrationDuration,
  emptyGrindDraft,
  GRIND_PRIORITIES,
  grindStatusOptions,
  grindBody,
  sortMilestones,
  RESOURCE_KEYS,
  RESOURCE_LABELS,
  resourceEntries,
  type CompletedGrind,
  type GrindDraft,
  type WotGrind,
  type WotMilestone,
  type WotResources,
} from "@/lib/wot";

const LOAD_ERROR = "Nepodařilo se načíst data z backendu.";

export default function WotPage() {
  const resourcesRes = useApiResource<WotResources>("/wot/resources");
  const grindsRes = useApiResource<WotGrind[]>("/wot/grinds");
  // Game Enrichment B: historie splnění a milníky – vlastní zdroje, chyba jednoho nesmí shodit stránku
  const completedRes = useApiResource<CompletedGrind[]>("/wot/grinds/completed");
  const milestonesRes = useApiResource<WotMilestone[]>("/wot/milestones");
  const resources = resourcesRes.data ?? {};
  const grinds = grindsRes.data ?? [];
  const completions = completedRes.data ?? [];
  const milestones = sortMilestones(milestonesRes.data ?? []);

  // splnění grindu: potvrzení → server → krátká oslava (při omezeném pohybu hned) → obnovení seznamů
  const [completing, setCompleting] = useState<WotGrind | null>(null);
  const [celebrating, setCelebrating] = useState<WotGrind | null>(null);
  const [completedNotice, setCompletedNotice] = useState<{ tank: string; id: string } | null>(null);
  const celebrationTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (celebrationTimer.current) window.clearTimeout(celebrationTimer.current);
    },
    [],
  );

  const [milestoneForm, setMilestoneForm] = useState<{ open: boolean; milestone: WotMilestone | null }>({ open: false, milestone: null });
  const [deletingMilestone, setDeletingMilestone] = useState<WotMilestone | null>(null);
  const [busyMilestone, setBusyMilestone] = useState<number | null>(null);
  const [todayIso] = useState(() => pragueDayKey(new Date())); // pražské datum pro „ne v budoucnu"

  const [showResourceForm, setShowResourceForm] = useState(false);
  const [resourceDraft, setResourceDraft] = useState<WotResources>({});

  const [showGrindForm, setShowGrindForm] = useState(false);
  const [grindMode, setGrindMode] = useState<"create" | "edit">("create");
  const [grindDraft, setGrindDraft] = useState<GrindDraft>(() => emptyGrindDraft());
  const [grindErrors, setGrindErrors] = useState<{ tank?: string; xp_remaining?: string }>({});

  const [submitting, setSubmitting] = useState<"resources" | "grind" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingGrind, setDeletingGrind] = useState<WotGrind | null>(null);

  const loading = resourcesRes.loading || grindsRes.loading;
  const loadFailed = resourcesRes.status === "error" || grindsRes.status === "error";
  const refreshing = resourcesRes.refreshing || grindsRes.refreshing;

  async function loadData() {
    await Promise.all([resourcesRes.reload(), grindsRes.reload()]);
  }

  function openResourceForm() {
    setResourceDraft(resources);
    setShowResourceForm(true);
  }

  async function handleResourceSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting("resources");
    setError(null);
    try {
      const entries = resourceEntries(resourceDraft);
      await Promise.all(
        entries.map((body) =>
          apiFetch("/wot/resource", jsonBody("POST", body)).then((r) => {
            if (!r.ok) throw new Error(`POST ${body.resource} failed`);
          }),
        ),
      );
      setShowResourceForm(false);
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit zdroje.");
    } finally {
      setSubmitting(null);
    }
  }

  function openNewGrind() {
    setGrindDraft(emptyGrindDraft());
    setGrindErrors({});
    setGrindMode("create");
    setShowGrindForm(true);
  }

  function editGrind(g: WotGrind) {
    setGrindDraft({
      tank: g.tank,
      xp_remaining: String(g.xp_remaining),
      priority: g.priority,
      status: g.status,
    });
    setGrindErrors({});
    setGrindMode("edit");
    setShowGrindForm(true);
  }

  async function handleGrindSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = grindBody(grindDraft);
    if (!parsed.ok) {
      setGrindErrors(parsed.errors);
      return;
    }
    setGrindErrors({});
    setSubmitting("grind");
    setError(null);
    try {
      const res = await apiFetch("/wot/grind", jsonBody("POST", parsed.body));
      if (!res.ok) throw new Error("Failed to save grind");
      setShowGrindForm(false);
      setGrindDraft(emptyGrindDraft());
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit grind.");
    } finally {
      setSubmitting(null);
    }
  }

  async function confirmDeleteGrind() {
    if (!deletingGrind || deletingGrind.id == null) return;
    try {
      const res = await apiFetch(`/wot/grind/${deletingGrind.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete grind");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat grind.");
    } finally {
      setDeletingGrind(null);
    }
  }

  async function confirmCompleteGrind() {
    const g = completing;
    if (!g || g.id == null) return;
    setError(null);
    try {
      const res = await apiFetch(`/wot/grind/${g.id}/complete`, { method: "POST" });
      if (!res.ok && res.status !== 409) throw new Error("complete failed");
      const body = res.ok ? ((await res.json()) as { completion?: { id?: string } }) : null;
      setCompleting(null);
      setCompletedNotice({ tank: g.tank, id: body?.completion?.id ?? "" });
      if (res.status === 409) {
        await Promise.all([grindsRes.reload(), completedRes.reload()]); // jiná záložka už grind splnila
        return;
      }
      const ms = celebrationDuration(prefersReducedMotion());
      if (ms === 0) {
        await Promise.all([grindsRes.reload(), completedRes.reload()]);
        return;
      }
      // oslava neblokuje nic: server už zapsal, seznamy se obnoví po ~1,3 s (nebo hned při odchodu ze stránky)
      setCelebrating(g);
      if (celebrationTimer.current) window.clearTimeout(celebrationTimer.current);
      celebrationTimer.current = window.setTimeout(() => {
        setCelebrating(null);
        void Promise.all([grindsRes.reload(), completedRes.reload()]);
      }, ms);
    } catch (err) {
      console.error(err);
      setCompleting(null);
      setError("Grind se nepodařilo označit jako splněný.");
    }
  }

  async function toggleFavorite(m: WotMilestone) {
    setBusyMilestone(m.id);
    setError(null);
    try {
      const res = await apiFetch(`/wot/milestones/${m.id}`, jsonBody("PATCH", { favorite: !m.favorite }));
      if (!res.ok) throw new Error("favorite failed");
      await milestonesRes.reload();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se změnit oblíbení.");
    } finally {
      setBusyMilestone(null);
    }
  }

  async function confirmDeleteMilestone() {
    const m = deletingMilestone;
    if (!m) return;
    try {
      const res = await apiFetch(`/wot/milestones/${m.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("delete failed");
      await milestonesRes.reload();
    } catch (err) {
      console.error(err);
      setError("Milník se nepodařilo smazat.");
    } finally {
      setDeletingMilestone(null);
    }
  }

  const visibleGrinds = activeGrinds(grinds).concat(celebrating && !activeGrinds(grinds).some((g) => g.id === celebrating.id) ? [celebrating] : []);
  const knownTanks = [...new Set([...grinds.map((g) => g.tank), ...completions.map((c) => c.tank), ...milestones.map((m) => m.tank)])].sort((a, b) =>
    a.localeCompare(b, "cs"),
  );

  // během oslavy už server grind splnil → hlavička ho nepočítá (seznam se obnoví až po ~1,3 s)
  const { activeCount, remaining: remainingTotal } = grindSummary(grinds, celebrating?.id);

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Tanks</HudLabel>}
        title="World of Tanks"
        subtitle="Zdroje a grindy tanků."
        meta={<AreaBadge area="wot" />}
      />

      {error ? <ErrorState message={error} /> : null}

      {loading ? (
        <LoadingState lines={4} label="Načítám data World of Tanks…" />
      ) : loadFailed ? (
        <ErrorState message={LOAD_ERROR} onRetry={() => void loadData()} retrying={refreshing} />
      ) : (
        <div className="space-y-6 md:space-y-8" aria-busy={refreshing || undefined}>
          {/* ===== ZDROJE ===== */}
          <Card as="section" id="resources" aria-labelledby="wot-resources" index={0} className="border-t-2 border-t-orange-400/40">
            <CardHeader
              title={<span id="wot-resources">Zdroje</span>}
              actions={
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={openResourceForm}
                  aria-expanded={showResourceForm}
                  aria-controls="wot-resource-form"
                >
                  Upravit zdroje
                </Button>
              }
            />
            <StatGrid cols={4}>
              {RESOURCE_KEYS.map((key) => (
                <MetricCard
                  key={key}
                  label={
                    <span className="inline-flex items-center gap-1.5">
                      <GameImage kind="resource" name={key} size="xs" />
                      {RESOURCE_LABELS[key]}
                    </span>
                  }
                  value={formatNumber(resources[key])}
                />
              ))}
            </StatGrid>

            {showResourceForm && (
              <form id="wot-resource-form" onSubmit={handleResourceSubmit} className="mt-4 space-y-4 border-t border-line-subtle pt-4">
                <h3 className="text-base font-semibold text-ink">Upravit zdroje</h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {RESOURCE_KEYS.map((key) => (
                    <FormField key={key} label={RESOURCE_LABELS[key]}>
                      {(p) => (
                        <input
                          {...p}
                          type="number"
                          inputMode="numeric"
                          value={resourceDraft[key] ?? ""}
                          onChange={(e) =>
                            setResourceDraft((prev) => ({
                              ...prev,
                              [key]: e.target.value === "" ? undefined : Number(e.target.value),
                            }))
                          }
                          className={fieldClass}
                          placeholder="0"
                        />
                      )}
                    </FormField>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" variant="primary" busy={submitting === "resources"} busyLabel="Ukládám…">
                    Uložit
                  </Button>
                  <Button variant="ghost" onClick={() => setShowResourceForm(false)}>
                    Zrušit
                  </Button>
                </div>
              </form>
            )}
          </Card>

          {/* ===== GRINDY ===== */}
          <PageSection
            labelledBy="wot-grinds"
            title="Grindy tanků"
            description={
              grinds.length
                ? `${activeCount} ${plural(activeCount, "aktivní", "aktivní", "aktivních")} · zbývá ${formatNumber(remainingTotal)} XP`
                : undefined
            }
            actions={
              <Button
                size="sm"
                variant="primary"
                onClick={openNewGrind}
                aria-expanded={showGrindForm && grindMode === "create"}
                aria-controls="wot-grind-form"
              >
                Přidat grind
              </Button>
            }
          >
            <div id="grinds" className="space-y-3">
              {showGrindForm && (
                <Card as="div" inset>
                  <form id="wot-grind-form" onSubmit={handleGrindSubmit} noValidate className="space-y-4">
                    <h3 className="text-base font-semibold text-ink">{grindMode === "edit" ? "Upravit grind" : "Nový grind"}</h3>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      <FormField label="Tank" error={grindErrors.tank}>
                        {(p) => (
                          <input
                            {...p}
                            type="text"
                            value={grindDraft.tank}
                            onChange={(e) => setGrindDraft((d) => ({ ...d, tank: e.target.value }))}
                            className={fieldClass}
                            placeholder="např. VZ.55"
                          />
                        )}
                      </FormField>
                      <FormField label="Zbývá XP" error={grindErrors.xp_remaining}>
                        {(p) => (
                          <input
                            {...p}
                            type="number"
                            inputMode="numeric"
                            value={grindDraft.xp_remaining}
                            onChange={(e) => setGrindDraft((d) => ({ ...d, xp_remaining: e.target.value }))}
                            className={fieldClass}
                            placeholder="0"
                          />
                        )}
                      </FormField>
                      <FormField label="Priorita">
                        {(p) => (
                          <select
                            {...p}
                            value={grindDraft.priority}
                            onChange={(e) => setGrindDraft((d) => ({ ...d, priority: e.target.value }))}
                            className={fieldClass}
                          >
                            {GRIND_PRIORITIES.map((o) => (
                              <option key={o.value} value={o.value}>
                                {o.label}
                              </option>
                            ))}
                          </select>
                        )}
                      </FormField>
                      <FormField label="Stav">
                        {(p) => (
                          <select
                            {...p}
                            value={grindDraft.status}
                            onChange={(e) => setGrindDraft((d) => ({ ...d, status: e.target.value }))}
                            className={fieldClass}
                          >
                            {grindStatusOptions(grindMode).map((o) => (
                              <option key={o.value} value={o.value}>
                                {o.label}
                              </option>
                            ))}
                          </select>
                        )}
                      </FormField>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button type="submit" variant="primary" busy={submitting === "grind"} busyLabel="Ukládám…">
                        Uložit
                      </Button>
                      <Button variant="ghost" onClick={() => setShowGrindForm(false)}>
                        Zrušit
                      </Button>
                    </div>
                  </form>
                </Card>
              )}

              {completedNotice ? (
                <p
                  role="status"
                  data-testid="grind-complete-notice"
                  className="flex items-center gap-2 rounded-[var(--radius-control)] border border-accent/40 bg-accent/5 px-3 py-2 text-sm text-ink"
                >
                  <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-accent-strong">Grind complete</span>
                  <span className="min-w-0 flex-1">{completedNotice.tank} je splněný – najdeš ho ve Splněných grindech.</span>
                  <Button size="sm" variant="ghost" onClick={() => setCompletedNotice(null)} aria-label="Zavřít oznámení">
                    ×
                  </Button>
                </p>
              ) : null}
              {visibleGrinds.length === 0 ? (
                <EmptyState
                  action={
                    showGrindForm ? undefined : (
                      <Button size="sm" variant="secondary" onClick={openNewGrind}>
                        Přidat grind
                      </Button>
                    )
                  }
                >
                  {completions.length ? "Žádný aktivní grind – všechno splněno." : "Zatím žádné grindy."}
                </EmptyState>
              ) : (
                <EntityList label="Aktivní grindy">
                  {visibleGrinds.map((g, idx) => (
                    <GrindRow
                      key={g.id ?? g.tank}
                      grind={g}
                      index={idx}
                      celebrating={celebrating?.id === g.id}
                      busy={celebrating !== null}
                      onEdit={() => editGrind(g)}
                      onDelete={() => setDeletingGrind(g)}
                      onComplete={() => setCompleting(g)}
                    />
                  ))}
                </EntityList>
              )}
            </div>
          </PageSection>

          {/* ===== SPLNĚNÉ GRINDY ===== */}
          {completedRes.status === "error" ? (
            <ErrorState message="Historii splněných grindů se nepodařilo načíst." onRetry={() => void completedRes.reload()} />
          ) : (
            <CompletedGrinds items={completions} highlightId={completedNotice?.id || null} />
          )}

          {/* ===== MILNÍKY ===== */}
          <PageSection
            labelledBy="wot-milestones"
            title="Mka & nejlepší bitvy"
            description="Památné bitvy se statistikami a screenshoty."
            actions={
              <Button size="sm" variant="primary" onClick={() => setMilestoneForm({ open: true, milestone: null })} aria-haspopup="dialog">
                Přidat Mko
              </Button>
            }
          >
            {milestonesRes.loading ? (
              <LoadingState lines={2} label="Načítám milníky…" />
            ) : milestonesRes.status === "error" ? (
              <ErrorState message="Milníky se nepodařilo načíst." onRetry={() => void milestonesRes.reload()} />
            ) : milestones.length === 0 ? (
              <EmptyState
                action={
                  <Button size="sm" variant="secondary" onClick={() => setMilestoneForm({ open: true, milestone: null })}>
                    Přidat první Mko
                  </Button>
                }
              >
                Zatím žádné uložené Mko ani památná bitva.
              </EmptyState>
            ) : (
              <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2" aria-label="Milníky">
                {milestones.map((m) => (
                  <MilestoneCard
                    key={m.id}
                    milestone={m}
                    busy={busyMilestone === m.id}
                    onEdit={() => setMilestoneForm({ open: true, milestone: m })}
                    onToggleFavorite={() => void toggleFavorite(m)}
                    onDelete={() => setDeletingMilestone(m)}
                  />
                ))}
              </ul>
            )}
          </PageSection>
          {/* ===== KNIHOVNA REPLAYŮ (Game Enrichment C) – na /wot jen odkaz ===== */}
          <Card as="section" aria-labelledby="wot-replays-link" data-section="wot-replays">
            <CardHeader
              title={<span id="wot-replays-link">Knihovna replayů</span>}
              description="Originální .wotreplay soubory se štítky, filtry a propojením na Mka."
              actions={
                <ButtonLink href="/wot/replays" variant="secondary" size="sm">
                  Otevřít knihovnu
                </ButtonLink>
              }
            />
          </Card>
        </div>
      )}

      <ConfirmDialog
        open={completing != null}
        title={`Označit ${completing?.tank ?? ""} jako splněný?`}
        message="Grind se přesune do Splněných grindů (průběh 100 %). Data grindu zůstanou zachovaná."
        confirmLabel="Splněno"
        busyLabel="Ukládám…"
        danger={false}
        onConfirm={confirmCompleteGrind}
        onCancel={() => setCompleting(null)}
      />
      <ConfirmDialog
        open={deletingMilestone != null}
        title={`Smazat milník ${deletingMilestone?.tank ?? ""}?`}
        message="Smaže se záznam i všechny jeho screenshoty. Tato akce je nevratná."
        confirmLabel="Smazat milník"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteMilestone}
        onCancel={() => setDeletingMilestone(null)}
      />
      <MilestoneForm
        open={milestoneForm.open}
        milestone={milestoneForm.milestone}
        knownTanks={knownTanks}
        today={todayIso}
        onClose={() => setMilestoneForm({ open: false, milestone: null })}
        onSaved={() => milestonesRes.reload()}
      />
      <ConfirmDialog
        open={deletingGrind != null}
        title={`Smazat grind ${deletingGrind?.tank ?? ""}?`}
        message="Tato akce je nevratná. Grind bude odstraněn ze Standa Hubu."
        confirmLabel="Smazat grind"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteGrind}
        onCancel={() => setDeletingGrind(null)}
      />
    </ContentContainer>
  );
}
