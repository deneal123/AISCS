import { voltageProbeSegment } from '../../../src/features/simulator/recording/voltageProbeSegment';

test('marks only the hash-matched compartment and uses recorded samples', () => {
  const morphology = { sha256: 'hash', segmentsByChild: new Map([[9, { start: [0, 0, 0], end: [6, 3, 0] }]]) };
  const preview = { target_id: 20, probe_morphology_sha256: 'hash', time_ms: [0, 1, 2],
    probe_baseline_mv: [-65, -65, -65], probe_active_mv: [-65, -45, -60],
    voltage_probe: { child_node_id: 9, segment_index: 1, segments_per_edge: 3 } };
  expect(voltageProbeSegment(morphology, preview, '20', 1.5)).toEqual({
    positions: [2, 1, 0, 4, 2, 0], deltaMv: 20, sampleTimeMs: 1,
  });
  expect(voltageProbeSegment({ ...morphology, sha256: 'wrong' }, preview, '20', 1)).toBeNull();
  expect(voltageProbeSegment(morphology, preview, '21', 1)).toBeNull();
  expect(voltageProbeSegment(morphology, preview, '20', 3)).toBeNull();
  const rounded = { ...preview, time_ms: [0, 1.000000000001, 2] };
  expect(voltageProbeSegment(morphology, rounded, '20', 1).sampleTimeMs).toBe(1.000000000001);
});
