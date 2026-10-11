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

// ---------- MRK-56: ruční import ZIPu „Stáhnout obsah kurzu" (POST /school/materials/import-zip) ----------

export const ZIP_IMPORT_PATH = '/school/materials/import-zip';

/** Jen soubor s příponou .zip a nenulovou velikostí (MIME typ prohlížeče u ZIPu nebývá spolehlivý). */
export function isZipFile(file: { name: string; size: number }): boolean {
  return /\.zip$/i.test(file.name) && file.size > 0;
}

// Backend vrací jen kategorii chyby; text pro člověka je tady (nikdy surové tělo odpovědi).
const IMPORT_ERRORS: Record<string, string> = {
  archive_invalid: 'Soubor není platný ZIP.',
  archive_too_large: 'ZIP je příliš velký.',
  unsupported_media_type: 'Soubor není ZIP.',
  not_course_export: 'Tohle nevypadá jako export kurzu z Moodle („Stáhnout obsah kurzu“).',
  unsafe_path: 'ZIP obsahuje nebezpečné cesty k souborům – import byl odmítnut.',
  symlink_entry: 'ZIP obsahuje odkazy na jiné soubory – import byl odmítnut.',
  encrypted_entry: 'ZIP obsahuje šifrované soubory – import byl odmítnut.',
  duplicate_entry: 'ZIP obsahuje duplicitní soubory – import byl odmítnut.',
  too_many_entries: 'ZIP obsahuje příliš mnoho souborů.',
  uncompressed_too_large: 'Rozbalený obsah ZIPu je příliš velký.',
  compression_ratio: 'ZIP má podezřele vysoký kompresní poměr – import byl odmítnut.',
  import_failed: 'Import se nepovedl. Uložené materiály zůstaly beze změny.',
};
const IMPORT_GENERIC = 'Import se nepovedl. Uložené materiály zůstaly beze změny.';

export function importErrorMessage(category: unknown): string {
  return typeof category === 'string' && Object.hasOwn(IMPORT_ERRORS, category) ? IMPORT_ERRORS[category] : IMPORT_GENERIC;
}

export function importSummary(result: Record<string, unknown>): string {
  const n = (key: string) => (typeof result[key] === 'number' ? (result[key] as number) : 0);
  const extra = [
    n('file_unsupported') ? `nepodporované soubory ${n('file_unsupported')}` : null,
    n('files_listed_missing') ? `v ZIPu chybí ${n('files_listed_missing')}` : null,
  ].filter(Boolean);
  return `Import hotový: nové ${n('created')}, změněné ${n('updated')}, beze změny ${n('unchanged')}`
    + (extra.length ? ` (${extra.join(', ')})` : '') + '.';
}

export type ImportOutcome = { ok: true; summary: string } | { ok: false; message: string };
type Fetcher = (path: string, init: RequestInit) => Promise<Response>;

/** Pošle ZIP jako tělo požadavku. Vrací jen bezpečný český text – nikdy tělo chyby ze serveru. */
export async function uploadMoodleZip(file: Blob & { name: string; size: number }, fetcher: Fetcher): Promise<ImportOutcome> {
  if (!isZipFile(file)) return { ok: false, message: 'Vyber soubor .zip stažený z Moodle („Stáhnout obsah kurzu“).' };
  let res: Response;
  try {
    res = await fetcher(ZIP_IMPORT_PATH, { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file });
  } catch {
    return { ok: false, message: 'Import se nepovedl – server je nedostupný. Uložené materiály zůstaly beze změny.' };
  }
  if (res.ok) {
    try {
      return { ok: true, summary: importSummary((await res.json()) as Record<string, unknown>) };
    } catch {
      return { ok: true, summary: 'Import hotový.' };
    }
  }
  let category: unknown = null;
  try {
    const body = (await res.json()) as { detail?: { category?: unknown } };
    category = body?.detail?.category;
  } catch {
    // ne-JSON tělo (proxy/HTML) – obecná hláška
  }
  return { ok: false, message: importErrorMessage(category) };
}

// ---------- MRK-44: cílené čtení jednoho materiálu (GET /school/materials/{id}/content) ----------

export type TextStatus = 'available' | 'empty' | 'failed' | 'unsupported' | 'not_downloaded';
export interface ContentLocation { kind: 'page' | 'slide'; from: number; to: number }
export interface ContentChunk {
  index: number;
  text: string;
  location: ContentLocation | null;
  score?: number;
  matched_terms?: string[];
}
export interface MaterialContent {
  material: { id: number; title: string; state: 'active' | 'source_missing' };
  text_status: TextStatus;
  text_message: string;
  extraction_truncated: boolean;
  query: string | null;
  query_terms: string[];
  chunks: ContentChunk[];
  total_chunks: number;
  matched_chunks: number;
  returned_chars: number;
  truncated: boolean;
  outline?: { kind: 'page' | 'slide'; number: number; label: string }[];
}

export const MAX_FIND_CHARS = 200;

/** API cesta čtení: id jen jako kladné celé číslo, dotaz oříznutý na limit serveru. */
export function contentPath(materialId: number | string, query?: string | null): string | null {
  const id = String(materialId);
  if (!/^[1-9][0-9]*$/.test(id)) return null;
  const q = (query ?? '').trim().slice(0, MAX_FIND_CHARS);
  return `/school/materials/${id}/content${q ? `?${new URLSearchParams({ q })}` : ''}`;
}

export function locationLabel(location: ContentLocation | null): string | null {
  if (!location) return null;
  const word = location.kind === 'slide' ? 'Snímek' : 'Strana';
  return location.from === location.to ? `${word} ${location.from}` : `${word} ${location.from}–${location.to}`;
}

/** Krátké shrnutí výsledku čtení pro čtečku i uživatele. */
export function contentSummary(c: MaterialContent): string {
  if (c.text_status !== 'available') return c.text_message;
  if (c.query) {
    if (!c.matched_chunks) return `„${c.query}“ se v materiálu nenašlo.`;
    return `Nalezeno ${c.matched_chunks} ${c.matched_chunks === 1 ? 'místo' : c.matched_chunks < 5 ? 'místa' : 'míst'}, zobrazeno ${c.chunks.length}.`;
  }
  return c.truncated ? `Začátek materiálu (${c.chunks.length} z ${c.total_chunks} částí).` : 'Celý text materiálu.';
}

/** Stav extrakce v řádku vybraného materiálu (pro lidi; čtení samo vrací přesný `text_status`). */
export function textStatusLabel(extraction: string | null, hasFile: boolean): string {
  const labels: Record<string, string> = {
    ok: 'získán', truncated: 'získán (zkrácený na limit)', empty: 'bez textové vrstvy (sken)', failed: 'nepodařilo se získat',
    unsupported: 'typ se nečte',
  };
  return extraction ? labels[extraction] ?? extraction : hasFile ? 'zatím nezpracován' : 'není k dispozici (soubor neuložen)';
}
