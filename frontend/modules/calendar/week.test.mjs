import assert from 'node:assert/strict';
import {test} from 'node:test';
import {weekStart,shiftDay,weekPaths,weekDays} from './week.ts';
const item={id:1,key:'one',source_id:1,title:'Synthetic',location:null,status:'active',all_day:false,starts_on:null,ends_on:null,starts_at:'2026-10-25T10:00:00Z',ends_at:'2026-10-25T11:00:00Z'};
test('Monday-first seven local dates and navigation do not shift at DST/year boundaries',()=>{
 assert.equal(weekStart('2026-10-25'),'2026-10-19');
 assert.equal(shiftDay('2026-10-19',7),'2026-10-26');
 assert.equal(shiftDay('2026-10-19',-7),'2026-10-12');
 assert.equal(weekStart('2027-01-01'),'2026-12-28');
 assert.equal(weekDays('2026-10-19',[],[]).length,7);
 assert.throws(()=>weekStart('2026-02-30'));
});
test('two bounded range requests per week, never a query per event/day',()=>{
 assert.deepEqual(weekPaths('2026-10-19'),{occurrences:'/calendar/occurrences?start=2026-10-19&end=2026-10-26',free:'/calendar/free-blocks?start=2026-10-19&end=2026-10-26&min_minutes=30'});
});
test('week retains overlapping instances, all-day exclusive end, and omits historical states',()=>{
 const rows=[item,{...item,id:2,key:'two'}, {...item,id:3,key:'all',all_day:true,starts_on:'2026-10-24',ends_on:'2026-10-26'}, {...item,id:4,status:'cancelled'},{...item,id:5,state:'source_missing'}];
 const days=weekDays('2026-10-19',rows,[{local_date:'2026-10-25',local_start:'12:00',local_end:'13:00',duration_minutes:60}]);
 assert.equal(days[5].events.length,1);assert.equal(days[6].events.length,3);assert.equal(days[6].blocks.length,1);
 assert.equal(weekDays('2026-10-26',rows,[])[0].events.length,0);
});
