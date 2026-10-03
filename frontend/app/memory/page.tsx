"use client";

import { useId, useMemo, useState } from "react";
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
  fieldClass,
  FilterBar,
  FilterSelect,
  FormField,
  HudLabel,
  LoadingState,
  PageHeader,
  PageSection,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { areaMeta } from "@/lib/areas";
import { countActiveFilters } from "@/lib/filters";
import { formatDateTime, plural } from "@/lib/format";
import {
  distinctSorted,
  EMPTY_MEMORY_FILTERS,
  memoryCategoryLabel,
  memoryPayload,
  memoryQuery,
  type MemoryDraft,
  type MemoryFilters,
} from "@/lib/memory";

type MemoryItem = {
  id: number;
  area: string;
  category: string;
  content: string;
  importance: number;
  active: boolean;
  created_at: string | null;
  updated_at: string | null;
};

const EMPTY_DRAFT: MemoryDraft = { area: "general", category: "context", content: "", importance: 5, active: true };

/** Formulář poznámky – stejný pro přidání i úpravu. */
function MemoryForm({
  draft,
  onChange,
  onSubmit,
  onCancel,
  busy,
  error,
  submitLabel,
  areas,
  categories,
}: {
  draft: MemoryDraft;
  onChange: (d: MemoryDraft) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  busy: boolean;
  error: string | null;
  submitLabel: string;
  areas: string[];
  categories: string[];
}) {
  const listId = useId();
  const [contentError, setContentError] = useState<string | null>(null);
  return (
    <form
      className="space-y-4"
      aria-busy={busy}
      onSubmit={(e) => {
        e.preventDefault();
        if (!draft.content.trim()) {
          setContentError("Vyplň obsah poznámky.");
          return;
        }
        setContentError(null);
        onSubmit();
      }}
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <FormField label="Oblast" hint="Vyber ze seznamu, nebo napiš vlastní.">
          {(p) => (
            <>
              <input {...p} list={`${listId}-areas`} value={draft.area} onChange={(e) => onChange({ ...draft, area: e.target.value })} className={fieldClass} />
              <datalist id={`${listId}-areas`}>
                {areas.map((a) => (
                  <option key={a} value={a}>
                    {areaMeta(a).label}
                  </option>
                ))}
              </datalist>
            </>
          )}
        </FormField>
        <FormField label="Kategorie" hint="Vyber ze seznamu, nebo napiš vlastní.">
          {(p) => (
            <>
              <input {...p} list={`${listId}-cats`} value={draft.category} onChange={(e) => onChange({ ...draft, category: e.target.value })} className={fieldClass} />
              <datalist id={`${listId}-cats`}>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {memoryCategoryLabel(c)}
                  </option>
                ))}
              </datalist>
            </>
          )}
        </FormField>
        <FormField label={`Důležitost: ${draft.importance}/10`}>
          {(p) => (
            <input
              {...p}
              type="range"
              min={1}
              max={10}
              value={draft.importance}
              onChange={(e) => onChange({ ...draft, importance: Number(e.target.value) })}
              className="h-10 w-full accent-[var(--color-accent)]"
            />
          )}
        </FormField>
      </div>
      <FormField label="Obsah" error={contentError}>
        {(p) => (
          <textarea {...p} rows={4} value={draft.content} onChange={(e) => onChange({ ...draft, content: e.target.value })} className={`${fieldClass} resize-y`} />
        )}
      </FormField>
      <label className="flex min-h-10 w-fit items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" checked={draft.active} onChange={(e) => onChange({ ...draft, active: e.target.checked })} className="h-4 w-4 accent-[var(--color-accent)]" />
        Aktivní (AI ji používá)
      </label>
      {error ? <ErrorState message={error} /> : null}
      <div className="flex flex-wrap justify-end gap-2">
        {onCancel ? (
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Zrušit
          </Button>
        ) : null}
        <Button type="submit" variant="primary" busy={busy} busyLabel="Ukládám…">
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

export default function MemoryPage() {
  const [filters, setFilters] = useState<MemoryFilters>(EMPTY_MEMORY_FILTERS);
  const qs = memoryQuery(filters);
  const list = useApiResource<MemoryItem[]>(`/memories${qs ? `?${qs}` : ""}`, { debounceMs: 300 });
  // Možnosti filtrů ze všech poznámek (ne jen z aktuálně vyfiltrovaných – výběr by se jinak zúžil sám na sebe).
  const all = useApiResource<MemoryItem[]>("/memories?include_inactive=true");

  const [createDraft, setCreateDraft] = useState<MemoryDraft>(EMPTY_DRAFT);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<MemoryDraft>(EMPTY_DRAFT);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MemoryItem | null>(null);

  const items = useMemo(() => (Array.isArray(list.data) ? list.data : []), [list.data]);
  const source = Array.isArray(all.data) ? all.data : items;
  const areas = useMemo(() => distinctSorted(source.map((m) => m.area)), [source]);
  const categories = useMemo(() => distinctSorted(source.map((m) => m.category)), [source]);
  const active = countActiveFilters({ ...filters });

  async function reloadAll() {
    await Promise.all([list.reload(), all.reload()]);
  }

  async function createMemory() {
    setCreating(true);
    setCreateError(null);
    try {
      await apiJson("/memory", jsonBody("POST", memoryPayload(createDraft)));
      setCreateDraft((d) => ({ ...d, content: "" }));
      await reloadAll();
    } catch (err) {
      setCreateError(errorMessage(err, "Nepodařilo se uložit poznámku."));
    } finally {
      setCreating(false);
    }
  }

  function startEdit(item: MemoryItem) {
    setEditingId(item.id);
    setEditError(null);
    setEditDraft({ area: item.area, category: item.category, content: item.content, importance: item.importance, active: item.active });
  }

  async function saveEdit() {
    if (editingId == null) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      await apiJson(`/memory/${editingId}`, jsonBody("PATCH", memoryPayload(editDraft)));
      setEditingId(null);
      await reloadAll();
    } catch (err) {
      setEditError(errorMessage(err, "Nepodařilo se upravit poznámku."));
    } finally {
      setSavingEdit(false);
    }
  }

  async function toggleActive(item: MemoryItem, next: boolean) {
    setBusyId(item.id);
    setActionError(null);
    try {
      await apiJson(`/memory/${item.id}`, jsonBody("PATCH", { active: next }));
      await reloadAll();
    } catch (err) {
      setActionError(errorMessage(err, "Nepodařilo se změnit stav poznámky."));
    } finally {
      setBusyId(null);
    }
  }

  async function confirmHardDelete() {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await apiJson(`/memory/${deleteTarget.id}/hard`, { method: "DELETE" });
      await reloadAll();
    } catch (err) {
      setActionError(errorMessage(err, "Nepodařilo se smazat poznámku."));
    } finally {
      setDeleteTarget(null);
    }
  }

  return (
    <ContentContainer width="narrow">
      <PageHeader
        eyebrow={<HudLabel>Systém · paměť AI</HudLabel>}
        title="Paměť"
        subtitle="Dlouhodobé poznámky, ze kterých AI vychází – preference, kontext a pravidla. Nejsou to aktuální data z modulů."
        actions={
          <Button size="sm" onClick={() => void reloadAll()} busy={list.refreshing} busyLabel="Obnovuji…" disabled={list.loading}>
            Obnovit
          </Button>
        }
      />

      <FilterBar
        label="Filtry paměti"
        search={{
          value: filters.q,
          onChange: (q) => setFilters((f) => ({ ...f, q })),
          placeholder: "Hledat v obsahu, oblasti nebo kategorii…",
          label: "Hledat v paměti",
        }}
        activeCount={active}
        onReset={() => setFilters(EMPTY_MEMORY_FILTERS)}
        result={list.data ? `${items.length} ${plural(items.length, "poznámka", "poznámky", "poznámek")}` : null}
      >
        <FilterSelect
          label="Oblast"
          value={filters.area}
          onChange={(area) => setFilters((f) => ({ ...f, area }))}
          options={[{ value: "all", label: "Všechny" }, ...areas.map((a) => ({ value: a, label: areaMeta(a).label }))]}
        />
        <FilterSelect
          label="Kategorie"
          value={filters.category}
          onChange={(category) => setFilters((f) => ({ ...f, category }))}
          options={[{ value: "all", label: "Všechny" }, ...categories.map((c) => ({ value: c, label: memoryCategoryLabel(c) }))]}
        />
        <label className="flex min-h-10 items-center gap-2 text-sm text-ink-2">
          <input
            type="checkbox"
            checked={filters.includeInactive}
            onChange={(e) => setFilters((f) => ({ ...f, includeInactive: e.target.checked }))}
            className="h-4 w-4 accent-[var(--color-accent)]"
          />
          Zobrazit i neaktivní
        </label>
      </FilterBar>

      {actionError ? <ErrorState message={actionError} /> : null}

      <PageSection title="Poznámky" labelledBy="memory-list">
        <div aria-busy={list.loading || list.refreshing}>
          {list.error && !list.data ? (
            <ErrorState message={list.error} onRetry={() => void list.reload()} retrying={list.refreshing} />
          ) : list.loading || !list.data ? (
            <LoadingState lines={4} label="Načítám paměť…" />
          ) : items.length === 0 ? (
            <EmptyState
              action={
                active > 0 ? (
                  <Button size="sm" onClick={() => setFilters(EMPTY_MEMORY_FILTERS)}>
                    Zrušit filtry
                  </Button>
                ) : undefined
              }
            >
              {active > 0 ? "Filtrům neodpovídá žádná poznámka." : "Zatím žádné poznámky. Přidej první níže."}
            </EmptyState>
          ) : (
            <EntityList label="Poznámky paměti">
              {items.map((it) => {
                const editing = editingId === it.id;
                return (
                  <EntityRow
                    key={it.id}
                    muted={!it.active}
                    busy={busyId === it.id}
                    badges={
                      <>
                        <AreaBadge area={it.area} />
                        <StatusBadge>{memoryCategoryLabel(it.category)}</StatusBadge>
                        {!it.active ? <StatusBadge>Neaktivní</StatusBadge> : null}
                        <span className="text-xs tabular-nums text-ink-muted">Důležitost {it.importance}/10</span>
                      </>
                    }
                    title={editing ? <span className="sr-only">Úprava poznámky</span> : <span className="whitespace-pre-wrap font-normal leading-relaxed">{it.content}</span>}
                    meta={`Vytvořeno ${formatDateTime(it.created_at)} · upraveno ${formatDateTime(it.updated_at)}`}
                    actions={
                      editing ? null : (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => startEdit(it)}>
                            Upravit
                          </Button>
                          <Button size="sm" variant="ghost" disabled={busyId === it.id} onClick={() => void toggleActive(it, !it.active)}>
                            {it.active ? "Deaktivovat" : "Aktivovat"}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(it)}>
                            Smazat
                          </Button>
                        </>
                      )
                    }
                  >
                    {editing ? (
                      <div className="mt-2">
                        <MemoryForm
                          draft={editDraft}
                          onChange={setEditDraft}
                          onSubmit={() => void saveEdit()}
                          onCancel={() => setEditingId(null)}
                          busy={savingEdit}
                          error={editError}
                          submitLabel="Uložit změny"
                          areas={areas}
                          categories={categories}
                        />
                      </div>
                    ) : null}
                  </EntityRow>
                );
              })}
            </EntityList>
          )}
        </div>
      </PageSection>

      <Card>
        <CardHeader title="Přidat poznámku" description="Krátký fakt nebo preference, kterou má AI dlouhodobě znát." />
        <MemoryForm
          draft={createDraft}
          onChange={setCreateDraft}
          onSubmit={() => void createMemory()}
          busy={creating}
          error={createError}
          submitLabel="Uložit poznámku"
          areas={areas}
          categories={categories}
        />
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Smazat poznámku?"
        message={deleteTarget ? `Poznámka #${deleteTarget.id} se smaže natrvalo. Pokud ji jen nechceš používat, deaktivuj ji.` : ""}
        confirmLabel="Smazat natrvalo"
        cancelLabel="Ponechat"
        danger
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmHardDelete}
      />
    </ContentContainer>
  );
}
