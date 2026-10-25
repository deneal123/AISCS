// Exercise the actual pinned TypeScript neural engine on its full compact graph.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";
import { gunzipSync } from "node:zlib";

const source = "/work/source";
const output = "/work/exports/flybox";
await mkdir(output, { recursive: true });
const ts = (await import(pathToFileURL(`${source}/frontend/node_modules/typescript/lib/typescript.js`))).default;
const input = await readFile(`${source}/frontend/src/connectome.ts`, "utf8");
const compiled = ts.transpileModule(input, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const compiledPath = `${output}/connectome-upstream.mjs`;
await writeFile(compiledPath, compiled);
const api = await import(pathToFileURL(compiledPath));
const directory = `${source}/frontend/public/connectome`;
const manifest = JSON.parse(await readFile(`${directory}/brain.json`, "utf8"));
assert.equal(manifest.neurons, 166700);
assert.equal(manifest.connections, 25088107);
const binary = (buffer) => buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
const sha = (buffer) => createHash("sha256").update(buffer).digest("hex");
const inputHashes = {};
const metaBytes = await readFile(`${directory}/meta.bin`);
inputHashes["meta.bin"] = sha(metaBytes);
const parts = [];
for (const name of manifest.parts) {
  assert.match(name, /^weights\.\d+\.bin$/);
  const bytes = await readFile(`${directory}/${name}`);
  inputHashes[name] = sha(bytes);
  parts.push(bytes);
}
const meta = api.parseMeta(binary(gunzipSync(metaBytes)));
const weights = api.parseWeights(binary(gunzipSync(Buffer.concat(parts))));
assert.equal(meta.n, manifest.neurons);
assert.equal(weights.n, meta.n);
assert.equal(weights.nnz, manifest.connections);
assert.equal(weights.colPtr[meta.n], weights.nnz);
for (let i = 0; i < meta.n; i++) {
  assert(weights.colPtr[i] <= weights.colPtr[i + 1]);
  assert(meta.typeIdx[i] < meta.types.length && meta.classIdx[i] < meta.superclasses.length);
}
for (const index of weights.rowIdx) assert(index >= 0 && index < meta.n);
for (const value of weights.lut) assert(Number.isFinite(value));
const population = api.cells(meta, ["LC4", "LPLC2"]);
assert(population.length > 0);
const targets = population.slice(0, 16);
const trials = [];
let reference = null;
for (const [attempt, seed] of [1, 2, 3, 1].entries()) {
  const brain = new api.ConnectomeBrain(weights, meta.params, seed);
  const rows = ["seed,attempt,step,time_ms,neuron_index"];
  const started = performance.now();
  let total = 0;
  for (let tick = 0; tick < 20; tick++) {
    brain.stimulate(targets, 1.2);
    const fired = brain.step();
    for (const value of brain.v) assert(Number.isFinite(value));
    for (const value of brain.current) assert(Number.isFinite(value));
    for (const neuron of fired) {
      assert(neuron >= 0 && neuron < meta.n);
      rows.push(`${seed},${attempt},${tick},${(tick + 1) * meta.params.dt * 1000},${neuron}`);
    }
    total += fired.length;
  }
  const seconds = (performance.now() - started) / 1000;
  assert(total > 0);
  const spikeContent = rows.slice(1).map((row) => row.split(",").slice(2).join(",")).join("\n");
  const stateHash = sha(Buffer.from(brain.v.buffer));
  if (attempt === 0) reference = { spikeContent, stateHash };
  if (attempt === 3) assert.deepEqual({ spikeContent, stateHash }, reference);
  const file = `seed${seed}-attempt${attempt}.csv`;
  await writeFile(`${output}/${file}`, rows.join("\n") + "\n");
  trials.push({ seed, spikes: total, seconds_with_diagnostics: seconds, final_voltage_sha256: stateHash, file });
}
const brain = new api.ConnectomeBrain(weights, meta.params, 1);
brain.stimulate(targets, 1.2);
brain.step();
assert(Array.from(targets).some((x) => brain.fired.subarray(0, brain.firedCount).includes(x)));
const checkpoint = brain.snapshot();
brain.step();
const nextState = brain.snapshot();
brain.restore(checkpoint);
brain.step();
assert.deepEqual(brain.snapshot(), nextState);
const clone = new api.ConnectomeBrain(weights, meta.params, 999);
clone.copyStateFrom(brain);
assert.deepEqual(clone.snapshot(), brain.snapshot());
brain.step();
clone.step();
assert.deepEqual(clone.snapshot(), brain.snapshot());
const blocked = new Uint8Array(meta.n);
for (const index of targets) blocked[index] = 1;
brain.stimulate(targets, 1.2);
brain.step();
const filtered = brain.filterFired(blocked);
assert(Array.from(filtered).every((index) => blocked[index] === 0));
const a = new api.ConnectomeBrain(weights, meta.params, 1);
const b = new api.ConnectomeBrain(weights, meta.params, 1);
assert.equal(a.lesion(0.1, 99), b.lesion(0.1, 99));
assert.deepEqual(a.snapshot().lesionMask, b.snapshot().lesionMask);
a.clearLesions();
assert.equal(a.snapshot().lesionMask, null);
a.restore(checkpoint);
const changed = a.lesion(1, 7);
assert.equal(changed, weights.nnz);
a.step();
assert(a.current.every((value) => value === 0));
const soma = await readFile(`${directory}/soma.bin`);
assert.equal(soma.toString("ascii", 0, 4), "FLYS");
assert.equal(soma.readUInt32LE(8), meta.n);
assert(soma.readUInt32LE(12) > 0 && soma.readUInt32LE(12) <= meta.n);
assert.equal(soma.length, 16 + meta.n * 6);
inputHashes["soma.bin"] = sha(soma);
const anatomyHash = createHash("sha256");
for await (const chunk of createReadStream("/work/brain-data/brain.npz")) anatomyHash.update(chunk);
inputHashes["brain.npz"] = anatomyHash.digest("hex");
assert.equal(inputHashes["brain.npz"], "cc9bd1ecd00bd703a6fa648bc6ad145c93c7c1ee53debdcc9ce0d1f4305e6aca");
const result = {
  status: "passed", scope: "unmodified upstream TypeScript neural engine, real compact MaleCNS graph, Node CPU",
  neurons: meta.n, connectivity_rows: weights.nnz, params: meta.params, trials,
  stimulated_population: "first 16 indices from LC4/LPLC2", available_population_neurons: population.length,
  repeat_seed_equal: true, snapshot_restore_equal: true, fork_future_equal: true,
  spike_output_filter_checked: true, deterministic_lesions_checked: true, all_edges_lesion_zero_current: true,
  mapped_soma: soma.readUInt32LE(12), input_sha256: inputHashes,
  typescript_source_sha256: sha(Buffer.from(input)),
  limitations: ["8-bit log-quantized weights", "Normalized model voltages, not human ECAP",
                "Body/world and browser UI require separate checks", "Not biological validation"],
};
await writeFile(`${output}/connectome-result.json`, JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify(result));
