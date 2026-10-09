// Synthetic browser check: build + start on port 3034; no real backend/LLM.
// PLAYWRIGHT_MODULE and PLAYWRIGHT_CHROMIUM select cloud-installed tools.
import assert from 'node:assert/strict';
import {mkdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {MODULES} from '../lib/modules.ts';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM});
const out=fileURLToPath(new URL('./.ui-check/',import.meta.url));mkdirSync(out,{recursive:true});
const base=process.env.UI_BASE_URL||'http://127.0.0.1:3034';
try {
 for(const width of [1366,390]) {
  const context=await browser.newContext({viewport:{width,height:1000},colorScheme:'dark',hasTouch:width===390});
  const page=await context.newPage(),errors=[],ranges=[];let generation=0,fail=false;
  page.on('pageerror',error=>errors.push(error.message));
  await context.route('http://127.0.0.1:8000/**',async route=>{
   const u=new URL(route.request().url()),start=u.searchParams.get('start'),end=u.searchParams.get('end');
   const response={status:200,contentType:'application/json',headers:{'Access-Control-Allow-Origin':base,'Access-Control-Allow-Credentials':'true'}};
   let body={};
   if(u.pathname==='/modules') body={modules:MODULES.map(m=>({id:m.id,label:m.label,available:m.implemented&&m.defaultEnabled,enabled:m.defaultEnabled,implemented:m.implemented,default_enabled:m.defaultEnabled,source:'default',locked:false,depends_on:[],capabilities:m.capabilities}))};
   else if(u.pathname==='/calendar') body={today:'2026-10-25',events:[],history:[],sources:[],moodle_configured:true};
   else if(u.pathname==='/calendar/sync'){generation++;body={created:1,updated:0,cancelled:0,errors:0};}
   else if(u.pathname==='/calendar/occurrences') {
    ranges.push({start,end,kind:'events'});
    if(fail){await route.fulfill({...response,status:503,body:'{}'});return;}
    body={start,end,truncated:false,occurrences:start==='2026-10-19'?[{id:1,key:'lecture',title:`Synthetic lecture ${generation}`,source_id:1,location:'Room',starts_at:'2026-10-25T10:00:00Z',ends_at:'2026-10-25T11:00:00Z',all_day:false,status:'active',starts_on:null,ends_on:null},{id:2,key:'all',title:'Synthetic all day',source_id:1,location:null,starts_at:'2026-10-24T22:00:00Z',ends_at:'2026-10-25T23:00:00Z',all_day:true,status:'active',starts_on:'2026-10-25',ends_on:'2026-10-26'}]:[]};
   } else if(u.pathname==='/calendar/free-blocks') {
    ranges.push({start,end,kind:'free'});
    body={start,end,truncated:false,blocks:[{starts_at:`${start}T11:00:00Z`,ends_at:`${start}T12:30:00Z`,local_date:start,local_start:'12:00',local_end:'13:30',duration_minutes:90}]};
   } else if(u.pathname==='/timeline/day')body={date:u.searchParams.get('date'),all_day_items:[],timed_items:[],free_blocks:[],free_blocks_from:['calendar'],truncated:false};
   else if(u.pathname==='/events/stream'){await route.fulfill({...response,contentType:'text/event-stream',body:': synthetic\n\n'});return;}
   else if(u.pathname==='/notifications/summary')body={unread_count:0};
   else if(u.pathname==='/auth/session/validate')body={valid:true};
   await route.fulfill({...response,body:JSON.stringify(body)});
  });
  await page.goto(base+'/calendar');
  await page.getByRole('link',{name:'Synthetic lecture 0',exact:true}).waitFor();
  assert.match(await page.locator('body').innerText(),/Celý den/);
  assert.match(await page.locator('body').innerText(),/11:00/);
  assert.equal(ranges.filter(r=>r.start==='2026-10-19'&&r.end==='2026-10-26').length,2);
  await page.getByRole('button',{name:'Synchronizovat',exact:true}).click();
  await page.getByRole('link',{name:'Synthetic lecture 1',exact:true}).waitFor();
  assert.equal(ranges.filter(r=>r.start==='2026-10-19'&&r.end==='2026-10-26').length,4);
  await page.getByRole('button',{name:'Předchozí týden'}).click();
  await page.getByText('2026-10-12 – 2026-10-18',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Další týden'}).click();
  await page.getByRole('link',{name:'Synthetic lecture 1',exact:true}).waitFor();
  await page.getByRole('button',{name:'Další týden'}).click();
  await page.getByText('2026-10-26 – 2026-11-01',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Tento týden'}).click();
  await page.getByRole('link',{name:'Synthetic lecture 1',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:out+`calendar-week-${width}.png`,fullPage:true});
  fail=true;await page.getByRole('button',{name:'Další týden'}).click();
  await page.getByRole('alert').filter({hasText:'Týden se nepodařilo načíst.'}).waitFor();
  fail=false;await page.getByRole('button',{name:'Tento týden'}).click();
  await page.getByRole('link',{name:'Synthetic lecture 1',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log(`${width}px: navigation, all-day/timed, empty/error, sync refresh, no overflow/JS errors passed`);
  await context.close();
 }
}finally{await browser.close();}
