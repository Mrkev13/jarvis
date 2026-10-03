"use client";

import { useState } from "react";
import {
  AreaBadge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  EntityList,
  EntityRow,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  StatGrid,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiFetch, jsonBody } from "@/lib/api";
import { formatNumber, plural } from "@/lib/format";
import { staggerStyle } from "@/lib/motion";
import { priorityTone } from "@/lib/ui";
import {
  activeXpRemaining,
  emptyGrindDraft,
  GRIND_PRIORITIES,
  GRIND_STATUSES,
  grindBody,
  grindStatusMeta,
  RESOURCE_KEYS,
  RESOURCE_LABELS,
  resourceEntries,
  type GrindDraft,
  type WotGrind,
  type WotResources,
} from "@/lib/wot";

const LOAD_ERROR = "Nepodařilo se načíst data z backendu.";

export default function WotPage() {
  const resourcesRes = useApiResource<WotResources>("/wot/resources");
  const grindsRes = useApiResource<WotGrind[]>("/wot/grinds");
  const resources = resourcesRes.data ?? {};
  const grinds = grindsRes.data ?? [];

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

  const activeCount = grinds.filter((g) => String(g.status).toLowerCase() === "active").length;
  const remainingTotal = activeXpRemaining(grinds);

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
                <MetricCard key={key} label={RESOURCE_LABELS[key]} value={formatNumber(resources[key])} />
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
                            {GRIND_STATUSES.map((o) => (
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

              {grinds.length === 0 ? (
                <EmptyState
                  action={
                    showGrindForm ? undefined : (
                      <Button size="sm" variant="secondary" onClick={openNewGrind}>
                        Přidat grind
                      </Button>
                    )
                  }
                >
                  Zatím žádné grindy.
                </EmptyState>
              ) : (
                <EntityList label="Grindy tanků">
                  {grinds.map((g, idx) => (
                    <GrindRow
                      key={g.id ?? g.tank}
                      grind={g}
                      index={idx}
                      onEdit={() => editGrind(g)}
                      onDelete={() => setDeletingGrind(g)}
                    />
                  ))}
                </EntityList>
              )}
            </div>
          </PageSection>
        </div>
      )}

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

function GrindRow({
  grind: g,
  index,
  onEdit,
  onDelete,
}: {
  grind: WotGrind;
  index: number;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const priority = priorityTone(g.priority);
  const status = grindStatusMeta(g.status);
  const done = String(g.status).toLowerCase() === "completed";
  return (
    <EntityRow
      searchTarget={g.id != null ? `grind-${g.id}` : undefined}
      style={staggerStyle(index)}
      className="motion-card"
      muted={done}
      badges={
        <>
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          <StatusBadge tone={priority.tone}>Priorita: {priority.label}</StatusBadge>
        </>
      }
      title={g.tank}
      meta={
        <span className="tabular-nums">
          Zbývá <span className="font-medium text-ink">{formatNumber(g.xp_remaining)} XP</span>
        </span>
      }
      actions={
        <>
          <Button size="sm" variant="secondary" onClick={onEdit}>
            Upravit
          </Button>
          <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Smazat grind ${g.tank}`}>
            Smazat
          </Button>
        </>
      }
    >
    </EntityRow>
  );
}
