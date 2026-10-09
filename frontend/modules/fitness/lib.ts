export const EXERCISE_TYPES = ['strength', 'bodyweight', 'duration', 'distance'] as const;
export type ExerciseType = typeof EXERCISE_TYPES[number];
export const TYPE_LABELS: Record<ExerciseType, string> = { strength: 'Síla', bodyweight: 'Vlastní váha', duration: 'Čas', distance: 'Vzdálenost' };
export interface Definition {
  id: number; name: string; type: ExerciseType; active: boolean;
  category?: string | null; equipment?: string | null; muscle_group?: string | null;
  body_area?: string | null; instructions?: string | null;
}
export type MeasureKey = 'reps' | 'weight_kg' | 'duration_seconds' | 'distance_m';
export interface MeasurementField { key: MeasureKey; label: string; min: number; max: number; step: number | 'any'; required: boolean }
const FIELDS: Record<MeasureKey, MeasurementField> = {
  reps: { key: 'reps', label: 'Opakování', min: 0, max: 10000, step: 1, required: true },
  weight_kg: { key: 'weight_kg', label: 'Zátěž (kg)', min: 0, max: 10000, step: 'any', required: false },
  duration_seconds: { key: 'duration_seconds', label: 'Čas (sekundy)', min: 1, max: 604800, step: 1, required: true },
  distance_m: { key: 'distance_m', label: 'Vzdálenost (metry)', min: 0, max: 10000000, step: 'any', required: true },
};
export function measurementFields(type: ExerciseType): MeasurementField[] {
  if (type === 'strength') return [FIELDS.reps, FIELDS.weight_kg];
  if (type === 'bodyweight') return [FIELDS.reps];
  if (type === 'duration') return [FIELDS.duration_seconds];
  return [FIELDS.distance_m, { ...FIELDS.duration_seconds, required: false }];
}
export interface DraftRow { exercise_id: string; values: Partial<Record<MeasureKey | 'rir' | 'sets' | 'pain_before' | 'pain_after', string>>; completed: boolean; notes: string }
export function emptyRow(): DraftRow { return { exercise_id: '', values: { sets: '1' }, completed: true, notes: '' }; }
export interface Measurements { reps?: number | null; weight_kg?: number | null; duration_seconds?: number | null; distance_m?: number | null }
export interface WorkoutSet extends Measurements { id: number; exercise_id: number; exercise_name: string; exercise_type: ExerciseType; order_index: number; rir: number | null; completed: boolean; notes: string | null }
export interface RehabEntry extends Measurements { id: number; rehab_exercise_id: number; exercise_name: string; exercise_type: ExerciseType; order_index: number; sets: number; pain_before: number | null; pain_after: number | null; notes: string | null }
export interface Workout { id: number; performed_on: string; title: string | null; notes: string | null; duration_minutes: number | null; sets: WorkoutSet[] }
export interface RehabSession { id: number; performed_on: string; notes: string | null; entries: RehabEntry[] }
export interface Progress { week_start: string; week_workouts: number; week_rehab_sessions: number; recent_workouts: Workout[]; recent_rehab_sessions: RehabSession[] }
export interface ExerciseProgress { exercise_id: number; last_performed_on: string | null; last_sets: WorkoutSet[]; recent_sessions: number[] }
function numeric(raw: string | undefined, min: number, max: number, integer = false, required = false): number | undefined {
  if (!raw?.trim()) { if (required) throw new Error('Vyplň povinné hodnoty.'); return undefined; }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) throw new Error('Hodnota je mimo povolený rozsah.');
  return value;
}
export function pragueDate(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Prague', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const part = (name: string) => parts.find(p => p.type === name)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export interface SetPayload extends Measurements { exercise_id: number; order_index: number; rir?: number; completed: boolean; notes: string | null }
export interface EntryPayload extends Measurements { rehab_exercise_id: number; order_index: number; sets: number; pain_before?: number; pain_after?: number; notes: string | null }
export interface WorkoutPayload { performed_on: string; title: string | null; notes: string | null; sets: SetPayload[] }
export interface RehabPayload { performed_on: string; notes: string | null; entries: EntryPayload[] }
export function buildSessionPayload(rehab: false, date: string, title: string, notes: string, rows: DraftRow[], definitions: Definition[]): WorkoutPayload;
export function buildSessionPayload(rehab: true, date: string, title: string, notes: string, rows: DraftRow[], definitions: Definition[]): RehabPayload;
export function buildSessionPayload(rehab: boolean, date: string, title: string, notes: string, rows: DraftRow[], definitions: Definition[]): WorkoutPayload | RehabPayload;
export function buildSessionPayload(rehab: boolean, date: string, title: string, notes: string, rows: DraftRow[], definitions: Definition[]): WorkoutPayload | RehabPayload {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(`${date}T12:00:00Z`)) || new Date(`${date}T12:00:00Z`).toISOString().slice(0,10) !== date) throw new Error('Vyber platné datum provedení.');
  if (date > pragueDate()) throw new Error('Datum provedení nemůže být v budoucnosti.');
  if (title.length > 200 || notes.length > 2000 || rows.some(row => row.notes.length > 500)) throw new Error('Poznámka nebo název je příliš dlouhý.');
  if (!rows.length || rows.length > 200) throw new Error('Přidej alespoň jednu položku.');
  const entries = rows.map((row, order_index) => {
    const definition = definitions.find(d => d.id === Number(row.exercise_id) && d.active);
    if (!definition) throw new Error('Vyber aktivní cvik.');
    const measurements: Measurements = {};
    for (const field of measurementFields(definition.type)) {
      const value = numeric(row.values[field.key], field.min, field.max, field.step === 1, field.required);
      if (field.key === 'distance_m' && value !== undefined && value <= 0) throw new Error('Vzdálenost musí být větší než nula.');
      if (value !== undefined) measurements[field.key] = value;
    }
    const base = { ...measurements, order_index, notes: row.notes.trim() || null };
    return rehab ? { ...base, rehab_exercise_id: definition.id, sets: numeric(row.values.sets, 1, 100, true, true)!, pain_before: numeric(row.values.pain_before,0,10), pain_after: numeric(row.values.pain_after,0,10) }
      : { ...base, exercise_id: definition.id, completed: row.completed, ...((definition.type === 'strength' || definition.type === 'bodyweight') ? { rir: numeric(row.values.rir,0,10) } : {}) };
  });
  return rehab ? { performed_on: date, notes: notes.trim() || null, entries: entries as EntryPayload[] }
    : { performed_on: date, title: title.trim() || null, notes: notes.trim() || null, sets: entries as SetPayload[] };
}
export function measurementText(row: Measurements): string {
  return [row.reps != null ? `${row.reps} opakování` : '', row.weight_kg != null ? `${row.weight_kg} kg` : '', row.duration_seconds != null ? `${row.duration_seconds} s` : '', row.distance_m != null ? `${row.distance_m} m` : ''].filter(Boolean).join(' · ');
}
