'use client';
import { useState, type FormEvent } from 'react';
import { Button, FormField, fieldClass } from '@/components/ui';
import { buildSessionPayload, emptyRow, measurementFields, pragueDate, type Definition, type DraftRow, type ExerciseType, type RehabPayload, type WorkoutPayload } from './lib';

export function MeasurementInputs({ type, rehab, row, onChange }: { type: ExerciseType; rehab: boolean; row: DraftRow; onChange: (row: DraftRow) => void }) {
  const update = (key: keyof DraftRow['values'], value: string) => onChange({ ...row, values: { ...row.values, [key]: value } });
  const extras = rehab ? [
    {key:'sets' as const,label:'Počet sérií',min:1,max:100,step:1,required:true},
    {key:'pain_before' as const,label:'Bolest před (0–10)',min:0,max:10,step:'any' as const,required:false},
    {key:'pain_after' as const,label:'Bolest po (0–10)',min:0,max:10,step:'any' as const,required:false},
  ] : type === 'strength' || type === 'bodyweight' ? [{key:'rir' as const,label:'RIR (0–10)',min:0,max:10,step:'any' as const,required:false}] : [];
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
    {[...measurementFields(type),...extras].map(field => <FormField key={field.key} label={field.label}>{props => <input {...props} className={fieldClass} type="number" min={field.min} max={field.max} step={field.step} required={field.required} value={row.values[field.key] ?? ''} onChange={e => update(field.key,e.target.value)} />}</FormField>)}
  </div>;
}
export function SessionForm({rehab,definitions,onSave,busy}: {rehab:boolean;definitions:Definition[];onSave:(payload:WorkoutPayload|RehabPayload)=>Promise<void>;busy:boolean}) {
  const [date,setDate] = useState(pragueDate);
  const [title,setTitle] = useState('');
  const [notes,setNotes] = useState('');
  const [rows,setRows] = useState<DraftRow[]>([emptyRow()]);
  const active = definitions.filter(d=>d.active);
  let payload: WorkoutPayload|RehabPayload|null = null;
  let validation = '';
  try { payload = buildSessionPayload(rehab,date,title,notes,rows,definitions); } catch(error) { validation = error instanceof Error ? error.message : 'Zkontroluj údaje.'; }
  const updateRow = (index:number,row:DraftRow) => setRows(previous=>previous.map((item,i)=>i===index?row:item));
  async function submit(e:FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!payload || busy) return;
    await onSave(payload);
  }
  return <form onSubmit={e=>void submit(e)} className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2">
      <FormField label="Datum provedení">{props=><input {...props} className={fieldClass} type="date" value={date} max={pragueDate()} required onChange={e=>setDate(e.target.value)} />}</FormField>
      {!rehab?<FormField label="Název tréninku (volitelné)">{props=><input {...props} className={fieldClass} maxLength={200} value={title} onChange={e=>setTitle(e.target.value)} />}</FormField>:null}
    </div>
    <FormField label="Poznámka (volitelné)">{props=><textarea {...props} className={fieldClass} maxLength={2000} value={notes} onChange={e=>setNotes(e.target.value)} />}</FormField>
    {rows.map((row,index)=>{
      const definition = active.find(d=>String(d.id)===row.exercise_id);
      return <fieldset key={index} className="space-y-3 rounded-lg border border-line p-3" disabled={busy}>
        <legend className="px-1 text-sm font-medium">{rehab?'Položka':'Série'} {index+1}</legend>
        <FormField label="Cvik">{props=><select {...props} className={fieldClass} required value={row.exercise_id} onChange={e=>updateRow(index,{...emptyRow(),exercise_id:e.target.value})}><option value="">Vyber cvik</option>{active.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select>}</FormField>
        {definition?<MeasurementInputs type={definition.type} rehab={rehab} row={row} onChange={value=>updateRow(index,value)} />:null}
        {!rehab?<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={row.completed} onChange={e=>updateRow(index,{...row,completed:e.target.checked})} />Dokončeno</label>:null}
        <FormField label="Poznámka k položce (volitelné)">{props=><input {...props} className={fieldClass} maxLength={500} value={row.notes} onChange={e=>updateRow(index,{...row,notes:e.target.value})} />}</FormField>
        {rows.length>1?<Button variant="ghost" size="sm" onClick={()=>setRows(previous=>previous.filter((_,i)=>i!==index))}>Odebrat {rehab?'položku':'sérii'} {index+1}</Button>:null}
      </fieldset>;
    })}
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" disabled={busy || rows.length>=200 || !active.length} onClick={()=>setRows(previous=>[...previous,emptyRow()])}>{rehab?'Přidat položku':'Přidat sérii'}</Button>
      <Button type="submit" variant="primary" busy={busy} busyLabel="Ukládám…" disabled={!payload}>{rehab?'Uložit rehab záznam':'Uložit trénink'}</Button>
    </div>
    {validation?<p className="text-sm text-ink-muted">{validation}</p>:null}
    {!active.length?<p className="text-sm text-ink-muted">Nejprve vytvoř aktivní cvik.</p>:null}
  </form>;
}
