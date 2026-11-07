import { applyFieldGraphEvents } from '../../../src/features/simulator/field/fieldGraphEvents';

const fixture = () => {
  const ids = new BigUint64Array([1n, 2n, 3n]);
  const base = { node_ids: ids, positions_mm: new Float32Array(9), spike_neurons: new Int32Array([2]),
    spike_times_ms: new Float32Array([9]), counts: new Int32Array([0, 0, 1]),
    input_indices: new Int32Array([2]), description: { manifest_sha256: 'graph', scene: {} } };
  const buffer = new ArrayBuffer(40);
  new BigUint64Array(buffer, 0, 3).set(ids);
  new Int32Array(buffer, 24, 2).set([0, 1]);
  new Float32Array(buffer, 32, 2).set([2, 4]);
  const cells = [{ body_id: 1, child_node_id: 7, threshold_mv: -20 }];
  const config = { graph_manifest_sha256: 'graph', source_cells: cells, replay_ids: [2], seed: 1, acquisition: null,
    simulation: { duration_ms: 10, source_um: [1, 2, 3], electrode_um: [1, 2, 4], reference_um: [5, 6, 7],
      source_model: 'pointsource', coordinate_frame: 'male-cns-v1.0-native-um' }, synapse: { delay_ms: 2 } };
  const metadata = { configuration: { source_cells: cells, replay_ids: [2], seed: 1, acquisition: null,
    simulation_parameters: { source_um: [1, 2, 3], duration_ms: 10 }, schedule_parameters: { duration_ms: 10, delay_ms: 2 },
    recording: { source_model: 'pointsource', electrode_um: [1, 2, 4], reference_um: [5, 6, 7] } }, graph_description: { manifest_sha256: 'graph', duration_ms: 10,
    binary: { byte_order: 'little', bytes: 40, arrays: {
      node_ids: { dtype: '<u8', offset: 0, count: 3, shape: [3] },
      spike_neurons: { dtype: '<i4', offset: 24, count: 2, shape: [2] },
      spike_times_ms: { dtype: '<f4', offset: 32, count: 2, shape: [2] },
    } } } };
  return { base, buffer, metadata, config };
};

test('replaces the scene event journal with checked field-driven events', () => {
  const { base, buffer, metadata, config } = fixture();
  const result = applyFieldGraphEvents(base, buffer, metadata, config);
  expect([...result.spike_neurons]).toEqual([0, 1]);
  expect([...result.spike_times_ms]).toEqual([2, 4]);
  expect([...result.counts]).toEqual([1, 1, 0]);
  expect([...result.input_indices]).toEqual([0]);
  expect(result.description.spikes_outside_input_population).toBe(1);
  expect(result.positions_mm).toBe(base.positions_mm);
  expect([...base.spike_neurons]).toEqual([2]);
});

test('rejects foreign nodes, event times, and altered cell selection', () => {
  const first = fixture(); new BigUint64Array(first.buffer, 0, 3)[1] = 99n;
  expect(() => applyFieldGraphEvents(first.base, first.buffer, first.metadata, first.config)).toThrow('field_graph_nodes');
  const second = fixture(); new Float32Array(second.buffer, 32, 2)[1] = 1.5;
  expect(() => applyFieldGraphEvents(second.base, second.buffer, second.metadata, second.config)).toThrow('field_graph_events');
  const third = fixture(); third.metadata.configuration.source_cells = [];
  expect(() => applyFieldGraphEvents(third.base, third.buffer, third.metadata, third.config)).toThrow('field_graph_configuration');
});

test('requires the retained compartment-event option to agree with the saved configuration', () => {
  const { base, buffer, metadata, config } = fixture();
  config.retain_compartment_crossings = true;
  expect(() => applyFieldGraphEvents(base, buffer, metadata, config)).toThrow('field_graph_configuration');
  metadata.configuration.retain_compartment_crossings = true;
  expect(applyFieldGraphEvents(base, buffer, metadata, config).description.spikes).toBe(2);
  metadata.configuration.retain_compartment_crossings = false;
  expect(() => applyFieldGraphEvents(base, buffer, metadata, config)).toThrow('field_graph_configuration');
});
