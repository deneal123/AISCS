import { decodeStateContrast } from '../../../src/features/simulator/stateContrast';
import { createStateContrastLayer } from '../../../src/features/simulator/stateContrastLayer';

function fixture() {
  const buffer = new ArrayBuffer(40), view = new DataView(buffer);
  view.setBigUint64(0, 10n, true); view.setBigUint64(8, 30n, true);
  [0, 0, 1, -2, 2, 0].forEach((value, i) => view.setFloat32(16 + i * 4, value, true));
  const graph = { node_ids: BigUint64Array.from([10n, 20n, 30n]), coordinate_kind: Uint8Array.from([1, 0, 1]),
    positions_mm: Float32Array.from([0, 0, 0, 1, 0, 0, 2, 0, 0]), description: { manifest_sha256: 'a'.repeat(64), duration_ms: 2 } };
  const graphFile = { name: 'graph.bin', sha256: 'b'.repeat(64), bytes: 12 };
  const metaFile = { name: 'metadata.json', sha256: 'c'.repeat(64), bytes: 10 };
  const source = { format: 'field-graph-replay-manifest-v1', files: [graphFile, metaFile,
    { name: 'signals.npz' }, { name: 'replay-evidence.jsonl' }, { name: 'replay-provenance.jsonl' }] };
  const description = { format: 'lif-state-contrast-v1', cells: 2, samples: 3, sha256: 'd'.repeat(64),
    graph_sha256: graphFile.sha256, graph_manifest_sha256: graph.description.manifest_sha256,
    field_manifest_sha256: 'e'.repeat(64), step_ms: 1, byte_order: 'little', ids_dtype: '<u8',
    difference_dtype: '<f4', difference_shape: [3, 2], difference_offset: 16, bytes: 40 };
  return { buffer, graph, graphFile, metaFile, source, description };
}
const decode = f => decodeStateContrast(f.buffer, f.description, 'e'.repeat(64), f.graphFile, f.metaFile, f.source, f.graph);

test('preserves signed model differences and uses only verified coordinates', () => {
  const f = fixture(), state = decode(f);
  expect([...state.indices]).toEqual([0, 2]);
  expect([...state.values]).toEqual([0, 0, 1, -2, 2, 0]);
  expect(state.maximum).toBe(2);
  const layer = createStateContrastLayer(f.graph, state);
  expect(layer.visibleCells).toBe(2);
  layer.update(1.7);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([1, -2]);
  expect(layer.bounds(1.7).isEmpty()).toBe(false);
  const nativeBounds = layer.bounds(1.7).clone();
  layer.coordinateView(false);
  const bodyBounds = layer.bounds(1.7);
  expect(bodyBounds.min.toArray()).toEqual([0, 0, 0]);
  expect(bodyBounds.max.toArray()).toEqual([2, 0, 0]);
  expect(bodyBounds.min.toArray()).not.toEqual(nativeBounds.min.toArray());
  layer.coordinateView(true);
  expect(layer.bounds(1.7).min.toArray()).toEqual(nativeBounds.min.toArray());
  layer.update(0);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([0, 0]);
  expect(layer.bounds(0).isEmpty()).toBe(true);
  layer.dispose();
});

test('rejects wrong graph, duplicate ids, malformed layout and nonfinite states', () => {
  let f = fixture(); f.description.graph_sha256 = '0'.repeat(64); expect(() => decode(f)).toThrow();
  f = fixture(); new DataView(f.buffer).setBigUint64(8, 10n, true); expect(() => decode(f)).toThrow();
  f = fixture(); f.description.difference_shape = [2, 3]; expect(() => decode(f)).toThrow();
  f = fixture(); new DataView(f.buffer).setFloat32(16, NaN, true); expect(() => decode(f)).toThrow();
});

test('supports valid sampled identifiers in their saved order', () => {
  const f = fixture(), view = new DataView(f.buffer);
  view.setBigUint64(0, 30n, true); view.setBigUint64(8, 10n, true);
  expect([...decode(f).indices]).toEqual([2, 0]);
});

test('holds the preceding saved state between explicit snapshot times', () => {
  const f = fixture(), state = { ...decode(f), sampleTimes: Uint32Array.from([0, 5, 10]) };
  const layer = createStateContrastLayer(f.graph, state);
  expect(layer.update(4).sample).toBe(0);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([0, 0]);
  expect(layer.update(9).sample).toBe(5);
  expect([...layer.points.geometry.attributes.change.array]).toEqual([1, -2]);
  expect(layer.update(10).sample).toBe(10);
  layer.dispose();
});
