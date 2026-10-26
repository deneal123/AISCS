/* Observe native numerical kernel with a separately recorded reset-clock fix.
 * Seeds select external stimuli, not native model randomness. */
const fs = require('node:fs');
const vm = require('node:vm');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {performance} = require('node:perf_hooks');
const out = '/work/exports';
fs.mkdirSync(out,{recursive:true});
const hash = x=>crypto.createHash('sha256').update(x).digest('hex');
const raw = zlib.gunzipSync(fs.readFileSync('data/connectome.bin.gz'));
const N=raw.readUInt32LE(0),E=raw.readUInt32LE(4);
assert.equal(N,139255);assert.equal(E,2698236);assert.equal(raw.length,8+12*E+3*N);
const metadata=JSON.parse(fs.readFileSync('data/neuron_meta.json','utf8'));
assert.equal(metadata.neuron_count,N);assert.equal(metadata.edge_count,E);
const events=[];
const ctx=vm.createContext({self:{postMessage:x=>events.push(x)},performance,
 Uint8Array,Uint16Array,Uint32Array,Int8Array,Int16Array,Int32Array,Float32Array,Float64Array,
 ArrayBuffer,DataView,Math,console,setTimeout:()=>{},clearTimeout:()=>{}});
vm.runInContext(fs.readFileSync('js/sim-worker.js','utf8'),ctx,{filename:'js/sim-worker.js'});
const send=data=>ctx.self.onmessage({data}),get=code=>vm.runInContext(code,ctx);
send({type:'init',buffer:raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength)});
assert(events.some(x=>x.type==='ready' && x.neuronCount===N));
const group=Array.from(get('groupId')),counts=new Array(63).fill(0),originalGroups=[];
for(let i=0;i<N;i++){const g=raw.readUInt16LE(8+12*E+3*i+1);assert(g<63);originalGroups.push(g);counts[g]++;}
assert.deepEqual(counts,metadata.group_sizes);
const sortedToOriginal=Array.from({length:N},(_,i)=>i).sort((a,b)=>originalGroups[a]-originalGroups[b]);
assert.deepEqual(sortedToOriginal.map(i=>originalGroups[i]),group);
const permutation=Buffer.alloc(N*4);
sortedToOriginal.forEach((value,i)=>permutation.writeUInt32LE(value,4*i));
fs.writeFileSync(out+'/worker-to-author-binary-index.u32.gz',zlib.gzipSync(permutation));
function stimulus(seed){
 let state=seed;const chosen=new Set();
 while(chosen.size<128){state=(Math.imul(state,1664525)+1013904223)>>>0;chosen.add(Math.floor(state/4294967296*counts[0]));}
 return Array.from(chosen).sort((a,b)=>a-b);
}
const originalWeights=new Float32Array(get('values'));
const originalWeightHash=hash(Buffer.from(originalWeights.buffer));
function run(name,seed,condition='intact'){
 send({type:'stop'});send({type:'reset'});assert.equal(get('tickCount'),0);
 send({type:'setParams',leakRate:.95,threshold:condition==='higher-threshold'?2:1,refractoryPeriod:3});
 const weights=get('values');weights.set(originalWeights);if(condition==='zero-weights')weights.fill(0);
 const indices=condition==='no-input'?[]:stimulus(seed);
 send({type:'setStimulusState',indices,intensities:indices.map(()=>.8)});
 const series=[],spikes=[],buffers=[],started=performance.now();
 for(let tick=0;tick<120;tick++){
  events.length=0;get('tick()');const event=events.find(x=>x.type==='tick');
  assert(event);assert.equal(event.tickCount,tick);assert.equal(event.fireState.length,N);
  const potentials=get('V');assert(potentials.every(Number.isFinite));
  const ids=[];for(let i=0;i<N;i++)if(event.fireState[i])ids.push(i);
  assert.equal(ids.length,event.firedNeurons);assert.equal(event.groupSpikeCounts.reduce((a,b)=>a+b,0),ids.length);
  for(const index of ids)spikes.push([tick,index,group[index]]);
  series.push({tick,events:ids.length,active_neurons:get('activeNeuronCount')});
  buffers.push(Buffer.from(new Uint8Array(potentials.buffer).slice()));
 }
 const values=Buffer.concat(buffers),stateFile=name+'-states.f32.gz',eventFile=name+'-spikes.json';
 fs.writeFileSync(out+'/'+stateFile,zlib.gzipSync(values));
 fs.writeFileSync(out+'/'+eventFile,JSON.stringify({columns:['tick','worker_index','group_id'],rows:spikes})+'\n');
 const selected=new Set(indices);
 const result={name,seed,condition,stimulated_indices:indices,stimulus:.8,ticks:120,shape:[120,N],potential_dtype:'little-endian float32',
  time_unit:'uncalibrated model tick',potential_unit:'normalized model variable',seconds:(performance.now()-started)/1000,
  total_events:spikes.length,events_outside_stimulated:spikes.filter(row=>!selected.has(row[1])).length,
  state_export:stateFile,event_export:eventFile,state_array_sha256:hash(values),state_file_sha256:hash(fs.readFileSync(out+'/'+stateFile)),
  event_file_sha256:hash(fs.readFileSync(out+'/'+eventFile)),series};
 console.log(JSON.stringify({name,events:result.total_events,outside:result.events_outside_stimulated,seconds:result.seconds}));return result;
}
const runs=[run('seed-1',1),run('seed-2',2),run('seed-3',3),run('seed-1-repeat',1),run('no-input',1,'no-input'),run('zero-weights',1,'zero-weights'),run('higher-threshold',1,'higher-threshold')];
assert.equal(runs[0].state_array_sha256,runs[3].state_array_sha256);assert.equal(runs[0].event_file_sha256,runs[3].event_file_sha256);
assert.notEqual(runs[0].state_array_sha256,runs[1].state_array_sha256);assert.equal(runs[4].total_events,0);assert.equal(runs[5].events_outside_stimulated,0);
get('values').set(originalWeights);assert.equal(hash(Buffer.from(get('values').buffer)),originalWeightHash);
send({type:'stop'});send({type:'reset'});assert.equal(get('tickCount'),0);assert(get('V').every(x=>x===0));assert(get('fired').every(x=>x===0));
const result={status:'passed',scope:'registered full author export in Node worker; one reset-clock assignment adapted',neurons:N,edges:E,groups:63,
 seeds:[1,2,3],seed_controls_external_stimulus:true,native_model_seed:false,repeat_seed_equal:true,reset_resets_tick_counter:true,
 empty_NOCI_group:metadata.groups.find(g=>g.name==='NOCI').neuron_count===0,
 index_space:'group-sorted worker indices; reversible to author binary index; FlyWire root IDs absent from these two inputs',original_weight_sha256:originalWeightHash,runs};
fs.writeFileSync(out+'/worker.json',JSON.stringify(result,null,2)+'\n');
let paths='';const colors=['#176294','#d48c20','#32834b'];
const peak=Math.max(1,...runs.slice(0,3).flatMap(r=>r.series.map(x=>x.events)));
for(let c=0;c<3;c++){
 const points=runs[c].series.map(v=>(70+v.tick*8)+','+(420-v.events*330/peak)).join(' ');
 paths+=`<polyline points="${points}" fill="none" stroke="${colors[c]}" stroke-width="2"/><text x="${80+c*200}" y="460" fill="${colors[c]}">stimulus seed ${c+1}</text>`;
}
const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="510" viewBox="0 0 1120 510"><rect width="1120" height="510" fill="white"/><g font-family="Arial" font-size="19" fill="#222"><text x="60" y="35">Recorded threshold events — full author graph, 139255 neurons</text><path d="M70 70V420H1050" fill="none" stroke="#222"/><text x="70" y="65">Events per model tick (maximum ${peak})</text><text x="450" y="495">120 uncalibrated ticks; external stimulation seeds</text>${paths}</g></svg>`;
fs.writeFileSync(out+'/recorded-events.svg',svg);
