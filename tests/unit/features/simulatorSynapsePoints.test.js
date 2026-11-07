import { decodeSynapsePoints } from '../../../src/features/simulator/connectome/useSynapsePoints';
import { maleCnsViewPosition } from '../../../src/features/simulator/connectome/connectomeMorphology';

const page = { nodeId: '1', direction: 'outgoing', offset: 0, items: [{ target_id: '2', synapse_count: 1 }] };
const pair = { body_pre: 1, body_post: 2, x_pre: 100, y_pre: 200, z_pre: 300, x_post: 105, y_post: 205, z_post: 305 };
const record = { body_id: '1', direction: 'outgoing', graph_manifest_sha256: 'graph', graph_offset: 0,
  coordinate_frame: 'male-cns-v1.0-native-8nm', source_md5: '58efcf712f8c4d4de5f2ad51e97def76',
  counts_match: true, total: 1, returned: 1, truncated: false, pairs: [pair],
  edge_counts: [{ partner_id: '2', graph_synapses: 1, source_pairs: 1 }] };

test('uses source coordinates and preserves neuron and graph identity', () => {
  const result = decodeSynapsePoints(record, page, 'graph');
  expect([...result.positions]).toEqual(maleCnsViewPosition([.8, 1.6, 2.4]).map(Math.fround));
  expect(result.total).toBe(1);
  expect(result.presynaptic.get('1')).toEqual([0]);
  const incoming = { ...record, body_id: '2', direction: 'incoming',
    edge_counts: [{ partner_id: '1', graph_synapses: 1, source_pairs: 1 }] };
  const decodedIncoming = decodeSynapsePoints(incoming, { nodeId: '2', direction: 'incoming', offset: 0,
    items: [{ source_id: '1', synapse_count: 1 }] }, 'graph');
  expect([...decodedIncoming.positions]).toEqual(maleCnsViewPosition([.84, 1.64, 2.44]).map(Math.fround));
  expect(decodedIncoming.presynaptic.get('1')).toEqual([0]);
});

test('rejects mismatched graphs, partners, edge counts and coordinates', () => {
  expect(() => decodeSynapsePoints(record, page, 'other')).toThrow('synapse_identity');
  expect(() => decodeSynapsePoints({ ...record, pairs: [{ ...pair, body_post: 3 }] }, page, 'graph')).toThrow('synapse_partner');
  expect(() => decodeSynapsePoints({ ...record, edge_counts: [{ ...record.edge_counts[0], source_pairs: 2 }] }, page, 'graph')).toThrow('synapse_edge');
  expect(() => decodeSynapsePoints({ ...record, pairs: [{ ...pair, x_pre: NaN }] }, page, 'graph')).toThrow('synapse_coordinate');
});
