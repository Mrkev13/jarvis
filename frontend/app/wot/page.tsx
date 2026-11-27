"use client";

import { HangarHero } from "@/components/wot/HangarHero";
import { medalRank } from "@/lib/wotHangar";
import { AskJarvis } from "@/components/ai/AskJarvis";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { GameImage } from "@/components/games/GameImage";
import { CompletedGrinds } from "@/components/wot/CompletedGrinds";
import { GrindRow } from "@/components/wot/GrindRow";
import { WargamingLink } from "@/components/wot/WargamingLink";
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
import { formatDateTime, formatNumber, plural, pragueDayKey } from "@/lib/format";
import { pulseJarvis } from "@/lib/jarvisSignals";
import { setPendingReplay } from "@/lib/pendingReplay";
import { compactNumber, pct, type WotStats } from "@/lib/wotStats";
import { prefersReducedMotion } from "@/lib/motion";
import {
  activeGrinds,
  grindSummary,
  celebrationDuration,
  emptyGrindDraft,
  GRIND_PRIORITIES,
  grindStatusOptions,
  grindBody,
  masterySummary,
  sortMilestones,
  RESOURCE_KEYS,
  RESOURCE_LABELS,
  resourceEntries,
  type CompletedGrind,
  type GrindDraft,
  type WotGrind,
  type WotMilestone,
  displayResources,
  type WotAccount,
  type WotResources,
} from "@/lib/wot";

const LOAD_ERROR = "Nepodařilo se načíst data z backendu.";

/** MRK-105: odkud a kdy je hodnota zdroje. */
function resourceHint(meta: { source: string | null; updated_at: string | null } | undefined): string | undefined {
  if (!meta?.updated_at) return undefined;
  return `${meta.source === "wargaming" ? "z Wargamingu" : "ručně"} · ${formatDateTime(meta.updated_at)}`;
}

export default function WotPage() {
  const resourcesRes = useApiResource<WotResources>("/wot/resources");
  const accountRes = useApiResource<WotAccount>("/wot/account"); // MRK-105: propojení s Wargamingem
  const grindsRes = useApiResource<WotGrind[]>("/wot/grinds");
  // Game Enrichment B: historie splnění a milníky – vlastní zdroje, chyba jednoho nesmí shodit stránku
  const completedRes = useApiResource<CompletedGrind[]>("/wot/grinds/completed");
  const milestonesRes = useApiResource<WotMilestone[]>("/wot/milestones");
  const todayStats = useApiResource<WotStats>("/wot/stats?period=today"); // MRK-153: karta „Dnes ve WoT“
  const resources = resourcesRes.data ?? {};
  const shown = displayResources(resources, accountRes.data); // MRK-105: částka + původ z jednoho snímku
  const grinds = grindsRes.data ?? [];
  const completions = completedRes.data ?? [];
  const milestones = sortMilestones(milestonesRes.data ?? []);
  const mastery = masterySummary(milestones);

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
  const router = useRouter();
  const replayInput = useRef<HTMLInputElement>(null);
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
    // MRK-105: i snímek účtu – po ručním zápisu musí zobrazená částka i „ručně · čas“ sedět
    await Promise.all([resourcesRes.reload(), grindsRes.reload(), accountRes.reload()]);
  }

  function openResourceForm() {
    setResourceDraft(Object.fromEntries(RESOURCE_KEYS.map((k) => [k, shown[k].amount])) as WotResources);
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
      if (res.ok) pulseJarvis("success");
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
      pulseJarvis("error");
    }
  }

  const visibleGrinds = activeGrinds(grinds).concat(celebrating && !activeGrinds(grinds).some((g) => g.id === celebrating.id) ? [celebrating] : []);
  const knownTanks = [...new Set([...grinds.map((g) => g.tank), ...completions.map((c) => c.tank), ...milestones.map((m) => m.tank)])].sort((a, b) =>
    a.localeCompare(b, "cs"),
  );

  // během oslavy už server grind splnil → hlavička ho nepočítá (seznam se obnoví až po ~1,3 s)
  const { activeCount, remaining: remainingTotal } = grindSummary(grinds, celebrating?.id);

  return (
    <ContentContainer className="theme-wot">
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Tanks</HudLabel>}
        title="World of Tanks"
        subtitle="Zdroje, Mka a grindy tanků."
        meta={<AreaBadge area="wot" />}
      />

      {error ? <ErrorState message={error} /> : null}

      {/* MRK-138: hangár – zaměřený tank (první aktivní grind) místo obecného HUD jádra (MRK-134) */}
      {!loading && !loadFailed ? (
        <HangarHero grind={activeGrinds(grinds)[0] ?? null} activeCount={activeCount} aces={mastery.total} />
      ) : null}

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
                  value={formatNumber(shown[key].amount)}
                  hint={resourceHint(shown[key])}
                />
              ))}
            </StatGrid>
            <WargamingLink account={accountRes.data} onChange={() => Promise.all([accountRes.reload(), resourcesRes.reload()])} />

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

          {/* ===== POČÍTADLO M-EK (MRK-82) – stejné pravidlo jako automatický cíl „wot_ace_mastery_count" ===== */}
          <Card as="section" aria-labelledby="wot-mastery" data-section="wot-mastery" index={0} className="border-t-2 border-t-amber-400/40">
            <CardHeader
              title={<span id="wot-mastery">Mka</span>}
              description="Síň slávy – detaily, bitvy a odznaky všech tanků na vlastních stránkách."
            />
            {milestonesRes.loading ? (
              <LoadingState lines={1} label="Počítám Mka…" />
            ) : milestonesRes.status === "error" ? (
              <p className="text-sm text-ink-muted">Počítadlo se nepodařilo načíst – zkus obnovit stránku.</p>
            ) : (
              <>
                <StatGrid cols={2}>
                  <MetricCard label="Mka celkem" value={formatNumber(mastery.total)} />
                  <MetricCard label="Tanků s Mkem" value={formatNumber(mastery.tanks)} />
                </StatGrid>
                {mastery.byTank.length > 0 ? (
                  // MRK-138: síň slávy – každý tank s Mkem jako medaile (bronz / stříbro / zlato podle počtu)
                  <ul className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" aria-label="Mka podle tanků">
                    {mastery.byTank.slice(0, 12).map((t, i) => (
                      <li
                        key={t.tank}
                        data-medal={medalRank(t.count)}
                        className="wot-medal flex min-w-0 items-center gap-2 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 py-1.5 pl-1.5 pr-2.5 text-sm text-ink"
                        style={{ ["--i" as string]: Math.min(i, 11) } as React.CSSProperties}
                      >
                        <MedalIcon rank={medalRank(t.count)} />
                        <GameImage kind="tank" name={t.tank} size="xs" />
                        <span className="min-w-0 flex-1 truncate">{t.tank}</span>
                        {t.count > 1 ? <span className="font-semibold tabular-nums text-ink-muted">×{t.count}</span> : null}
                      </li>
                    ))}
                    {mastery.byTank.length > 12 ? (
                      <li className="self-center text-sm text-ink-muted">+{mastery.byTank.length - 12} dalších</li>
                    ) : null}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-ink-muted">Zatím žádné Mko. Přidej první tlačítkem Přidat Mko níže.</p>
                )}
              </>
            )}
            {/* MRK-152: cesty z M-ek – podstránky a rychlé přidání */}
            <nav aria-label="M-ka – další" className="mt-4 flex flex-wrap gap-2 border-t border-line-subtle pt-4" data-wot-mastery-links>
              <ButtonLink href="/wot/mastery" size="sm" variant="secondary">M-ka všech tanků</ButtonLink>
              <ButtonLink href="/wot/milestones" size="sm" variant="secondary">M-ka a nejlepší bitvy</ButtonLink>
              <ButtonLink href="/wot/replays" size="sm" variant="ghost">Knihovna replayů</ButtonLink>
              <span className="hidden flex-1 sm:block" aria-hidden />
              <Button size="sm" variant="primary" onClick={() => setMilestoneForm({ open: true, milestone: null })} aria-haspopup="dialog">
                Přidat Mko
              </Button>
              <Button size="sm" variant="primary" onClick={() => replayInput.current?.click()}>
                Přidat replay
              </Button>
              <input
                ref={replayInput}
                type="file"
                accept=".wotreplay"
                className="sr-only"
                tabIndex={-1}
                aria-hidden="true"
                data-testid="overview-replay-input"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  setPendingReplay(file); // knihovna replayů ho nahraje stejnou cestou jako vlastní tlačítko
                  router.push("/wot/replays?upload=1");
                }}
              />
            </nav>
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

          {/* ===== DNES VE WOT (MRK-153) – souhrn dne, grafy a období na /wot/stats ===== */}
          <Card as="section" aria-labelledby="wot-today-stats" data-section="wot-today-stats">
            <CardHeader
              title={<span id="wot-today-stats">Dnes ve WoT</span>}
              description="Automaticky z Wargaming API – bitvy, hodnocení a zdroje v čase."
              actions={<ButtonLink href="/wot/stats" size="sm" variant="secondary">Statistiky a grafy</ButtonLink>}
            />
            {todayStats.data ? (
              todayStats.data.summary.battles > 0 ? (
                <StatGrid cols={4}>
                  <MetricCard label="Bitvy" value={todayStats.data.summary.battles.toLocaleString("cs-CZ")} />
                  <MetricCard label="Výhry" value={pct(todayStats.data.summary.win_rate)} />
                  <MetricCard label="Ø damage" value={compactNumber(todayStats.data.summary.avg_damage)} />
                  <MetricCard label="Hodnocení" value={todayStats.data.rating_now?.toLocaleString("cs-CZ") ?? "–"}
                    hint={todayStats.data.rating_change ? `${todayStats.data.rating_change > 0 ? "+" : ""}${todayStats.data.rating_change} dnes` : undefined} />
                </StatGrid>
              ) : (
                <p className="text-sm text-ink-muted">Dnes zatím žádné bitvy{todayStats.data.rating_now ? ` · hodnocení ${todayStats.data.rating_now.toLocaleString("cs-CZ")}` : ""}.</p>
              )
            ) : todayStats.status === "error" ? (
              <p className="text-sm text-ink-muted">Statistiky se nepodařilo načíst.</p>
            ) : (
              <LoadingState lines={1} label="Načítám dnešní statistiky…" />
            )}
          </Card>

          {/* ===== SPLNĚNÉ GRINDY ===== */}
          {completedRes.status === "error" ? (
            <ErrorState message="Historii splněných grindů se nepodařilo načíst." onRetry={() => void completedRes.reload()} />
          ) : (
            <CompletedGrinds items={completions} highlightId={completedNotice?.id || null} />
          )}

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
      <AskJarvis surface="wot" />
    </ContentContainer>
  );
}


/** MRK-138: medaile síně slávy – vlastní SVG (hvězda ve věnci), ne grafika Wargamingu. */
function MedalIcon({ rank }: { rank: "bronze" | "silver" | "gold" }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" className={`wot-medal-icon wot-medal-${rank} shrink-0`}>
      <path d="M8 1h8l-2 6h-4z" className="wot-medal-ribbon" />
      <circle cx="12" cy="14.5" r="8" className="wot-medal-disc" />
      <path d="M12 9.5l1.5 3.1 3.4.5-2.5 2.4.6 3.4-3-1.6-3 1.6.6-3.4-2.5-2.4 3.4-.5z" className="wot-medal-star" />
    </svg>
  );
}
