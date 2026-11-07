import { applyFragmentEvents, verifyCoupledEvents, verifyCoupledSourceEvents, verifyFragmentEvents } from '../../../src/features/simulator/recording/fragmentEvents';
import { createHash, webcrypto } from 'crypto';
import { TextDecoder } from 'util';

const graph = 'a'.repeat(64);
const configuration = { graph_manifest_sha256: graph, source_ids: [1], simulation: { duration_ms: 10 } };
const base = { node_ids: BigUint64Array.from([1n, 2n, 3n]), description: { manifest_sha256: graph } };
const metadata = { configuration, events: { format: 'fragment-events-v1', graph_sha256: graph, node_count: 3, event_count: 2 } };

function buffer(indices = [1, 2], times = [2, 3]) {
  const output = new ArrayBuffer(3 * 8 + 2 * 8);
  new BigUint64Array(output, 0, 3).set(base.node_ids);
  new Int32Array(output, 24, 2).set(indices);
  new Float32Array(output, 32, 2).set(times);
  return output;
}

test('replaces original activity with the verified journal, keeping source cells silent', () => {
  const result = applyFragmentEvents(base, buffer(), metadata, configuration);
  expect(Array.from(result.input_indices)).toEqual([0]);
  expect(Array.from(result.spike_neurons)).toEqual([1, 2]);
  expect(Array.from(result.counts)).toEqual([0, 1, 1]);
});

test('rejects source firing, changed configuration and unsorted event times', () => {
  expect(() => applyFragmentEvents(base, buffer([0, 2]), metadata, configuration)).toThrow('fragment_events');
  expect(() => applyFragmentEvents(base, buffer(), metadata, { ...configuration, source_ids: [2] })).toThrow('fragment_identity');
  expect(() => applyFragmentEvents(base, buffer([1, 2], [3, 2]), metadata, configuration)).toThrow('fragment_events');
});

test('checks both file digests before displaying the event journal', async () => {
  global.crypto = webcrypto;
  global.TextDecoder = TextDecoder;
  const events = buffer();
  const bytes = Buffer.from(JSON.stringify(metadata), 'utf8');
  const model = Uint8Array.from(bytes).buffer;
  const artifact = data => ({ bytes: data.byteLength, sha256: createHash('sha256').update(Buffer.from(data)).digest('hex') });
  const result = await verifyFragmentEvents(base, events, artifact(events), model, artifact(model), configuration);
  expect(Array.from(result.spike_neurons)).toEqual([1, 2]);
  await expect(verifyFragmentEvents(base, events, { ...artifact(events), sha256: '0'.repeat(64) }, model, artifact(model), configuration)).rejects.toThrow('fragment_checksum');
});

test('checks coupled network events and separates source cells', async () => {
  global.crypto = webcrypto;
  const events = buffer();
  const artifact = { name: 'coupled-events.bin', bytes: events.byteLength,
    sha256: createHash('sha256').update(Buffer.from(events)).digest('hex') };
  const run = { configuration_sha256: 'b'.repeat(64), configuration: { graph_manifest_sha256: graph },
    result: { manifest: { kind: 'experimental-coupled-population', graph_sha256: graph,
      configuration_sha256: 'b'.repeat(64), files: [artifact] },
    preview: { status: 'converged', graph_sha256: graph, graph_cells: 3, source_cells: 1,
      source_ids: [1], network_spikes: 2, duration_ms: 10 } } };
  const result = await verifyCoupledEvents(base, events, artifact, run);
  expect(Array.from(result.spike_neurons)).toEqual([1, 2]);
  expect(Array.from(result.input_indices)).toEqual([0]);
  await expect(verifyCoupledEvents(base, buffer([0, 2]), artifact, run)).rejects.toThrow('coupled_checksum');
  await expect(verifyCoupledEvents(base, events, artifact, { ...run,
    result: { ...run.result, preview: { ...run.result.preview, status: 'iteration_limit' } } }))
    .rejects.toThrow('coupled_identity');
});

test('verifies source-segment crossings separately from network spikes', async () => {
  global.crypto = webcrypto;
  const data = new ArrayBuffer(96), bytes = new Uint8Array(data), view = new DataView(data);
  bytes.set([83, 82, 67, 49]); view.setUint32(4, 3, true); view.setUint32(8, 10, true);
  view.setUint32(12, 2, true); bytes.set(Buffer.from(graph, 'hex'), 16);
  bytes.set(Buffer.from('b'.repeat(64), 'hex'), 48);
  new Uint32Array(data, 80, 2).set([0, 0]); new Uint32Array(data, 88, 2).set([1, 3]);
  const artifact = { name: 'coupled-source-events.bin', bytes: data.byteLength,
    sha256: createHash('sha256').update(Buffer.from(data)).digest('hex') };
  const run = { configuration_sha256: 'b'.repeat(64), result: {
    manifest: { graph_sha256: graph, configuration_sha256: 'b'.repeat(64), files: [artifact] },
    preview: { graph_cells: 3, source_cells: 1, duration_ms: 10 } } };
  const result = await verifyCoupledSourceEvents({ ...base, input_indices: Int32Array.of(0) }, data, artifact, run);
  expect(Array.from(result.physical_source_times_ms)).toEqual([1, 3]);
  expect(result.spike_neurons).toBeUndefined();
  await expect(verifyCoupledSourceEvents({ ...base, input_indices: Int32Array.of(1) }, data, artifact, run))
    .rejects.toThrow('source_events_order');
  const altered = data.slice(0);
  new Uint32Array(altered, 88, 2).set([3, 1]);
  const alteredArtifact = { ...artifact, sha256: createHash('sha256').update(Buffer.from(altered)).digest('hex') };
  const alteredRun = { ...run, result: { ...run.result,
    manifest: { ...run.result.manifest, files: [alteredArtifact] } } };
  await expect(verifyCoupledSourceEvents({ ...base, input_indices: Int32Array.of(0) }, altered,
    alteredArtifact, alteredRun)).rejects.toThrow('source_events_order');
  await expect(verifyCoupledSourceEvents({ ...base, input_indices: Int32Array.of(0) }, altered,
    artifact, run)).rejects.toThrow('source_events_checksum');
});
