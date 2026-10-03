"use client";

import { useMemo, useState } from "react";
import {
  AreaBadge,
  Button,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  FilterBar,
  FilterChips,
  FilterSelect,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  StatGrid,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { formatNumber, formatPercent, plural } from "@/lib/format";
import {
  BUILD_BUCKET_LABELS,
  BUILD_BUCKET_OPTIONS,
  filterAndSortCharacters,
  normalizeCharacters,
  PRIORITY_OPTIONS,
  ROLE_OPTIONS,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  statusMeta,
  type BuildBucket,
  type CharacterPayload,
  type MffCharacterItem,
  type MffSummary,
  type SortId,
} from "@/lib/mff";
import { priorityTone } from "@/lib/ui";
import { CharacterCard } from "./CharacterCard";
import { CharacterForm } from "./CharacterForm";

const FORM_ID = "mff-new-character";
const ALL = { value: "all", label: "Vše" };
const SORT_SELECT = SORT_OPTIONS.map((s) => ({ value: s.id, label: s.label }));
const PRIORITY_SELECT = [ALL, ...PRIORITY_OPTIONS.map((p) => ({ value: p, label: priorityTone(p).label }))];
const STATUS_SELECT = [ALL, ...STATUS_OPTIONS.map((s) => ({ value: s, label: statusMeta(s).label }))];
const BUILD_SELECT = BUILD_BUCKET_OPTIONS.map((b) => ({ value: b, label: BUILD_BUCKET_LABELS[b] }));
const ROLE_CHIPS = ROLE_OPTIONS.map((r) => ({ value: r, label: r }));

export default function MffPage() {
  const summary = useApiResource<MffSummary>("/mff/summary");
  const charsRes = useApiResource<MffCharacterItem[]>("/mff/characters");
  const characters = useMemo(() => normalizeCharacters(charsRes.data ?? []), [charsRes.data]);

  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingChar, setDeletingChar] = useState<MffCharacterItem | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showRoleFilter, setShowRoleFilter] = useState(false);

  const [filterTier, setFilterTier] = useState<string>("all");
  const [filterPriority, setFilterPriority] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterRoles, setFilterRoles] = useState<string[]>([]);
  const [filterBuild, setFilterBuild] = useState<BuildBucket>("all");
  const [sortMode, setSortMode] = useState<SortId>("default");

  const tierSelect = useMemo(() => {
    const tiers = new Set<string>();
    for (const c of characters) if (c.tier) tiers.add(c.tier);
    return [ALL, ...Array.from(tiers).sort().map((t) => ({ value: t, label: t }))];
  }, [characters]);

  const filteredAndSorted = useMemo(
    () =>
      filterAndSortCharacters(characters, {
        tier: filterTier,
        priority: filterPriority,
        status: filterStatus,
        roles: filterRoles,
        build: filterBuild,
        sort: sortMode,
      }),
    [characters, filterTier, filterPriority, filterStatus, filterRoles, filterBuild, sortMode],
  );

  const firstLoad = summary.loading || charsRes.loading;
  const busyLoading = firstLoad || summary.refreshing || charsRes.refreshing;
  const loadError = summary.status === "error" ? summary.error : charsRes.status === "error" ? charsRes.error : null;

  async function loadData() {
    await Promise.all([summary.reload(), charsRes.reload()]);
  }

  function toggleFilterRole(r: string) {
    setFilterRoles((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]));
  }

  async function handleSubmit(payload: CharacterPayload) {
    setSubmitting(true);
    setActionError(null);
    try {
      await apiJson("/mff/character", jsonBody("POST", payload));
      setShowForm(false);
      await loadData();
    } catch (err) {
      setActionError(errorMessage(err, "Nepodařilo se uložit postavu."));
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteChar() {
    if (!deletingChar) return;
    try {
      await apiJson(`/mff/character/${deletingChar.id}`, { method: "DELETE" });
      await loadData();
    } catch {
      setActionError("Nepodařilo se smazat postavu.");
    } finally {
      setDeletingChar(null);
    }
  }

  const s = summary.data;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · Marvel Future Fight</HudLabel>}
        title="Marvel Future Fight"
        subtitle="Sledování postav, CTP, artifactů a plánů vylepšení."
        meta={<AreaBadge area="mff" />}
        actions={
          <Button
            variant={showForm ? "ghost" : "primary"}
            aria-expanded={showForm}
            aria-controls={showForm ? FORM_ID : undefined}
            onClick={() => setShowForm((v) => !v)}
          >
            {showForm ? "Zavřít formulář" : "Přidat postavu"}
          </Button>
        }
      />

      {actionError ? <ErrorState message={actionError} /> : null}
      {loadError ? (
        <ErrorState message={loadError} onRetry={() => void loadData()} retrying={busyLoading} />
      ) : null}

      <PageSection labelledBy="mff-summary" title="Přehled">
        {summary.loading ? (
          <LoadingState lines={2} label="Načítám přehled…" />
        ) : !s ? (
          <EmptyState compact>Přehled se nepodařilo načíst.</EmptyState>
        ) : (
          <StatGrid cols={4}>
            <MetricCard label="Sledované postavy" value={formatNumber(s.tracked_characters ?? 0)} />
            <MetricCard label="T4" value={formatNumber(s.t4_count ?? 0)} />
            <MetricCard label="T3" value={formatNumber(s.t3_count ?? 0)} />
            <MetricCard label="Prioritní buildy" value={formatNumber(s.priority_count ?? 0)} />
            <MetricCard label="Postaveno" value={formatNumber(s.built_count ?? 0)} />
            <MetricCard label="Plně postavené T4" value={formatNumber(s.fully_built_t4_count ?? 0)} />
            <MetricCard label="Průměrný build" value={formatPercent(s.average_build_completeness ?? 0)} />
          </StatGrid>
        )}
      </PageSection>

      {showForm ? (
        <CharacterForm
          id={FORM_ID}
          submitting={submitting}
          disabled={busyLoading}
          onSubmit={(payload) => void handleSubmit(payload)}
          onCancel={() => setShowForm(false)}
        />
      ) : null}

      <PageSection labelledBy="mff-characters" title="Postavy">
        <FilterBar
          label="Filtry a řazení postav"
          result={
            charsRes.loading
              ? undefined
              : `Zobrazeno ${filteredAndSorted.length} z ${characters.length} ${plural(characters.length, "postavy", "postav", "postav")}`
          }
        >
          <FilterSelect label="Řazení" value={sortMode} onChange={(v) => setSortMode(v as SortId)} options={SORT_SELECT} />
          <FilterSelect label="Tier" value={filterTier} onChange={setFilterTier} options={tierSelect} />
          <FilterSelect label="Priorita" value={filterPriority} onChange={setFilterPriority} options={PRIORITY_SELECT} />
          <FilterSelect label="Stav" value={filterStatus} onChange={setFilterStatus} options={STATUS_SELECT} />
          <FilterSelect
            label="Kompletnost buildu"
            value={filterBuild}
            onChange={(v) => setFilterBuild(v as BuildBucket)}
            options={BUILD_SELECT}
          />
          <Button
            size="sm"
            variant="secondary"
            aria-expanded={showRoleFilter}
            aria-controls="mff-role-filter"
            onClick={() => setShowRoleFilter((v) => !v)}
          >
            {showRoleFilter ? "Skrýt filtr rolí" : "Filtr rolí"}
            {filterRoles.length > 0 ? ` (${filterRoles.length})` : ""}
          </Button>
          {showRoleFilter ? (
            <div id="mff-role-filter" className="w-full space-y-1">
              <FilterChips label="Role" options={ROLE_CHIPS} selected={filterRoles} onToggle={toggleFilterRole} />
              <p className="text-xs text-ink-muted">Zobrazí postavy, které mají všechny vybrané role.</p>
            </div>
          ) : null}
        </FilterBar>

        <div aria-busy={charsRes.refreshing}>
          {charsRes.loading ? (
            <LoadingState lines={4} label="Načítám postavy…" />
          ) : charsRes.status === "error" ? null : filteredAndSorted.length === 0 ? (
            characters.length === 0 ? (
              <EmptyState
                action={
                  showForm ? undefined : (
                    <Button variant="secondary" aria-controls={FORM_ID} onClick={() => setShowForm(true)}>
                      Přidat postavu
                    </Button>
                  )
                }
              >
                Zatím žádné sledované postavy.
              </EmptyState>
            ) : (
              <EmptyState>Žádné postavy neodpovídají aktuálním filtrům.</EmptyState>
            )
          ) : (
            <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Sledované postavy">
              {filteredAndSorted.map((c, i) => (
                <CharacterCard key={c.id} character={c} index={i} onDelete={setDeletingChar} />
              ))}
            </ul>
          )}
        </div>
      </PageSection>

      <ConfirmDialog
        open={deletingChar != null}
        title={`Smazat postavu ${deletingChar?.name ?? ""}?`}
        message="Tato akce je nevratná. Postava bude odstraněna ze Standa Hubu."
        confirmLabel="Smazat postavu"
        cancelLabel="Ponechat"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteChar}
        onCancel={() => setDeletingChar(null)}
      />
    </ContentContainer>
  );
}
