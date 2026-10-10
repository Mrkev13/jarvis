'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Button, Card, CardHeader, ContentContainer, EmptyState, ErrorState, LoadingState, PageHeader, Tabs } from '@/components/ui';
import { useApiResource } from '@/hooks/useApiResource';
import { apiJson, errorMessage, jsonBody } from '@/lib/api';
import { DefinitionForm, DefinitionList, type DefinitionPayload } from './Definitions';
import { RehabDetail, RehabHistory, WorkoutDetail, WorkoutHistory } from './History';
import { SessionForm } from './SessionForm';
import { measurementText, type Definition, type ExerciseProgress, type Progress, type RehabPayload, type RehabSession, type Workout, type WorkoutPayload } from './lib';

type Tab = 'workouts'|'exercises'|'rehab';
function positiveId(value:string|null) { return value && /^[1-9][0-9]*$/.test(value) ? Number(value) : null; }
export default function FitnessPage() {
  const params=useSearchParams();
  const workoutId=positiveId(params.get('workout'));
  const exerciseId=positiveId(params.get('exercise'));
  const rehabId=positiveId(params.get('rehab_session'));
  const rehabExerciseId=positiveId(params.get('rehab_exercise'));
  const linkedTab:Tab=rehabId || rehabExerciseId ? 'rehab' : exerciseId ? 'exercises' : 'workouts';
  const query=params.toString();
  const [chosenTab,setChosenTab]=useState<{tab:Tab;query:string}|null>(null);
  const tab=chosenTab?.query===query ? chosenTab.tab : linkedTab;
  const [creating,setCreating]=useState<'session'|'definition'|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [notice,setNotice]=useState<string|null>(null);
  const progress=useApiResource<Progress>('/fitness/progress');
  const definitions=useApiResource<{exercises:Definition[]}>('/fitness/exercises');
  const rehabDefinitions=useApiResource<{exercises:Definition[]}>('/fitness/rehab/exercises');
  const workouts=useApiResource<{workouts:Workout[]}>(tab==='workouts'?'/fitness/workouts':null);
  const rehabSessions=useApiResource<{sessions:RehabSession[]}>(tab==='rehab'?'/fitness/rehab/sessions':null);
  const selectedWorkout=useApiResource<Workout>(workoutId && tab==='workouts'?`/fitness/workouts/${workoutId}`:null);
  const selectedRehab=useApiResource<RehabSession>(rehabId && tab==='rehab'?`/fitness/rehab/sessions/${rehabId}`:null);
  const exerciseProgress=useApiResource<ExerciseProgress>(exerciseId && tab==='exercises'?`/fitness/exercises/${exerciseId}/progress`:null);
  const resources=[progress,definitions,rehabDefinitions,workouts,rehabSessions,selectedWorkout,selectedRehab,exerciseProgress];
  const failed=resources.find(resource=>resource.error);
  const rehab=tab==='rehab';
  const currentDefinitions=rehab?rehabDefinitions:definitions;
  async function mutate(path:string,method:string,body:unknown) {
    if (busy) return;
    setBusy(true);setError(null);setNotice(null);
    try {
      await apiJson(path,jsonBody(method,body));
      setCreating(null);setNotice('Uloženo.');
      await Promise.all(resources.map(resource=>resource.reload()));
    } catch(e) { setError(errorMessage(e)); } finally {setBusy(false);}
  }
  async function createDefinition(body:DefinitionPayload) {await mutate(rehab?'/fitness/rehab/exercises':'/fitness/exercises','POST',body);}
  async function createSession(body:WorkoutPayload|RehabPayload) {await mutate(rehab?'/fitness/rehab/sessions':'/fitness/workouts','POST',body);}
  function toggle(definition:Definition) {void mutate(`${rehab?'/fitness/rehab/exercises':'/fitness/exercises'}/${definition.id}`,'PATCH',{active:!definition.active});}
  return <ContentContainer>
    <PageHeader title="Fitness & Rehab" subtitle="Záznamy provedených tréninků a rehabilitace." />
    <Tabs id="fitness" label="Fitness a rehabilitace" items={[{value:'workouts',label:'Tréninky'},{value:'exercises',label:'Cviky'},{value:'rehab',label:'Rehab'}]} value={tab} onChange={value=>{setChosenTab({tab:value,query});setCreating(null);setNotice(null);setError(null);}} />
    {notice?<p role="status" className="text-sm text-ink-muted">{notice}</p>:null}
    {error?<ErrorState message={error} />:null}
    {failed?<ErrorState message={failed.error} onRetry={()=>void failed.reload()} />:null}
    {resources.some(resource=>resource.loading)?<LoadingState lines={2} />:null}
    <div id="fitness-panel" role="tabpanel" aria-labelledby={`fitness-${tab}`} className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {tab!=='exercises'?<Button variant="primary" disabled={busy || !currentDefinitions.data} onClick={()=>setCreating('session')}>{rehab?'Zapsat rehab':'Zapsat trénink'}</Button>:null}
        {tab!=='workouts'?<Button variant="secondary" disabled={busy} onClick={()=>setCreating('definition')}>{rehab?'Nový rehab cvik':'Nový cvik'}</Button>:null}
      </div>
      {creating?<Card><CardHeader title={creating==='definition'?'Nový cvik':rehab?'Nový rehab záznam':'Nový trénink'} />{creating==='definition'?<DefinitionForm key={`definition-${tab}`} rehab={rehab} onSave={createDefinition} busy={busy} />:<SessionForm key={`session-${tab}`} rehab={rehab} definitions={currentDefinitions.data?.exercises ?? []} onSave={createSession} busy={busy} />}<div className="mt-3"><Button variant="ghost" disabled={busy} onClick={()=>setCreating(null)}>Zavřít formulář</Button></div></Card>:null}
      {tab==='workouts'?<>
        {progress.data?<Card><CardHeader title="Tento týden" /><p className="text-sm text-ink-muted">Od {progress.data.week_start}: {progress.data.week_workouts} tréninků · {progress.data.week_rehab_sessions} rehab záznamů</p></Card>:null}
        {selectedWorkout.data?<WorkoutDetail workout={selectedWorkout.data} />:null}
        {workouts.data?<Card><CardHeader title="Historie tréninků" /><WorkoutHistory workouts={workouts.data.workouts} /></Card>:null}
      </>:null}
      {tab==='exercises'?<>
        {definitions.data?<Card><CardHeader title="Cviky" /><DefinitionList definitions={definitions.data.exercises} rehab={false} onToggle={toggle} busy={busy} selected={exerciseId} /></Card>:null}
        {exerciseProgress.data?<Card><CardHeader title="Poslední výkon" />{exerciseProgress.data.last_performed_on?<><p className="text-sm">{exerciseProgress.data.last_performed_on}</p><ul className="text-sm text-ink-muted">{exerciseProgress.data.last_sets.map(set=><li key={set.id}>{set.exercise_name} · {measurementText(set)}</li>)}</ul><ul className="space-y-2 text-sm">{exerciseProgress.data.recent_sessions.map(id=><li key={id}><Link className="text-accent hover:underline" href={`/fitness?workout=${id}`}>Trénink #{id}</Link></li>)}</ul></>:<EmptyState>Zatím žádné dokončené série tohoto cviku.</EmptyState>}</Card>:null}
      </>:null}
      {tab==='rehab'?<>
        {selectedRehab.data?<RehabDetail session={selectedRehab.data} />:null}
        {rehabDefinitions.data?<Card><CardHeader title="Rehab cviky" /><DefinitionList definitions={rehabDefinitions.data.exercises} rehab onToggle={toggle} busy={busy} selected={rehabExerciseId} /></Card>:null}
        {rehabSessions.data?<Card><CardHeader title="Historie rehabilitace" /><RehabHistory sessions={rehabSessions.data.sessions} /></Card>:null}
      </>:null}
    </div>
  </ContentContainer>;
}
