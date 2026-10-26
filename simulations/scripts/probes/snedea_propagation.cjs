// Check a convergent path explicitly; sparse random stimulation alone drove only its inputs.
const fs=require('node:fs'),vm=require('node:vm'),zlib=require('node:zlib'),assert=require('node:assert/strict');
const {performance}=require('node:perf_hooks');
const raw=zlib.gunzipSync(fs.readFileSync('data/connectome.bin.gz'));
const events=[];
const ctx=vm.createContext({self:{postMessage:x=>events.push(x)},performance,Uint8Array,Uint16Array,Uint32Array,Float32Array,Float64Array,ArrayBuffer,DataView,Math,console,setTimeout:()=>{},clearTimeout:()=>{}});
vm.runInContext(fs.readFileSync('js/sim-worker.js','utf8'),ctx);
const get=x=>vm.runInContext(x,ctx),send=x=>ctx.self.onmessage({data:x});
send({type:'init',buffer:raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)});
assert.equal(get('N'),139255);
const row=get('rowPtr'),col=get('colIdx'),weights=get('values'),original=new Float32Array(weights),sums=new Float64Array(get('N'));
for(let pre=0;pre<sums.length;pre++)for(let j=row[pre];j<row[pre+1];j++)if(col[j]!==pre && weights[j]>0)sums[col[j]]+=weights[j];
let target=0;for(let i=1;i<sums.length;i++)if(sums[i]>sums[target])target=i;
const incoming=new Map();
for(let pre=0;pre<sums.length;pre++)for(let j=row[pre];j<row[pre+1];j++)if(col[j]===target && pre!==target && weights[j]>0)incoming.set(pre,(incoming.get(pre)||0)+weights[j]);
const indices=Array.from(incoming).sort((a,b)=>b[1]-a[1]).slice(0,256).map(x=>x[0]);
assert(indices.length>0);assert(!indices.includes(target));
function run(connected){
 send({type:'stop'});send({type:'reset'});send({type:'setParams',threshold:1,refractoryPeriod:3,leakRate:.95});
 weights.set(original);if(!connected)weights.fill(0);
 send({type:'setStimulusState',indices,intensities:indices.map(()=>2)});
 const selected=new Set(indices),spikes=[],series=[];let targetMax=0,targetEvents=0,outside=0;
 const started=performance.now();
 for(let tick=0;tick<160;tick++){
  events.length=0;get('tick()');const event=events.find(x=>x.type==='tick'),potential=get('V');
  assert(event);assert(potential.every(Number.isFinite));targetMax=Math.max(targetMax,potential[target]);
  if(event.fireState[target])targetEvents++;
  let outsideTick=0;
  for(let i=0;i<event.fireState.length;i++)if(event.fireState[i]){spikes.push([tick,i]);if(!selected.has(i)){outside++;outsideTick++;}}
  series.push({tick,target_potential:potential[target],target_event:event.fireState[target],events:event.firedNeurons,outside_events:outsideTick});
 }
 return {connected,target_events:targetEvents,max_target_potential:targetMax,events_outside_stimulated:outside,seconds:(performance.now()-started)/1000,series,spikes};
}
const intact=run(true),control=run(false);weights.set(original);
assert.equal(control.events_outside_stimulated,0);assert.equal(control.max_target_potential,0);
assert(intact.max_target_potential>0 || intact.target_events>0);
const result={status:'passed',scope:'diagnostic chosen convergent stimulation, not a natural stimulus or biological circuit validation',target_worker_index:target,incoming_positive_sum:sums[target],selected_incoming_sum:indices.reduce((s,i)=>s+incoming.get(i),0),stimulated_indices:indices,time_unit:'uncalibrated model tick',intact,zero_weights:control};
fs.writeFileSync('/work/exports/convergent-propagation.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({target,selected:indices.length,intact_events:intact.target_events,outside:intact.events_outside_stimulated,control_events:control.target_events}));
