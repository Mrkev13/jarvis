import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import * as calendar from './lib.ts';
import * as week from './week.ts';
const require=createRequire(import.meta.url);
const ui={Card:({children})=>React.createElement('div',null,children),CardHeader:({title})=>React.createElement('h2',null,title),EmptyState:({children})=>React.createElement('p',null,children),LoadingState:()=>React.createElement('p',null,'loading'),ErrorState:({message})=>React.createElement('p',null,message),Button:({children})=>React.createElement('button',null,children)};
function load(resource) {
 const compiled=ts.transpileModule(readFileSync(new URL('./WeekView.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const mod={exports:{}};
 new Function('require','module','exports',compiled)(name=>name==='@/components/ui'?ui:name==='./lib'?calendar:name==='./week'?week:name==='@/hooks/useApiResource'?{useApiResource:resource}:name==='next/link'?{default:({href,children,...props})=>React.createElement('a',{href,...props},children)}:require(name),mod,mod.exports);
 return mod.exports;
}
const defaults={start:'2026-10-19',events:[],free:[],loading:false,error:null,truncated:false,onRetry:()=>{}};
const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
test('week renders timed/all-day items, stable links, seven days and incomplete warning',()=>{
 const {WeekList}=load();
 const event={id:1,key:'instance',title:'Timed synthetic',location:'Room',status:'active',all_day:false,starts_at:'2026-10-25T10:00:00Z',ends_at:'2026-10-25T11:00:00Z'};
 const html=render(WeekList,{...defaults,truncated:true,events:[event,{...event,id:2,key:'all',title:'All day synthetic',all_day:true,starts_on:'2026-10-24',ends_on:'2026-10-25'}]});
 assert.equal((html.match(/<section /g)||[]).length,7);
 assert.match(html,/Timed synthetic/);assert.match(html,/11:00/);assert.match(html,/Celý den/);assert.match(html,/calendar\?event=2/);assert.match(html,/Neúplný přehled/);assert.match(html,/Možné volno/);
});
test('week loading, error and empty states are explicit',()=>{
 const {WeekList}=load();
 assert.match(render(WeekList,{...defaults,loading:true}),/loading/);
 assert.match(render(WeekList,{...defaults,error:'unavailable'}),/Týden se nepodařilo načíst/);
 assert.match(render(WeekList,defaults),/Žádné události/);
});
test('current week navigation starts Monday and uses only two range resources',()=>{
 const paths=[];
 const {WeekView}=load(path=>{paths.push(path);return {data:{start:'2026-10-19',occurrences:[],blocks:[]},loading:false,error:null,reload:()=>{}};});
 const html=render(WeekView,{today:'2026-10-25'});
 assert.deepEqual(paths,Object.values(week.weekPaths('2026-10-19')));
 assert.match(html,/Předchozí týden/);assert.match(html,/Další týden/);assert.match(html,/2026-10-19 – 2026-10-25/);
});
