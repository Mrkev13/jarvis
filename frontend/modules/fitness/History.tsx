import Link from 'next/link';
import { Card, CardHeader, EmptyState } from '@/components/ui';
import { measurementText, type RehabSession, type Workout } from './lib';

export function WorkoutHistory({workouts}:{workouts:Workout[]}) {
  if (!workouts.length) return <EmptyState>Zatím žádné tréninky.</EmptyState>;
  return <ul className="divide-y divide-line">{workouts.map(workout=><li key={workout.id} className="py-3"><Link href={`/fitness?workout=${workout.id}`} className="text-accent hover:underline">{workout.title || 'Trénink'} · {workout.performed_on}</Link><p className="text-sm text-ink-muted">{workout.sets.length} sérií</p></li>)}</ul>;
}
export function RehabHistory({sessions}:{sessions:RehabSession[]}) {
  if (!sessions.length) return <EmptyState>Zatím žádné rehab záznamy.</EmptyState>;
  return <ul className="divide-y divide-line">{sessions.map(session=><li key={session.id} className="py-3"><Link href={`/fitness?rehab_session=${session.id}`} className="text-accent hover:underline">Rehab · {session.performed_on}</Link><p className="text-sm text-ink-muted">{session.entries.length} položek</p></li>)}</ul>;
}
export function WorkoutDetail({workout}:{workout:Workout}) {
  return <Card><CardHeader title={workout.title || 'Detail tréninku'} /><div id={`workout-${workout.id}`} className="space-y-3 text-sm">
    <p>{workout.performed_on}{workout.duration_minutes != null ? ` · ${workout.duration_minutes} min` : ''}</p>
    {workout.notes?<p className="whitespace-pre-wrap">{workout.notes}</p>:null}
    <ol className="divide-y divide-line">{workout.sets.map((set,index)=><li key={set.id} className="py-3 space-y-1"><p className="font-medium">{index+1}. {set.exercise_name}</p><p>{measurementText(set)}{set.rir!=null?` · RIR ${set.rir}`:''} · {set.completed?'Dokončeno':'Nedokončeno'}</p>{set.notes?<p className="text-ink-muted">{set.notes}</p>:null}</li>)}</ol>
  </div></Card>;
}
export function RehabDetail({session}:{session:RehabSession}) {
  return <Card><CardHeader title="Detail rehab záznamu" /><div id={`rehab_session-${session.id}`} className="space-y-3 text-sm">
    <p>{session.performed_on}</p>{session.notes?<p className="whitespace-pre-wrap">{session.notes}</p>:null}
    <ol className="divide-y divide-line">{session.entries.map((entry,index)=><li key={entry.id} className="py-3 space-y-1"><p className="font-medium">{index+1}. {entry.exercise_name}</p><p>{entry.sets} sérií · {measurementText(entry)}</p>{entry.pain_before!=null || entry.pain_after!=null?<p>Bolest (0–10): {entry.pain_before ?? '—'} → {entry.pain_after ?? '—'}</p>:null}{entry.notes?<p className="text-ink-muted">{entry.notes}</p>:null}</li>)}</ol>
  </div></Card>;
}
