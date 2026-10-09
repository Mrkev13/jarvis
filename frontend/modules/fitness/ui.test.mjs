import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import * as fitness from './lib.ts';
const require = createRequire(import.meta.url);
const ui = Object.fromEntries(['Card','ContentContainer','EmptyState'].map(name=>[name,({children})=>React.createElement('div',null,children)]));
ui.CardHeader = function CardHeader({title}) {return React.createElement('h2',null,title);};
ui.Button = function Button({children,...props}) { delete props.busy; delete props.busyLabel; delete props.variant; return React.createElement('button',props,children);};
ui.FormField = function FormField({label,children}) {return React.createElement('label',null,label,children({}));};
ui.fieldClass='';
function load(file) {
 const compiled=ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const mod={exports:{}};
 new Function('require','module','exports',compiled)(name=>name==='@/components/ui'?ui:name==='./lib'?fitness:name==='next/link'?{default:({href,children,...props})=>React.createElement('a',{href,...props},children)}:require(name),mod,mod.exports);
 return mod.exports;
}
function render(component,props){return renderToStaticMarkup(React.createElement(component,props));}
test('MeasurementInputs renders only relevant type fields and workout RIR / rehab pain with bounds',()=>{
 const {MeasurementInputs}=load('./SessionForm.tsx');
 const props={row:{exercise_id:'1',values:{},completed:true,notes:''},onChange:()=>{}};
 for(const type of fitness.EXERCISE_TYPES){
  const html=render(MeasurementInputs,{...props,type,rehab:false});
  for(const f of fitness.measurementFields(type)) assert.ok(html.includes(f.label));
  if(type!=='strength') assert.doesNotMatch(html,/Zátěž/);
  if(type==='strength'||type==='bodyweight') assert.match(html,/RIR/); else assert.doesNotMatch(html,/RIR/); assert.doesNotMatch(html,/Bolest před/);
 }
 const html=render(MeasurementInputs,{...props,type:'bodyweight',rehab:true});
 assert.match(html,/Počet sérií/); assert.match(html,/Bolest před/); assert.match(html,/Bolest po/); assert.doesNotMatch(html,/RIR/); assert.match(html,/max="10"/);
});
test('SessionForm initial state prevents empty submission and offers active definitions only',()=>{
 const {SessionForm}=load('./SessionForm.tsx');
 const html=render(SessionForm,{rehab:false,definitions:[{id:1,name:'Active synthetic',type:'strength',active:true},{id:2,name:'Archived synthetic',type:'duration',active:false}],onSave:()=>{},busy:false});
 assert.match(html,/Active synthetic/); assert.doesNotMatch(html,/Archived synthetic/); assert.match(html,/Přidat sérii/); assert.match(html,/disabled=""/); assert.match(html,/type="date"/);
});
test('Workout detail preserves all sets, snapshot names, completion and units',()=>{
 const {WorkoutDetail}=load('./History.tsx');
 const html=render(WorkoutDetail,{workout:{id:9,title:'Synthetic session',performed_on:'2026-10-09',notes:'Detail note',duration_minutes:30,sets:[{id:1,exercise_id:3,exercise_name:'Archived press snapshot',exercise_type:'strength',reps:8,weight_kg:20,rir:2,completed:true},{id:2,exercise_id:3,exercise_name:'Archived press snapshot',exercise_type:'strength',reps:6,weight_kg:20,rir:null,completed:false}]}});
 assert.match(html,/Archived press snapshot/);assert.match(html,/8 opakování/); assert.match(html,/20 kg/);assert.match(html,/Nedokončeno/);assert.match(html,/Detail note/);assert.match(html,/30 min/);
});
test('Rehab history and detail use stable links, multiple entries and self-reported pain',()=>{
 const {RehabHistory,RehabDetail}=load('./History.tsx');
 const session={id:12,performed_on:'2026-10-09',notes:'Synthetic rehab',entries:[{id:1,rehab_exercise_id:4,exercise_name:'Synthetic stretch',exercise_type:'duration',duration_seconds:60,sets:2,pain_before:3,pain_after:1,notes:'Entry note'},{id:2,rehab_exercise_id:5,exercise_name:'Synthetic repetition',exercise_type:'bodyweight',reps:10,sets:1,pain_before:null,pain_after:null}]};
 assert.match(render(RehabHistory,{sessions:[session]}),/\/fitness\?rehab_session=12/);
 const html=render(RehabDetail,{session});
 assert.match(html,/Synthetic stretch/);assert.match(html,/Synthetic repetition/);assert.match(html,/60 s/);assert.match(html,/3 → 1/);assert.match(html,/Entry note/);
});

test('Definition create form distinguishes exercise metadata from rehab instructions',()=>{
 const {DefinitionForm}=load('./Definitions.tsx');
 const html=render(DefinitionForm,{rehab:false,onSave:async()=>{},busy:false});
 assert.match(html,/Název cviku/);assert.match(html,/Typ měření/);assert.match(html,/Vybavení/);assert.match(html,/Kategorie/);assert.match(html,/maxLength="120"/i);assert.match(html,/disabled=""/);
 const rehab=render(DefinitionForm,{rehab:true,onSave:async()=>{},busy:false});
 assert.match(rehab,/Oblast těla/);assert.match(rehab,/Vlastní instrukce/);assert.doesNotMatch(rehab,/Vybavení/);
});
test('Definition list includes archive and restore actions and stable exercise links',()=>{
 const {DefinitionList}=load('./Definitions.tsx');
 const definitions=[{id:1,name:'Active synthetic',type:'strength',active:true},{id:2,name:'Archived synthetic',type:'duration',active:false}];
 const html=render(DefinitionList,{definitions,rehab:false,onToggle:()=>{},busy:false,selected:2});
 assert.match(html,/exercise=1/);assert.match(html,/exercise=2/);assert.match(html,/Archivovat/);assert.match(html,/Obnovit/);assert.match(html,/Archivováno/);
 const rehab=render(DefinitionList,{definitions:[{...definitions[1],instructions:'Synthetic personal instructions',body_area:'Synthetic area'}],rehab:true,onToggle:()=>{},busy:false});
 assert.match(rehab,/rehab_exercise=2/);assert.match(rehab,/Synthetic personal instructions/);assert.match(rehab,/Synthetic area/);
});
