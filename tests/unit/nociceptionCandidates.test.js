import { nociceptionAscendingIndices, nociceptionCandidateIndices } from '../../src/features/simulator/connectome/nociceptionCandidates';

const graph = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';

test('shows only mapped candidates with source positions on the pinned graph', () => {
  const data = { description: { manifest_sha256: graph }, node_ids: [804024n, 804202n, 42n],
    coordinate_kind: [1, 0, 1] };
  expect(nociceptionCandidateIndices(data)).toEqual([0]);
  expect(nociceptionCandidateIndices({ ...data, description: { manifest_sha256: 'other' } })).toEqual([]);
  expect(nociceptionCandidateIndices(null)).toEqual([]);
  expect(nociceptionAscendingIndices({ ...data, node_ids: [11604n, 42n], coordinate_kind: [1, 1] })).toEqual([0]);
  expect(nociceptionAscendingIndices({ ...data, description: { manifest_sha256: 'other' } })).toEqual([]);
});
