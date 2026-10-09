// Synthetic Fitness browser regression/screenshots. Build/start frontend on port3033 first.
// PLAYWRIGHT_MODULE / PLAYWRIGHT_CHROMIUM work as in ui-check.mjs. No backend or LLM needed.
import assert from 'node:assert/strict';
import {mkdirSync} from 'node:fs';
import {MODULES} from '../lib/modules.ts';
import {stubLongRequests} from './network-stubs.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM,args:['--no-sandbox']});
const out=new URL('./.ui-check/',import.meta.url);mkdirSync(out,{recursive:true});
const defs=[{id:1,name:'Testovací dřep',type:'strength',active:true},{id:2,name:'Testovací chůze',type:'distance',active:true}];
const rehab=[{id:1,name:'Testovací rehab cvik',type:'bodyweight',active:true}];
const workout={id:1,performed_on:'2026-10-08',title:'Testovací trénink',notes:null,duration_minutes:30,sets:[{id:1,exercise_id:1,exercise_name:'Testovací dřep',exercise_type:'strength',order_index:0,reps:8,weight_kg:20,duration_seconds:null,distance_m:null,rir:2,completed:true,notes:null}]};
const session={id:1,performed_on:'2026-10-08',notes:null,entries:[{id:1,rehab_exercise_id:1,exercise_name:'Testovací rehab cvik',exercise_type:'bodyweight',order_index:0,reps:10,sets:2,pain_before:1,pain_after:0,notes:null}]};
let saved=null;
for(const width of [1366,390]) {
 const ctx=await browser.newContext({viewport:{width,height:1000},hasTouch:width===390,colorScheme:'dark'});
 await stubLongRequests(ctx);
 await ctx.route('http://127.0.0.1:8000/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  let body={};
  if(path==='/modules')body={modules:MODULES.map(m=>({id:m.id,label:m.label,implemented:m.implemented,enabled:m.defaultEnabled,available:m.defaultEnabled&&m.implemented,default_enabled:m.defaultEnabled,source:'default',locked:false,depends_on:[],capabilities:m.capabilities}))};
  if(path==='/fitness/exercises')body={exercises:defs};
  if(path==='/fitness/rehab/exercises')body={exercises:rehab};
  if(path==='/fitness/workouts') {body={workouts:[workout]};if(route.request().method()==='POST'){saved=route.request().postDataJSON();body=workout;}}
  if(path==='/fitness/workouts/1')body=workout;
  if(path==='/fitness/rehab/sessions')body={sessions:[session]};
  if(path==='/fitness/rehab/sessions/1')body=session;
  if(path==='/fitness/progress')body={week_start:'2026-10-05',week_workouts:1,week_rehab_sessions:1,recent_workouts:[workout],recent_rehab_sessions:[session]};
  if(path==='/notifications/summary')body={unread_count:0};
  await route.fulfill({status:200,json:body,headers:{'Access-Control-Allow-Origin':'http://127.0.0.1:3033','Access-Control-Allow-Credentials':'true'}});
 });
 const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto((process.env.UI_BASE_URL||'http://127.0.0.1:3033')+'/fitness?workout=1');
 await page.getByRole('button',{name:'Zapsat trénink',exact:true}).click();
 await page.getByLabel('Cvik', {exact:true}).selectOption('1');
 await page.getByLabel('Opakování',{exact:true}).fill('8');
 await page.getByLabel('Zátěž (kg)',{exact:true}).fill('20');
 await page.getByRole('button',{name:'Přidat sérii',exact:true}).click();
 await page.getByLabel('Cvik',{exact:true}).nth(1).selectOption('2');
 await page.getByLabel('Vzdálenost (metry)',{exact:true}).fill('500');
 assert.equal(await page.locator('body').evaluate(e=>e.scrollWidth>window.innerWidth),false,'mobile horizontal overflow');
 await page.screenshot({path:new URL(`fitness-${width}.png`,out).pathname,fullPage:true});
 await page.getByRole('button',{name:'Uložit trénink',exact:true}).click();
 await page.getByRole('status').filter({hasText:'Uloženo'}).waitFor();
 assert.equal(saved.sets.length,2);assert.deepEqual(saved.sets.map(s=>s.order_index),[0,1]);assert.equal(saved.sets[1].distance_m,500);assert.equal(saved.sets[1].reps,undefined);
 await page.getByRole('tab',{name:'Rehab',exact:true}).click();
 await page.getByText('Testovací rehab cvik',{exact:true}).first().waitFor();
 await page.getByRole('link',{name:'Rehab · 2026-10-08',exact:true}).click();
 await page.getByText('Detail rehab záznamu',{exact:true}).waitFor();
 await page.getByText('Bolest (0–10): 1 → 0',{exact:true}).waitFor();
 assert.equal(errors.length,0,errors.join('\n'));await ctx.close();
 console.log(`Fitness ${width}px: dynamic fields, atomic payload, rehab/history, overflow and screenshot PASS`);
}
await browser.close();
