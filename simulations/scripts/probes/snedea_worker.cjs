/* Runs the pinned browser-worker code in Node V8 on its real binary export.
 * No body/UI claim follows from this separate kernel scenario. */
const fs = require('node:fs');
const vm = require('node:vm');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const {performance} = require('node:perf_hooks');

const raw = zlib.gunzipSync(fs.readFileSync('/work/assets/connectome.bin.gz'));
const events = [];
const ctx = vm.createContext({self: {postMessage: x => events.push(x)}, performance,
  Uint8Array, Uint16Array, Uint32Array, Int8Array, Int16Array, Int32Array,
  Float32Array, Float64Array, ArrayBuffer, DataView, Math, console,
  setTimeout: () => {}, clearTimeout: () => {}});
vm.runInContext(fs.readFileSync('js/sim-worker.js', 'utf8'), ctx, {filename: 'js/sim-worker.js'});
ctx.self.onmessage({data: {type: 'init', buffer: raw.buffer.slice(raw.byteOffset, raw.byteOffset+raw.byteLength)}});
const ready = events.find(x => x.type === 'ready');
if (!ready) throw new Error(JSON.stringify(events));
if (ready.neuronCount !== 139255) throw new Error('Unexpected registered export neuron count');
function run(seed) {
  ctx.self.onmessage({data: {type: 'reset'}});
  let state = seed;
  function random() { state = (Math.imul(state, 1664525)+1013904223) >>> 0; return state/4294967296; }
  const index = Math.floor(random()*ready.neuronCount);
  ctx.self.onmessage({data: {type: 'setStimulusState', indices: [index], intensities: [0.15]}});
  const digests = [], spikes = [];
  for (let t=0; t<12; t++) {
    events.length = 0;
    vm.runInContext('tick()', ctx);
    const event = events.find(x => x.fireState);
    if (!event || event.fireState.length !== ready.neuronCount) throw new Error('Bad export dimensions');
    const potentials = vm.runInContext('V', ctx);
    if (!potentials.every(Number.isFinite)) throw new Error('Nonfinite potential');
    digests.push(crypto.createHash('sha256').update(event.fireState).update(Buffer.from(potentials.buffer)).digest('hex'));
    spikes.push(event.firedNeurons);
  }
  return {seed, stimulated_index: index, digests, spikes};
}
const results = [1,2,3].map(run);
const repeat = run(1);
if (JSON.stringify(repeat) !== JSON.stringify(results[0])) throw new Error('Reset/seed mismatch');
const counterBefore = vm.runInContext('tickCount', ctx);
ctx.self.onmessage({data: {type: 'reset'}});
const counterAfter = vm.runInContext('tickCount', ctx);
const output = {scope: 'real_registered_export_in_Node_V8_worker_code_not_browser_or_body',
  neurons: ready.neuronCount, edges: ready.edgeCount, seeds: [1,2,3],
  seed_controls_external_stimulus: true, native_model_seed: false,
  repeat_seed_equal: true, time_unit: 'tick_without_physical_dt_calibration',
  potential_unit: 'normalized_model_variable', reset_resets_tick_counter: counterAfter === 0,
  index_space: 'group_sorted_worker_indices_without_original_FlyWire_IDs',
  reset_counter_before: counterBefore, reset_counter_after: counterAfter, results};
fs.mkdirSync('/work/exports', {recursive: true});
fs.writeFileSync('/work/exports/worker.json', JSON.stringify(output, null, 2)+'\n');
console.log(JSON.stringify({neurons: output.neurons, edges: output.edges, repeat_seed_equal: true}));
if (!output.reset_resets_tick_counter) {
  console.error('Reset does not restore the simulation clock; see exports/worker.json');
  process.exitCode = 1;
}
