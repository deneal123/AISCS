// Real author interface in isolated Edge. Caretaker sockets and external HTTP are blocked.
import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const base=process.env.ASPA_SNEDEA_URL,out=process.env.ASPA_SNEDEA_OUTPUT;
const require=createRequire(path.join(process.env.ASPA_SNEDEA_TOOLS,'package.json'));
const {chromium}=require('playwright');
await mkdir(out,{recursive:true});
const context=await chromium.launchPersistentContext(process.env.ASPA_SNEDEA_PROFILE,{executablePath:process.env.ASPA_SNEDEA_EDGE,headless:true,viewport:{width:1600,height:1000},args:['--disable-background-networking','--disable-sync','--no-first-run']});
const record={scope:'actual author browser UI; no caretaker/LLM backend',screenshots:[],page_errors:[],console_errors:[],network_failures:[],status:'failed'};
const page=await context.newPage();
await context.route('**/*',route=>route.request().url().startsWith(base+'/') ? route.continue() : route.abort());
await context.routeWebSocket('**/*',ws=>ws.close({code:1000,reason:'isolated local review; caretaker disabled'}));
await context.addInitScript(()=>{
 let seed=1;Math.random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
 window.__reviewWorkerTicks=0;
 const NativeWorker=window.Worker;
 window.Worker=class extends NativeWorker{
  constructor(...args){super(...args);this.addEventListener('message',event=>{if(event.data?.type==='tick')window.__reviewWorkerTicks++;});}
 };
});
page.on('pageerror',e=>record.page_errors.push(String(e)));
page.on('console',m=>{if(m.type()==='error')record.console_errors.push(m.text());});
page.on('requestfailed',r=>record.network_failures.push({url:r.url(),error:r.failure()?.errorText}));
const state=()=>page.evaluate(()=>({ready:BRAIN.workerReady,neurons:BRAIN.workerNeuronCount,fired:BRAIN.workerFiredNeurons,fire_state_length:BRAIN.latestFireState?.length,behavior:behavior.current,position:{x:fly.x,y:fly.y},food:food.length,light:lightStateIndex,temperature:tempStateIndex,stimulate:JSON.parse(JSON.stringify(BRAIN.stimulate))}));
const shot=async name=>{await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});record.screenshots.push(name+'.png');};
try{
 await page.goto(base+'/',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>window.BRAIN?.workerReady===true,null,{timeout:90000});
 await page.waitForFunction(()=>window.BRAIN?.latestFireState?.length===139255,null,{timeout:30000});
 record.initial=await state();assert.equal(record.initial.neurons,139255);
 await shot('browser-full-connectome');
 await page.locator('[data-tool="feed"]').click();await page.mouse.click(1100,450);
 await page.waitForFunction(()=>food.length>0,null,{timeout:5000});record.food_added=await state();
 await page.locator('#lightBtn').click();await page.locator('#tempBtn').click();
 record.environment=await state();assert.equal(record.environment.light,1);assert.equal(record.environment.temperature,1);
 await shot('browser-environment-controls');
 await page.locator('[data-tool="air"]').click();
 await page.mouse.move(1000,400);await page.mouse.down();await page.mouse.move(1120,450,{steps:4});await page.mouse.up();
 record.after_air=await state();
 await page.locator('[data-tool="touch"]').click();
 const point=await page.evaluate(()=>({x:fly.x,y:fly.y}));
 for(let i=0;i<3;i++)await page.mouse.click(point.x,point.y,{delay:50});
 await page.waitForTimeout(1500);record.after_touch=await state();await shot('browser-touch-state');
 await page.locator('#clearButton').click();assert.equal((await state()).food,0);
 await page.evaluate(()=>BRAIN.stopWorker());await page.waitForTimeout(500);
 const stoppedAt=await page.evaluate(()=>window.__reviewWorkerTicks);
 await page.waitForTimeout(500);
 const stillAt=await page.evaluate(()=>window.__reviewWorkerTicks);
 record.pause_observation={settled_message_count:stoppedAt,after_500ms:stillAt,last_frame_retained:await page.evaluate(()=>BRAIN.latestFireState!==null)};
 record.paused=stoppedAt===stillAt;assert(record.paused);
 await page.evaluate(()=>BRAIN.startWorker());await page.waitForFunction(count=>window.__reviewWorkerTicks>count,stillAt,{timeout:10000});
 record.resumed=true;
 await page.locator('#brain3dBtn').click();await page.waitForTimeout(1200);
 record.brain3d_pressed=await page.locator('#brain3dBtn').getAttribute('aria-pressed');
 await shot('browser-brain3d');
 assert.equal(record.brain3d_pressed,'true');
 record.final=await state();assert.equal(record.page_errors.length,0);
 await page.locator('#brain3dBtn').click();await page.locator('#centerButton').click();
 for(let i=0;i<3;i++)await page.locator('#zoomIn').click();
 await shot('browser-body-zoom');
 const svg=await readFile(process.env.ASPA_SNEDEA_SVG,'utf8');
 const graph=await context.newPage();await graph.setViewportSize({width:1120,height:510});await graph.setContent(svg);
 await graph.screenshot({path:path.join(out,'recorded-events.png')});record.screenshots.push('recorded-events.png');await graph.close();
 if(process.env.ASPA_SNEDEA_PROPAGATION_SVG){
  const propagation=await context.newPage();await propagation.setViewportSize({width:1120,height:610});
  await propagation.setContent(await readFile(process.env.ASPA_SNEDEA_PROPAGATION_SVG,'utf8'));
  await propagation.screenshot({path:path.join(out,'recorded-propagation.png')});record.screenshots.push('recorded-propagation.png');await propagation.close();
 }
 record.browser=context.browser()?.version();record.status='passed';
}catch(error){record.error=String(error);await shot('browser-failure');process.exitCode=1;}
finally{await writeFile(path.join(out,'browser.json'),JSON.stringify(record,null,2)+'\n');await context.close();}
console.log(JSON.stringify({status:record.status,page_errors:record.page_errors,error:record.error}));
