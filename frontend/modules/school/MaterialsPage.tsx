'use client';

import { useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  Button, ButtonLink, Card, CardHeader, ContentContainer, EmptyState, EntityList, EntityRow, ErrorState, FilterBar,
  FilterSelect, LoadingState, PageHeader, StatusBadge, buttonClass,
} from '@/components/ui';
import { useApiResource } from '@/hooks/useApiResource';
import { apiJson, apiUrl, errorMessage, jsonBody } from '@/lib/api';
import { MaterialReader } from './MaterialReader';
import {
  STATE_OPTIONS, TYPE_OPTIONS, activeFilterCount, fileState, materialMeta, materialsPath, parseFilters, syncSummary,
  textStatusLabel, typeLabel, type MaterialFilters, type MaterialsPayload, type StudyCourse, type StudyMaterial,
} from './materialsLib';

type MaterialDetail = StudyMaterial & { extracted_chars: number };

function MaterialRow({ m }: { m: StudyMaterial }) {
  const state = fileState(m);
  return <EntityRow searchTarget={`material-${m.id}`} title={m.title} muted={m.state === 'source_missing'}
    badges={<>
      <StatusBadge>{typeLabel(m.material_type)}</StatusBadge>
      <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
    </>}
    meta={materialMeta(m)}
    actions={m.has_file
      ? <a href={apiUrl(`/school/materials/${m.id}/file`)} download className={buttonClass('secondary', 'sm')}>Stáhnout</a>
      : null} />;
}

function CourseMapping({ course, subjects, onSaved }: {
  course: StudyCourse; subjects: MaterialsPayload['subjects']; onSaved: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggestion = subjects.find(s => s.id === course.suggested_subject_id);
  async function save(subjectId: number | null) {
    setBusy(true); setError(null);
    try {
      await apiJson(`/school/materials/courses/${course.id}`, jsonBody('PUT', { subject_id: subjectId }));
      await onSaved();
    } catch (e) {
      setError(errorMessage(e, 'Přiřazení se nepovedlo uložit.'));
    } finally { setBusy(false); }
  }
  return <EntityRow searchTarget={`course-${course.id}`} title={course.name} busy={busy}
    badges={<StatusBadge tone={course.subject ? 'info' : 'neutral'}>{course.subject ? course.subject.name : 'Bez předmětu'}</StatusBadge>}
    meta={[course.short_name, `${course.materials} materiálů`, suggestion && !course.subject ? `návrh: ${suggestion.name}` : null]
      .filter(Boolean).join(' · ')}
    actions={<div className="flex flex-wrap items-end gap-2">
      <FilterSelect label="Předmět" value={course.subject ? String(course.subject.id) : ''}
        onChange={value => void save(value ? Number(value) : null)}
        options={[{ value: '', label: 'Bez předmětu' }, ...subjects.map(s => ({ value: String(s.id), label: s.name }))]} />
      {suggestion && !course.subject
        ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save(suggestion.id)}>Použít návrh</Button> : null}
    </div>}>
    {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
  </EntityRow>;
}

export default function MaterialsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = parseFilters(params);
  const selected = params.get('material');
  const selectedId = selected && /^[1-9][0-9]*$/.test(selected) ? selected : null;
  const materials = useApiResource<MaterialsPayload>(materialsPath(filters));
  const detail = useApiResource<MaterialDetail>(selectedId ? `/school/materials/${selectedId}` : null);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  function setFilters(next: Partial<MaterialFilters>) {
    const merged = { ...filters, ...next };
    const query = new URLSearchParams();
    if (merged.subject) query.set('subject', merged.subject);
    if (merged.course) query.set('course', merged.course);
    if (merged.type) query.set('type', merged.type);
    if (merged.state !== 'active') query.set('state', merged.state);
    router.replace(`${pathname}${query.size ? `?${query}` : ''}`, { scroll: false });
  }

  async function sync() {
    setSyncing(true); setSyncError(null); setNotice(null);
    try {
      setNotice(syncSummary(await apiJson<Record<string, number>>('/school/materials/sync', jsonBody('POST', {}))));
      await materials.reload();
    } catch {
      setSyncError('Synchronizace se nepovedla. Uložené materiály zůstaly beze změny.');
    } finally { setSyncing(false); }
  }

  const data = materials.data;
  const subjectOptions = [{ value: '', label: 'Všechny předměty' }, ...(data?.subjects ?? []).map(s => ({ value: String(s.id), label: s.name }))];
  const selectedDetail = detail.data;
  return <ContentContainer>
    <PageHeader title="Studijní materiály" subtitle="Soubory z kurzů v Moodlu – prezentace, PDF a dokumenty."
      actions={<>
        <ButtonLink href="/school" variant="ghost">Zpět do Školy</ButtonLink>
        <Button variant="secondary" busy={syncing} disabled={!data?.configured} onClick={() => void sync()}>Synchronizovat</Button>
      </>} />
    {notice ? <p role="status" className="text-sm text-ink-muted">{notice}</p> : null}
    {syncError ? <ErrorState message={syncError} /> : null}
    {materials.loading ? <LoadingState lines={4} /> : null}
    {materials.error ? <ErrorState message="Materiály se nepodařilo načíst." onRetry={() => void materials.reload()} /> : null}
    {data ? <>
      {!data.configured ? <EmptyState>Moodle ještě není připojený (nastavuje se jen na serveru). Uložené materiály můžeš dál prohlížet.</EmptyState> : null}
      {selectedDetail ? <Card>
        <CardHeader title="Vybraný materiál" />
        <EntityList label="Vybraný materiál"><MaterialRow m={selectedDetail} /></EntityList>
        <p className="mt-2 text-xs text-ink-muted">Text: {textStatusLabel(selectedDetail.extraction_status, selectedDetail.has_file)}</p>
        <MaterialReader key={selectedDetail.id} materialId={selectedDetail.id} initialQuery={params.get('find')} />
      </Card> : null}
      <FilterBar label="Filtry materiálů" activeCount={activeFilterCount(filters)}
        onReset={() => router.replace(pathname, { scroll: false })}
        result={`${data.materials.length}${data.truncated ? '+' : ''} materiálů`}>
        <FilterSelect label="Předmět" value={filters.subject} onChange={subject => setFilters({ subject })} options={subjectOptions} />
        <FilterSelect label="Typ" value={filters.type} onChange={type => setFilters({ type })} options={TYPE_OPTIONS} />
        <FilterSelect label="Stav" value={filters.state} onChange={state => setFilters({ state: state as MaterialFilters['state'] })} options={STATE_OPTIONS} />
      </FilterBar>
      <Card>
        <CardHeader title="Materiály" icon="school" />
        {data.materials.length
          ? <EntityList label="Studijní materiály">{data.materials.map(m => <MaterialRow key={m.id} m={m} />)}</EntityList>
          : <EmptyState>{activeFilterCount(filters) ? 'Filtrům nic neodpovídá.' : 'Zatím žádné materiály.'}</EmptyState>}
      </Card>
      {data.courses.length ? <Card>
        <CardHeader title="Kurzy a předměty" />
        <p className="mb-3 text-xs text-ink-muted">Kurz se k předmětu přiřazuje jen ručně. Návrh vychází pouze z přesného kódu předmětu.</p>
        <EntityList label="Kurzy z Moodlu">
          {data.courses.map(c => <CourseMapping key={c.id} course={c} subjects={data.subjects} onSaved={materials.reload} />)}
        </EntityList>
      </Card> : null}
    </> : null}
  </ContentContainer>;
}
