import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildSessionPayload, measurementFields, pragueDate } from './lib.ts';
import { createModuleAccess, manifestFlags } from '../../lib/modules.ts';

const definitions = [{id:1,name:'Synthetic press',type:'strength',active:true},{id:2,name:'Synthetic walk',type:'distance',active:true}];
function row(exercise_id, values) { return {exercise_id:String(exercise_id),values,notes:'',completed:true}; }
test('type fields have explicit units and keep strength/bodyweight/time/distance distinct', () => {
  assert.deepEqual(measurementFields('strength').map(f=>f.key), ['reps','weight_kg']);
  assert.deepEqual(measurementFields('bodyweight').map(f=>f.key), ['reps']);
  assert.deepEqual(measurementFields('duration').map(f=>f.key), ['duration_seconds']);
  assert.deepEqual(measurementFields('distance').map(f=>f.key), ['distance_m','duration_seconds']);
});
test('workout is one atomic, ordered multi-set payload without irrelevant fields', () => {
  const payload = buildSessionPayload(false,'2026-10-09','Synthetic workout','', [row(1,{reps:'8',weight_kg:'20',duration_seconds:'100',rir:'2'}),row(2,{distance_m:'1000',duration_seconds:'600'})],definitions);
  assert.equal(payload.performed_on,'2026-10-09');
  assert.equal(payload.title,'Synthetic workout');
  assert.equal(payload.sets.length,2);
  assert.deepEqual(payload.sets[0],{exercise_id:1,order_index:0,reps:8,weight_kg:20,rir:2,completed:true,notes:null});
  assert.equal(payload.sets[1].distance_m,1000);
  assert.equal(payload.sets[1].order_index,1);
  assert.equal('starts_at' in payload,false);
});
test('rehab accepts multiple entries with sets and optional pain scores, no workout rir', () => {
  const payload = buildSessionPayload(true,'2026-10-09','ignored','note',[row(1,{reps:'10',weight_kg:'0',sets:'2',pain_before:'3',pain_after:'0',rir:'2'})],definitions);
  assert.equal(payload.entries[0].rehab_exercise_id,1);
  assert.equal(payload.entries[0].sets,2);
  assert.equal(payload.entries[0].pain_after,0);
  assert.equal('rir' in payload.entries[0],false);
});
test('empty/invalid/archived input cannot produce payload', () => {
  for (const rows of [[],[row(1,{})],[row(1,{reps:'-1',weight_kg:'20'})],[row(1,{reps:'1.5',weight_kg:'20'})],[row(1,{reps:'8',weight_kg:'20',rir:'11'})],[row(999,{reps:'8'})]]) {
    assert.throws(()=>buildSessionPayload(false,'2026-10-09','','',rows,definitions));
  }
  assert.throws(()=>buildSessionPayload(false,'bad','','',[row(1,{reps:'8',weight_kg:'20'})],definitions));
  assert.throws(()=>buildSessionPayload(false,'2026-10-09','','',[row(1,{reps:'8',weight_kg:'20'})],[{...definitions[0],active:false}]));
});
test('Prague current calendar date handles UTC midnight boundary',()=>{
  assert.equal(pragueDate(new Date('2026-10-08T23:30:00Z')),'2026-10-09');
});
test('disabled Fitness blocks its route and every contribution',()=>{
  const on=createModuleAccess(manifestFlags());
  const off=createModuleAccess({...manifestFlags(),fitness:false});
  assert.equal(on.allowsPath('/fitness'),true);
  assert.equal(off.allowsPath('/fitness'),false);
  for(const type of ['fitness_exercise','fitness_workout','fitness_rehab_exercise','fitness_rehab_session']) {
    for(const capability of ['search','today','ai_context']) assert.equal(off.allowsEntity(type,capability),false);
  }
});

test('payload numeric limits mirror strict backend types and optional measurements',()=>{
 const payload=buildSessionPayload(false,'2026-10-09','','',[row(1,{reps:'0',rir:'2.5'})],definitions);
 assert.equal(payload.sets[0].reps,0);assert.equal(payload.sets[0].rir,2.5);assert.equal(payload.sets[0].weight_kg,undefined);
 const distance=buildSessionPayload(false,'2026-10-09','','',[row(2,{distance_m:'0.05',rir:'9'})],definitions);
 assert.equal(distance.sets[0].distance_m,0.05);assert.equal('rir' in distance.sets[0],false);
 assert.throws(()=>buildSessionPayload(false,'2026-10-09','','',[row(2,{distance_m:'0'})],definitions));
 assert.throws(()=>buildSessionPayload(false,'9999-10-09','','',[row(1,{reps:'8'})],definitions));
 assert.throws(()=>buildSessionPayload(true,'2026-10-09','','',[row(1,{reps:'8',sets:'101'})],definitions));
 assert.throws(()=>buildSessionPayload(true,'2026-10-09','','',[row(1,{reps:'8',sets:'1',pain_before:'-1'})],definitions));
 assert.throws(()=>buildSessionPayload(false,'2026-10-09','','',Array.from({length:201},()=>row(1,{reps:'8'})),definitions));
});
