import registry from '../../../public/assets/simulator/malecns/motor.json';
import { buildMotorReadout, motorAngleAtTime, causalOnsets, MOTOR_REGIONS } from '../../../src/features/simulator/scene/motorReadout';
import { responseSeries } from '../../../src/features/simulator/scene/sceneModel';

function fixture() {
  const data = { description: { dataset_id: registry.dataset_id, annotations_sha256: registry.annotations_sha256 },
    node_ids: BigUint64Array.from(registry.cells.map(cell => BigInt(cell.id))),
    spike_neurons: new Int32Array(), spike_times_ms: new Float32Array() };
  const left = registry.cells.findIndex(cell => cell.region === 'front_left');
  const right = registry.cells.findIndex(cell => cell.region === 'hind_right');
  data.spike_neurons = new Int32Array([left, right]);
  data.spike_times_ms = new Float32Array([38, 42]);
  return { data, left, right };
}

test('each limb cue starts at its actual motor event, never at the earlier HH spike or future event', () => {
  const { data } = fixture(), readout = buildMotorReadout(registry, data);
  expect(readout.active).toBe(2); expect(readout.first).toBe(38);
  for (const region of MOTOR_REGIONS) expect(motorAngleAtTime(readout, region, 34.1)).toBe(0);
  expect(motorAngleAtTime(readout, 'front_left', 38)).toBeGreaterThan(0);
  expect(motorAngleAtTime(readout, 'hind_right', 38)).toBe(0);
  expect(motorAngleAtTime(readout, 'hind_right', 42)).toBeGreaterThan(0);
  expect(motorAngleAtTime(readout, 'front_left', 62)).toBe(0);
  expect(motorAngleAtTime(null, 'front_left', 38)).toBe(0);
});

test('foreign or incomplete motor annotations do not silently drive an animation', () => {
  const { data } = fixture();
  expect(() => buildMotorReadout({ ...registry, dataset_id: 'other' }, data)).toThrow('identity');
  expect(() => buildMotorReadout({ ...registry, cells: registry.cells.slice(1) }, data)).toThrow('identity');
  const cells = registry.cells.map(cell => ({ ...cell }));
  cells[0].soma_side = cells[0].soma_side === 'L' ? 'R' : 'L';
  expect(() => buildMotorReadout({ ...registry, cells }, data)).toThrow('population');
  expect(() => buildMotorReadout(registry, { ...data, node_ids: data.node_ids.slice(1) })).toThrow('population');
});

test('whole-CNS motion trace and scene share motor events and have no HH fallback', () => {
  const { data } = fixture(), readout = buildMotorReadout(registry, data);
  const preview = { connectome: {}, time_ms: [34.1, 38, 42], spikes: [{ cell_id: 0, time_ms: 34.1 }],
    visualization: { reaction: { window_ms: 24, decay_ms: 8, normalization: 3, max_angle_rad: .25 } } };
  const series = responseSeries(preview, undefined, readout);
  expect(series.motionAvailable).toBe(true);
  expect(series.motionDegrees[0]).toBe(0);
  expect(series.motionDegrees[1]).toBeCloseTo(motorAngleAtTime(readout, 'front_left', 38) * 180 / Math.PI);
  expect(responseSeries(preview).motionAvailable).toBe(false);
  expect(responseSeries(preview).motionDegrees).toEqual([0, 0, 0]);
  const quiet = buildMotorReadout(registry, { ...data, spike_neurons: [], spike_times_ms: [] });
  expect(quiet.first).toBe(Infinity);
  for (const region of MOTOR_REGIONS) expect(motorAngleAtTime(quiet, region, 100)).toBe(0);
});

test('onset summary distinguishes input, downstream and motor events including a silent record', () => {
  const data = { input_indices: new Int32Array([2]), spike_neurons: new Int32Array([2, 1, 2]), spike_times_ms: new Float32Array([30, 32, 35]) };
  expect(causalOnsets(data, { first: 38 })).toEqual({ input: 30, network: 32, motor: 38 });
  expect(causalOnsets({ ...data, spike_neurons: [], spike_times_ms: [] }, { first: Infinity })).toEqual({ input: null, network: null, motor: null });
  expect(causalOnsets(null, null)).toBeNull();
});
