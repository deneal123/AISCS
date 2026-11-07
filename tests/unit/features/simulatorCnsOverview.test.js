import { decodeOverviewChunk, validateOverview } from '../../../src/features/simulator/connectome/cnsOverview';

function manifest() {
  let start = 0; const chunks = [];
  while (start < 166700) {
    const cells = Math.min(10000, 166700 - start);
    chunks.push({ start, cells, cells_with_edges: cells, file: `overview-${String(start).padStart(6, '0')}.bin.gz`, bytes: 10, sha256: 'a'.repeat(64) });
    start += cells;
  }
  return { dataset_id: 'male-cns:v1.0-annotated-nonglial', manifest_sha256: 'graph', source_frame: 'MaleCNS native unmirrored EM',
    units: 'um', method: 'evenly-sampled-original-swc-edges-v1', record_bytes: 28, edges_per_neuron_max: 8, chunks };
}

test('overview must match the complete registered graph', () => {
  expect(validateOverview(manifest(), 'graph').chunks).toHaveLength(17);
  expect(() => validateOverview(manifest(), 'other')).toThrow('overview_identity');
  const partial = manifest(); partial.chunks.pop();
  expect(() => validateOverview(partial, 'graph')).toThrow('overview_coverage');
});

test('decoder validates graph index and retains endpoints in the correct frame', () => {
  const raw = new ArrayBuffer(28), view = new DataView(raw);
  view.setUint32(0, 20, true);
  [393, 200, 180, 394, 200, 180].forEach((value, i) => view.setFloat32(4 + i * 4, value, true));
  const chunk = { start: 20, cells: 1, cells_with_edges: 1 };
  const result = decodeOverviewChunk(raw, chunk, 8);
  expect([...result.nodeIndices]).toEqual([20, 20]);
  expect(result.positions[4] - result.positions[1]).toBeCloseTo(.001);
  view.setUint32(0, 21, true);
  expect(() => decodeOverviewChunk(raw, chunk, 8)).toThrow('overview_index');
});
