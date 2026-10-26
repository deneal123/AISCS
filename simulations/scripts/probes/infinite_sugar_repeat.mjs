// Fixed-update repeat test of the exact native CPU Brain class, not body/GUI fidelity.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';

const source = '/work/source';
const out = '/work/exports';
fs.mkdirSync(out, {recursive:true});
const files = new Set(['meta.json','indptr.bin.gz','colidx.bin.gz','w2.bin.gz']);
globalThis.fetch = async (url) => {
  const name = path.posix.basename(String(url));
  assert(files.has(name));
  return new Response(fs.readFileSync(path.join(source,'web/brain',name)));
};
const { Brain } = await import(pathToFileURL(path.join(source,'web/brain.ts')).href);
const original = await Brain.load('/registered-brain');
assert.equal(original.N,139255);
assert.equal(original.colidx.length,2700513);
const bytes = (a) => Buffer.from(a.buffer,a.byteOffset,a.byteLength);
const sha = (a) => crypto.createHash('sha256').update(a).digest('hex');
const matrixBefore = [original.indptr,original.colidx,original.w].map(a=>sha(bytes(a)));
const cases = [];
for (const [name,seed] of [['native-default',null],['native-default-repeat',null],['noise-1',1],['noise-2',2],['noise-3',3],['noise-1-repeat',1]]) {
  const brain = new Brain(original.meta,original.indptr,original.colidx,original.w);
  const nativeInitialRng = brain._rng;
  if (seed !== null) brain._rng = seed;
  const rolling = crypto.createHash('sha256');
  const rows = [];
  for(let tick=0;tick<80;tick++) {
    brain.step(1);
    assert.equal(brain.ms,tick+1);
    assert(brain.v.every(Number.isFinite));
    rolling.update(bytes(brain.v));
    rows.push({native_ms:brain.ms,cumulative_events:brain.totalSpikes});
  }
  const digest = crypto.createHash('sha256');
  for(const values of [brain.v,brain.refr,brain.baseline,...brain.inhVal,...brain.inhIdx,brain.inhCnt,brain.lastSpikeMs]) digest.update(bytes(values));
  digest.update(JSON.stringify({rng:brain._rng,slot:brain.slot,ms:brain.ms,totalSpikes:brain.totalSpikes,rate:brain.rate,popRate:brain.popRate}));
  const file = name+'-final-voltage.f32.gz';
  fs.writeFileSync(path.join(out,file),gzipSync(bytes(brain.v),{mtime:0}));
  const item = {name,noise_seed_override:seed,native_baseline_seed:22222,native_initial_rng:nativeInitialRng,steps:80,neurons:brain.N,events:brain.totalSpikes,trace_sha256:rolling.digest('hex'),full_state_sha256:digest.digest('hex'),file,file_sha256:sha(fs.readFileSync(path.join(out,file))),rows};
  cases.push(item);
  console.log(JSON.stringify({name,events:item.events,trace_sha256:item.trace_sha256}));
}
const signatures=(x)=>[x.trace_sha256,x.full_state_sha256];
assert.deepEqual(signatures(cases[0]),signatures(cases[1]));
assert.deepEqual(signatures(cases[2]),signatures(cases[5]));
assert.notDeepEqual(signatures(cases[2]),signatures(cases[3]));
assert.notDeepEqual(signatures(cases[2]),signatures(cases[4]));
assert.deepEqual([original.indptr,original.colidx,original.w].map(a=>sha(bytes(a))),matrixBefore);
const result={status:'passed',repeat_seed_equal:true,cases,matrix_hashes:matrixBefore,matrix_unchanged:true,scope:'Exact native CPU Brain and real registered graph; 80 fixed updates from fresh constructors. Native baseline is seeded22222; optional _rng overrides affect sparse random kicks only. No renderer, body replay, steady-state calibration or biological/physical unit validation claimed.',backend:process.version};
fs.writeFileSync(path.join(out,'neural-repeat.json'),JSON.stringify(result,null,2)+'\n');
