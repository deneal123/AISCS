import { createHash } from 'crypto';
import { verifyCoupledSparseDelta, verifyFragmentSparseDelta } from '../../../src/features/simulator/recording/fragmentSparseDelta';
import { createStateContrastLayer } from '../../../src/features/simulator/stateContrastLayer';

test('validates and displays exact per-tick differences and rejects malformed order', async () => {
  global.crypto = { subtle: { digest: async (_algorithm, input) =>
    Uint8Array.from(createHash('sha256').update(Buffer.from(input)).digest()).buffer } };
  const binary = new ArrayBuffer(80 + 4 * 5 + 8 * 3), view = new DataView(binary), bytes = new Uint8Array(binary);
  bytes.set([83, 80, 68, 49]); view.setUint32(4, 3, true); view.setUint32(8, 4, true); view.setUint32(12, 3, true);
  bytes.fill(0xaa, 16, 48); bytes.fill(0xbb, 48, 80);
  [0, 0, 1, 3, 3].forEach((value, i) => view.setUint32(80 + 4 * i, value, true));
  [1, 1, 2].forEach((value, i) => view.setUint32(100 + 4 * i, value, true));
  [.5, .25, -.5].forEach((value, i) => view.setFloat32(112 + 4 * i, value, true));
  const graphHash = 'a'.repeat(64), configHash = 'b'.repeat(64);
  const graph = { node_ids: BigUint64Array.from([1n, 2n, 3n]), coordinate_kind: Uint8Array.from([1, 1, 1]),
    positions_mm: Float32Array.from([0, 0, 0, 1, 0, 0, 2, 0, 0]), description: { manifest_sha256: graphHash } };
  const file = () => ({ name: 'fragment-delta.bin', bytes: binary.byteLength,
    sha256: createHash('sha256').update(Buffer.from(binary)).digest('hex') });
  const run = entry => ({ configuration_sha256: configHash,
    configuration: { graph_manifest_sha256: graphHash, source_ids: [1], simulation: { duration_ms: 3 } },
    result: { manifest: { kind: 'experimental-fragment-population', graph_sha256: graphHash,
      configuration_sha256: configHash, files: [entry] } } });
  let entry = file();
  const state = await verifyFragmentSparseDelta(binary, entry, run(entry), graph);
  const layer = createStateContrastLayer(graph, state);
  expect(layer.update(1).active).toBe(1);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([.5, 0]);
  expect(layer.update(2).active).toBe(2);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([.25, -.5]);
  expect(layer.update(3).active).toBe(0);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([0, 0]);
  layer.dispose();
  const coupledEntry = { ...entry, name: 'coupled-delta.bin' };
  const coupled = { configuration_sha256: configHash, configuration: { graph_manifest_sha256: graphHash },
    result: { manifest: { kind: 'experimental-coupled-population', graph_sha256: graphHash,
      configuration_sha256: configHash, files: [coupledEntry] },
    preview: { status: 'converged_partial', graph_sha256: graphHash, source_ids: [1], source_cells: 1, duration_ms: 3 } } };
  const coupledState = await verifyCoupledSparseDelta(binary, coupledEntry, coupled, graph);
  expect([...coupledState.values]).toEqual([...state.values]);
  expect([...coupledState.indices]).toEqual([...state.indices]);
  await expect(verifyCoupledSparseDelta(binary, coupledEntry, { ...coupled,
    result: { ...coupled.result, preview: { ...coupled.result.preview, status: 'iteration_limit' } } }, graph))
    .rejects.toThrow('coupled_identity');
  view.setUint32(108, 1, true); entry = file();
  await expect(verifyFragmentSparseDelta(binary, entry, run(entry), graph)).rejects.toThrow('sparse_values');
});
