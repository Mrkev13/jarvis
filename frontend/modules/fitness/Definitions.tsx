'use client';
import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { Button, EmptyState, FormField, fieldClass } from '@/components/ui';
import { EXERCISE_TYPES, TYPE_LABELS, type Definition, type ExerciseType } from './lib';
export type DefinitionPayload = { name:string; type:ExerciseType; body_area?:string|null; instructions?:string|null; category?:string; equipment?:string|null; muscle_group?:string|null };
export function DefinitionForm({rehab,onSave,busy}:{rehab:boolean;onSave:(body:DefinitionPayload)=>Promise<void>;busy:boolean}) {
  const [name,setName] = useState('');
  const [type,setType] = useState<ExerciseType>(rehab?'bodyweight':'strength');
  const [category,setCategory] = useState('');
  const [equipment,setEquipment] = useState('');
  const [area,setArea] = useState('');
  const [instructions,setInstructions] = useState('');
  async function submit(e:FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (!name.trim() || busy) return;
    await onSave({name:name.trim(),type,...(rehab ? {body_area:area.trim()||null,instructions:instructions.trim()||null} : {category:category.trim()||'general',equipment:equipment.trim()||null,muscle_group:area.trim()||null})});
  }
  return <form className="space-y-3" onSubmit={e=>void submit(e)}>
    <div className="grid gap-3 sm:grid-cols-2">
      <FormField label="Název cviku">{props=><input {...props} className={fieldClass} value={name} required maxLength={120} onChange={e=>setName(e.target.value)} />}</FormField>
      <FormField label="Typ měření">{props=><select {...props} className={fieldClass} value={type} onChange={e=>setType(e.target.value as ExerciseType)}>{EXERCISE_TYPES.map(value=><option key={value} value={value}>{TYPE_LABELS[value]}</option>)}</select>}</FormField>
      <FormField label={rehab?'Oblast těla (volitelné)':'Svalová skupina (volitelné)'}>{props=><input {...props} className={fieldClass} value={area} maxLength={120} onChange={e=>setArea(e.target.value)} />}</FormField>
      {!rehab?<><FormField label="Kategorie (volitelné)">{props=><input {...props} className={fieldClass} value={category} maxLength={80} onChange={e=>setCategory(e.target.value)} />}</FormField><FormField label="Vybavení (volitelné)">{props=><input {...props} className={fieldClass} value={equipment} maxLength={120} onChange={e=>setEquipment(e.target.value)} />}</FormField></>:<FormField label="Vlastní instrukce (volitelné)">{props=><textarea {...props} className={fieldClass} value={instructions} maxLength={2000} onChange={e=>setInstructions(e.target.value)} />}</FormField>}
    </div>
    <Button type="submit" variant="primary" busy={busy} busyLabel="Ukládám…" disabled={!name.trim()}>Vytvořit {rehab?'rehab cvik':'cvik'}</Button>
  </form>;
}
export function DefinitionList({definitions,rehab,onToggle,busy,selected}:{definitions:Definition[];rehab:boolean;onToggle:(definition:Definition)=>void;busy:boolean;selected?:number|null}) {
  if (!definitions.length) return <EmptyState>Zatím žádné cviky.</EmptyState>;
  return <ul className="divide-y divide-line">{definitions.map(definition=><li key={definition.id} id={`${rehab?'rehab_exercise':'exercise'}-${definition.id}`} className={`py-3 space-y-2 ${selected===definition.id?'rounded-lg bg-accent/10 px-3':''}`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><Link href={`/fitness?${rehab?'rehab_exercise':'exercise'}=${definition.id}`} className="font-medium text-accent hover:underline">{definition.name}</Link><Button size="sm" variant="secondary" busy={busy} onClick={()=>onToggle(definition)}>{definition.active?'Archivovat':'Obnovit'}</Button></div>
    <p className="text-sm text-ink-muted">{TYPE_LABELS[definition.type]}{definition.active?'':' · Archivováno'}{(definition.body_area || definition.muscle_group)?` · ${definition.body_area || definition.muscle_group}`:''}{definition.equipment?` · ${definition.equipment}`:''}</p>
    {definition.instructions?<p className="whitespace-pre-wrap text-sm text-ink-muted">{definition.instructions}</p>:null}
  </li>)}</ul>;
}
