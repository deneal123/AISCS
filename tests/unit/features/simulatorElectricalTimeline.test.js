import { electricalSpikeHistogram, sceneSpikeHistogram, verifiedHistogramForScene } from '../../../src/features/simulator/recording/electricalTimeline';

test('bins verified events on the same millisecond time base, including the final endpoint', () => {
  const readout = { source: { spike_times_ms: Float32Array.from([1, 1, 3, 10]) } };
  expect(electricalSpikeHistogram(readout, 10)).toEqual([0, 2, 0, 1, 0, 0, 0, 0, 0, 0, 1]);
});

test('the timeline uses the same network result as the scene, including a zero response', () => {
  const scene = { result: { manifest: { kind: 'experimental-field-proxy' }, preview: { spikes_by_ms: [0, 3, 0] } } };
  expect(sceneSpikeHistogram(scene, [0, 0, 5], null, 2)).toBeNull();
  expect(sceneSpikeHistogram(scene, [0, 0, 5], null, 2, [0, 3, 0])).toEqual([0, 3, 0]);
  scene.result.preview.spikes_by_ms = [0, 0, 0];
  expect(sceneSpikeHistogram(scene, [0, 0, 5], null, 2, [0, 0, 0])).toEqual([0, 0, 0]);
  delete scene.result.preview.spikes_by_ms;
  expect(sceneSpikeHistogram(scene, [0, 0, 5], null, 2)).toBeNull();
  expect(sceneSpikeHistogram(null, [0, 0, 5], null, 2)).toEqual([0, 0, 5]);
});

test('distinguishes an empty verified response from a missing or invalid stream', () => {
  expect(electricalSpikeHistogram({ source: { spike_times_ms: new Float32Array() } }, 2)).toEqual([0, 0, 0]);
  expect(electricalSpikeHistogram(null, 2)).toBeNull();
  expect(electricalSpikeHistogram({ source: { spike_times_ms: [3] } }, 2)).toBeNull();
  expect(electricalSpikeHistogram({ source: { spike_times_ms: [NaN] } }, 2)).toBeNull();
});

test('verification belongs only to the exact response and graph currently shown', () => {
  const field = { id: 'field' }, description = { manifest_sha256: 'graph' };
  const state = { runId: 'scene', fieldRun: field, description, histogram: [0, 1] };
  expect(verifiedHistogramForScene(state, 'scene', field, description)).toEqual([0, 1]);
  expect(verifiedHistogramForScene(state, 'other', field, description)).toBeNull();
  expect(verifiedHistogramForScene(state, 'scene', { id: 'field' }, description)).toBeNull();
  expect(verifiedHistogramForScene(state, 'scene', field, { manifest_sha256: 'graph' })).toBeNull();
  expect(verifiedHistogramForScene(state, 'scene', null, description)).toBeNull();
});
