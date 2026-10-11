import {groupEvents, type CalendarEvent, type FreeBlock} from './lib.ts';
export interface OccurrencesPayload {start:string;end:string;occurrences:CalendarEvent[];truncated?:boolean}
export function shiftDay(day:string,offset:number):string {
  const value=new Date(`${day}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(value.getTime()) || value.toISOString().slice(0,10)!==day) throw new Error('Invalid local date');
  value.setUTCDate(value.getUTCDate()+offset);
  return value.toISOString().slice(0,10);
}
export function weekStart(day:string):string {
  shiftDay(day,0);
  const weekday=new Date(`${day}T00:00:00Z`).getUTCDay();
  return shiftDay(day,-((weekday+6)%7));
}
export function weekPaths(start:string) {
  const end=shiftDay(start,7);
  return {occurrences:`/calendar/occurrences?start=${start}&end=${end}`,free:`/calendar/free-blocks?start=${start}&end=${end}&min_minutes=30`};
}
export function weekDays(start:string,events:CalendarEvent[],blocks:FreeBlock[]) {
  return Array.from({length:7},(_,offset)=>{
    const day=shiftDay(start,offset);
    return {day,label:new Intl.DateTimeFormat('cs-CZ',{weekday:'short',day:'numeric',month:'numeric',timeZone:'UTC'}).format(new Date(`${day}T00:00:00Z`)),events:groupEvents(events,day).today,blocks:blocks.filter(b=>b.local_date===day)};
  });
}
