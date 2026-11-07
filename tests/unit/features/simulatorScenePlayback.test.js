import { scenePlayback } from '../../../src/features/simulator/recording/scenePlayback';

test('fast whole-network playback contains real model events but no E1–REF recording', () => {
  const run = { configuration: { waveform: [0, 1, 0], current_na: -300 }, result: {
    manifest: { kind: 'experimental-field-proxy' },
    preview: { duration_ms: 3, spikes_by_ms: [0, 2, 1, 0] },
  } };
  const actual = scenePlayback({ activeField: run, sceneField: run, direct: true, verifiedProxyHistogram: [0, 2, 1, 0] });
  expect(actual.time_ms).toEqual([0, 1, 2, 3]);
  expect(actual.signal_uv).toBeNull();
  expect(actual.stimulus_fraction).toEqual([0, 1, 0]);
  expect(actual.stimulus_time_ms).toEqual([.5, 1.5, 2.5]);
  expect(actual.stimulus_current_na).toBe(-300);
  expect(actual.connectome.spikes_by_ms).toEqual([0, 2, 1, 0]);
  expect(actual.networkOnly).toBe(true);
});

test('recording playback uses the selected physical trace and the same network as the scene', () => {
  const activeField = { id: 'source' };
  const activeFieldPreview = { time_ms: [0, 1, 2], neural_uv: [0, .4, -.2],
    stimulus_fraction: [0, 1, 0], network_spikes_by_ms: [0, 3, 0] };
  const sceneField = { result: { manifest: { kind: 'experimental-field-proxy' },
    preview: { spikes_by_ms: [0, 1, 2] } } };
  const activeFieldConfig = { simulation: { current_na: -300, duration_ms: 2 } };
  const actual = scenePlayback({ activeField, activeFieldPreview, activeFieldConfig, sceneField, verifiedProxyHistogram: [0, 1, 2] });
  expect(actual.time_ms).toEqual([0, 1, 2]);
  expect(actual.signal_uv).toEqual([0, .4, -.2]);
  expect(actual.stimulus_current_na).toBe(-300);
  expect(actual.connectome.spikes_by_ms).toEqual([0, 1, 2]);
});

test('a proxy preview is not displayed as verified network activity before artifact verification', () => {
  const run = { configuration: { waveform: [0, 1], current_na: -300 }, result: {
    manifest: { kind: 'experimental-field-proxy' }, preview: { duration_ms: 2, spikes_by_ms: [0, 50, 0] },
  } };
  expect(scenePlayback({ activeField: run, sceneField: run, direct: true }).connectome.spikes_by_ms).toBeNull();
  expect(scenePlayback({ activeField: run, sceneField: run, direct: true,
    verifiedProxyHistogram: [0, 2, 0] }).connectome.spikes_by_ms).toEqual([0, 2, 0]);
});

test('a changed contact draft hides the previous trace until the next calculation', () => {
  const preview = { time_ms: [0, 1], signal_uv: [0, 2] };
  expect(scenePlayback({ fieldContactDraft: {}, preview })).toBeNull();
  expect(scenePlayback({ fieldContactDraft: null, preview })).toBe(preview);
});

test('incomplete or malformed outputs cannot create a playable trace', () => {
  const run = { configuration: { waveform: [1] }, result: { preview: { duration_ms: 2 } } };
  expect(scenePlayback({ activeField: run, direct: true })).toBeNull();
  expect(scenePlayback({ activeField: {}, activeFieldPreview: { time_ms: [0, 1],
    neural_uv: [0, NaN] } })).toBeNull();
  expect(scenePlayback({ preview: { time_ms: [0, 1], signal_uv: [0] } })).toBeNull();
  expect(scenePlayback({})).toBeNull();
});

test('an additional recording keeps its own sample grid and the original stimulus grid', () => {
  const activeField = { id: 'source' };
  const activeFieldPreview = { time_ms: [0, 1, 2], stimulus_fraction: [0, 1, 0] };
  const activeTarget = { time_ms: [0, .5, 1, 1.5, 2], neural_uv: [0, 1, 2, 1, 0] };
  const actual = scenePlayback({ activeField, activeFieldPreview, activeTarget });
  expect(actual.time_ms).toEqual(activeTarget.time_ms);
  expect(actual.signal_uv).toEqual(activeTarget.neural_uv);
  expect(actual.stimulus_time_ms).toEqual(activeFieldPreview.time_ms);
  expect(actual.stimulus_fraction).toEqual(activeFieldPreview.stimulus_fraction);
});
