'use client';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {Button,Card,CardHeader,EmptyState,ErrorState,LoadingState} from '@/components/ui';
import {useApiResource} from '@/hooks/useApiResource';
import {eventTime,freeBlockLabel,type CalendarEvent,type FreeBlocksPayload} from './lib';
import {shiftDay,weekDays,weekPaths,weekStart,type OccurrencesPayload} from './week';

export function WeekList({start,events,free,loading,error,truncated,onRetry}:{start:string;events:CalendarEvent[];free:FreeBlocksPayload['blocks'];loading:boolean;error:string|null;truncated:boolean;onRetry:()=>void}) {
 if(loading) return <LoadingState lines={4} />;
 if(error) return <ErrorState message="Týden se nepodařilo načíst." onRetry={onRetry} />;
 return <>
  <p className="mb-3 text-sm text-ink-muted">Volno podle Kalendáře: 07–22, alespoň 30 min. Celodenní položky čas neblokují. Školní termíny jsou v části Můj den.</p>
  {truncated?<p role="status" className="mb-3 text-sm text-warning">Neúplný přehled: příliš mnoho událostí. Volno neber jako jisté.</p>:null}
  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{weekDays(start,events,free).map(day=><section key={day.day} aria-label={day.label} className="min-w-0 rounded-lg border border-line p-3">
    <h3 className="mb-2 font-medium">{day.label}</h3>
    {!day.events.length?<EmptyState>Žádné události.</EmptyState>:<ul className="space-y-3">{day.events.map(event=><li key={event.key||String(event.id)} className="min-w-0 text-sm"><Link className="break-words text-accent hover:underline" href={`/calendar?event=${event.id}`}>{event.title}</Link><p className="text-xs text-ink-muted">{eventTime(event)}</p>{event.location?<p className="break-words text-xs text-ink-muted">{event.location}</p>:null}</li>)}</ul>}
    <div className="mt-3 border-t border-line pt-2 text-xs text-ink-muted"><p>{truncated?'Možné volno (neúplné)':'Volno'}</p>{day.blocks.length?<ul className="mt-1 space-y-1">{day.blocks.map(block=><li key={block.starts_at}>{freeBlockLabel(block)}</li>)}</ul>:<p>Žádný blok alespoň 30 min.</p>}</div>
  </section>)}</div>
 </>;
}

export function WeekView({today,refresh=0}:{today:string;refresh?:number}) {
 const [start,setStart]=useState(()=>weekStart(today));
 const paths=weekPaths(start);
 const occurrences=useApiResource<OccurrencesPayload>(paths.occurrences);
 const blocks=useApiResource<FreeBlocksPayload>(paths.free);
 const reloadOccurrences=occurrences.reload, reloadBlocks=blocks.reload;
 const refreshed=useRef(refresh);
 useEffect(()=>{if(refresh!==refreshed.current){refreshed.current=refresh;void reloadOccurrences();void reloadBlocks();}},[refresh,reloadOccurrences,reloadBlocks]);
 const current=occurrences.data?.start===start?occurrences.data:null;
 const currentBlocks=blocks.data?.start===start?blocks.data:null;
 return <Card><CardHeader title="Týden" />
  <div className="mb-3 flex flex-wrap items-center gap-2"><Button variant="secondary" size="sm" onClick={()=>setStart(day=>shiftDay(day,-7))}>Předchozí týden</Button><Button variant="ghost" size="sm" onClick={()=>setStart(weekStart(today))}>Tento týden</Button><Button variant="secondary" size="sm" onClick={()=>setStart(day=>shiftDay(day,7))}>Další týden</Button><span className="text-sm text-ink-muted">{start} – {shiftDay(start,6)}</span></div>
  <WeekList start={start} events={current?.occurrences??[]} free={currentBlocks?.blocks??[]} loading={occurrences.loading||blocks.loading||(!current&&!occurrences.error)||(!currentBlocks&&!blocks.error)} error={occurrences.error||blocks.error} truncated={Boolean(current?.truncated||currentBlocks?.truncated)} onRetry={()=>{void occurrences.reload();void blocks.reload();}} />
 </Card>;
}
