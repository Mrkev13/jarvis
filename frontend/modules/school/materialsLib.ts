// MRK-42: studijní materiály z Moodlu – typy a čisté pomocné funkce stránky /school/materials.
// API nikdy nevrací URL Moodlu ani token; frontend zná jen `configured: true/false`.

export type MaterialType = 'pdf' | 'pptx' | 'docx' | 'txt' | 'other';
export type MaterialState = 'active' | 'missing' | 'all';

export interface StudyMaterial {
  id: number;
  title: string;
  file_name: string;
  material_type: MaterialType;
  size_bytes: number | null;
  section_name: string | null;
  source_modified_at: string | null;
  created_at: string;
  updated_at: string;
  source_missing_at: string | null;
  state: 'active' | 'source_missing';
  download_status: 'stored' | 'metadata_only' | 'too_large' | 'unsupported' | 'rejected' | 'failed';
  has_file: boolean;
  extraction_status: string | null;
  course: { id: number; name: string } | null;
  subject: { id: number; name: string } | null;
}

export interface StudyCourse {
  id: number;
  name: string;
  short_name: string | null;
  subject: { id: number; name: string } | null;
  suggested_subject_id: number | null;
  materials: number;
}

export interface MaterialsPayload {
  configured: boolean;
  materials: StudyMaterial[];
  truncated: boolean;
  courses: StudyCourse[];
  subjects: { id: number; name: string }[];
}

export interface MaterialFilters { subject: string; type: string; state: MaterialState; course: string }

export const TYPE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: '', label: 'Všechny typy' }, { value: 'pdf', label: 'PDF' }, { value: 'pptx', label: 'Prezentace' },
  { value: 'docx', label: 'Dokument' }, { value: 'txt', label: 'Text' }, { value: 'other', label: 'Ostatní' },
];

export const STATE_OPTIONS: ReadonlyArray<{ value: MaterialState; label: string }> = [
  { value: 'active', label: 'Aktuální' }, { value: 'missing', label: 'Zmizelé z Moodlu' }, { value: 'all', label: 'Vše' },
];

const TYPE_LABELS: Record<MaterialType, string> = { pdf: 'PDF', pptx: 'Prezentace', docx: 'Dokument', txt: 'Text', other: 'Soubor' };

const ID = /^[1-9][0-9]*$/;

/** Filtry z URL (?subject=&type=&state=&course=) – neplatné hodnoty se tiše zahodí. */
export function parseFilters(params: { get(name: string): string | null }): MaterialFilters {
  const subject = params.get('subject') ?? '';
  const course = params.get('course') ?? '';
  const type = params.get('type') ?? '';
  const state = params.get('state') ?? '';
  return {
    subject: ID.test(subject) ? subject : '',
    course: ID.test(course) ? course : '',
    type: TYPE_OPTIONS.some(o => o.value === type) ? type : '',
    state: STATE_OPTIONS.some(o => o.value === state) ? (state as MaterialState) : 'active',
  };
}

/** API cesta seznamu podle filtrů (jen povolené parametry). */
export function materialsPath(filters: MaterialFilters): string {
  const query = new URLSearchParams();
  if (filters.subject) query.set('subject_id', filters.subject);
  if (filters.course) query.set('course_id', filters.course);
  if (filters.type) query.set('type', filters.type);
  if (filters.state !== 'active') query.set('state', filters.state);
  const text = query.toString();
  return `/school/materials${text ? `?${text}` : ''}`;
}

export function activeFilterCount(filters: MaterialFilters): number {
  return [filters.subject, filters.course, filters.type, filters.state !== 'active' ? filters.state : ''].filter(Boolean).length;
}

export function typeLabel(type: MaterialType): string {
  return TYPE_LABELS[type] ?? 'Soubor';
}

export function formatSize(bytes: number | null): string | null {
  if (bytes == null || bytes < 0) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`;
}

export function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  // naive UTC z backendu → zobrazení v Praze
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString('cs-CZ', { timeZone: 'Europe/Prague', day: 'numeric', month: 'numeric', year: 'numeric' });
}

/** Stav souboru pro štítek: co uživatel s materiálem může udělat. */
export function fileState(m: StudyMaterial): { label: string; tone: 'info' | 'warning' | 'neutral' } {
  if (m.state === 'source_missing') return { label: 'Zmizelo z Moodlu', tone: 'warning' };
  if (m.has_file) return { label: 'Uloženo', tone: 'info' };
  const labels: Record<StudyMaterial['download_status'], string> = {
    stored: 'Soubor chybí', metadata_only: 'Jen metadata', too_large: 'Příliš velký', unsupported: 'Nepodporovaný typ',
    rejected: 'Odmítnuto (neodpovídá typu)', failed: 'Stažení selhalo',
  };
  return { label: labels[m.download_status] ?? 'Jen metadata', tone: m.download_status === 'failed' ? 'warning' : 'neutral' };
}

export function materialMeta(m: StudyMaterial): string {
  return [m.subject?.name ?? m.course?.name, m.section_name, formatSize(m.size_bytes),
    formatDate(m.source_modified_at) ? `změněno ${formatDate(m.source_modified_at)}` : null].filter(Boolean).join(' · ');
}

export function syncSummary(result: Record<string, number>): string {
  const parts = [`nové ${result.created ?? 0}`, `změněné ${result.updated ?? 0}`, `zmizelé ${result.missing ?? 0}`,
    `vrácené ${result.restored ?? 0}`];
  const failed = result.courses_failed ? ` ${result.courses_failed} kurzů se nepodařilo načíst – jejich materiály zůstaly beze změny.` : '';
  return `Materiály: ${parts.join(', ')}.${failed}`;
}
