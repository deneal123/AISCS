import { decodeArborBundle, validateArborManifest } from '../../../src/features/simulator/connectome/sensoryArbors';

function fixture() {
  const buffer = new ArrayBuffer(48), view = new DataView(buffer);
  [[393, 200, 180, -1], [403, 200, 180, 0], [403, 210, 180, 1]].forEach((row, i) => {
    row.slice(0, 3).forEach((v, axis) => view.setFloat32(i * 16 + axis * 4, v, true));
    view.setInt32(i * 16 + 12, row[3], true);
  });
  return { buffer, bundle: { bytes: 48, cells: [{ id: '10001', start: 0, count: 3 }] }, wanted: new Map([['10001', 7]]) };
}

test('real arbor segments retain parent geometry and the original graph index without inferred peripheral paths', () => {
  const { buffer, bundle, wanted } = fixture();
  const result = decodeArborBundle(buffer, bundle, wanted);
  expect(result.cells).toBe(1); expect(result.vertices).toBe(3);
  expect([...result.nodeIndices]).toEqual([7, 7, 7, 7]);
  const expected = [0.80907826, 0, 0.02593260, 0.80907826, 0.01, 0.02593260,
    0.80907826, 0.01, 0.02593260, 0.80641858, 0.01, 0.01733457];
  expected.forEach((value, index) => expect(result.positions[index]).toBeCloseTo(value, 6));
});

test('cyclic, foreign or unresolvable geometry never becomes a displayed arbor', () => {
  const { buffer, bundle, wanted } = fixture(), view = new DataView(buffer);
  view.setInt32(12, 1, true);
  expect(() => decodeArborBundle(buffer, bundle, wanted)).toThrow('cycle');
  view.setInt32(12, -1, true); view.setInt32(28, 3, true);
  expect(() => decodeArborBundle(buffer, bundle, wanted)).toThrow('vertex');
  view.setInt32(28, 0, true); view.setFloat32(0, NaN, true);
  expect(() => decodeArborBundle(buffer, bundle, wanted)).toThrow('vertex');
  expect(() => validateArborManifest({ dataset_id: 'another-release' }, { description: {} })).toThrow('identity');
});
