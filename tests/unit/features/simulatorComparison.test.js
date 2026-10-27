import { createCameraLink } from '../../../src/features/simulator/sceneCamera';
import { comparisonIssue, comparisonSceneIssue, comparisonReference } from '../../../src/features/simulator/sceneModel';

const configuration = { model_id: 'local', duration_ms: 200, dt_ms: .025, placement: { registration: {
  mesh_asset_id: 'flybody', mesh_sha256: 'a'.repeat(64), region_id: 'thorax', origin_mm: [0, 0, 0],
} } };
const manifest = { contract_version: '1.0', units: { signal: 'uV', time: 'ms' },
  versions: { NEURON: '9' }, dynamics_cache: { engine: { schema: 'v2', solver: { source: 'one' } } }, operator: { source_sha256: 'recording' } };
const preview = { time_ms: [0, 100, 200], signal_uv: [0, 1, 0] };
const reference = { configuration, manifest, ...preview };

test('comparison checks nested solver identities and physical units independent of key order', () => {
  const reordered = { ...manifest, units: { time: 'ms', signal: 'uV' }, dynamics_cache: { engine: { solver: { source: 'one' }, schema: 'v2' } } };
  expect(comparisonIssue(reference, configuration, reordered, preview)).toBe('');
  expect(comparisonIssue(reference, configuration, { ...manifest, units: { ...manifest.units, signal: 'mV' } }, preview)).not.toBe('');
  expect(comparisonIssue(reference, configuration, { ...manifest, dynamics_cache: { engine: { schema: 'v2', solver: { source: 'other' } } } }, preview)).not.toBe('');
  expect(comparisonIssue(reference, configuration, { ...manifest, operator: { source_sha256: 'other' } }, preview)).not.toBe('');
  expect(comparisonIssue(reference, configuration, {}, preview)).not.toBe('');
});

test('comparison rejects shifted, shortened, unordered or nonfinite saved axes without resampling', () => {
  for (const time_ms of [[0, 99, 200], [0, 100], [0, 100, 199], [0, NaN, 200], [0, 201, 200]]) {
    expect(comparisonIssue(reference, configuration, manifest, { ...preview, time_ms })).not.toBe('');
  }
});

test('shared scenes require exact registered frames while a completed record alone can be pinned', () => {
  expect(comparisonSceneIssue(reference, configuration)).toBe('');
  expect(comparisonSceneIssue(reference, { ...configuration, placement: {} })).not.toBe('');
  expect(comparisonSceneIssue(reference, { ...configuration, placement: { registration: { ...configuration.placement.registration, origin_mm: [0, 0, 1] } } })).not.toBe('');
  expect(comparisonReference({ id: 'one', state: 'running', result: { preview } })).toBeNull();
  expect(comparisonReference({ id: 'one', state: 'completed', configuration, result: { preview, manifest } })).toEqual({ ...reference, run_id: 'one' });
});

test('camera broadcast excludes its owner, isolates snapshots and ignores duplicate or invalid poses', () => {
  const link = createCameraLink(), first = jest.fn(), second = jest.fn();
  link.subscribe('A', first);
  const unsubscribe = link.subscribe('B', second);
  const pose = { position: [1, 2, 3], target: [0, 0, 0] };
  link.publish(pose, 'A');
  expect(first).not.toHaveBeenCalled();
  expect(second).toHaveBeenCalledWith(pose);
  link.snapshot().position[0] = 999;
  second.mock.calls[0][0].target[0] = 999;
  expect(link.snapshot()).toEqual(pose);
  link.publish(pose, 'A');
  link.publish({ ...pose, position: [NaN, 0, 0] }, 'A');
  expect(second).toHaveBeenCalledTimes(1);
  unsubscribe();
  link.publish({ ...pose, position: [2, 3, 4] }, 'A');
  expect(second).toHaveBeenCalledTimes(1);
  link.reset(); expect(link.snapshot()).toBeNull();
});
