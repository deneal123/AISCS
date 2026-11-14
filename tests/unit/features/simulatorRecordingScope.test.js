import { contactNormalsForSimulation, directFieldMatchesScene, directFieldTimeline, fieldExclusionNotice, fieldProxyActivityNotice, fieldProxyExplanation, fieldRecordingScope, fieldResultDescription, fieldResultHeading } from '../../../src/features/simulator/recording/recordingScope';

test('describes full-population recording without calling it a selected subset', () => {
  const run = { result: { manifest: { kind: 'experimental-full-population-feedback' } } };
  expect(fieldResultDescription(run, false)).toContain('всех клеток');
});

test('shows the physically recorded cell count only when it is explicitly available', () => {
  expect(fieldRecordingScope({ result: { preview: { source_cells: 46 } } }))
    .toBe('E1 − REF · клеток: 46');
  expect(fieldRecordingScope({ result: { preview: { source_cells: 0 } } }))
    .toBe('E1 − REF · выбранные клетки');
  expect(fieldRecordingScope(null)).toBe('E1 − REF · выбранные клетки');
});

test('direct network output never claims a physical E1–REF recording', () => {
  const run = { title: 'STIM', result: { preview: { source_cells: 46 } } };
  expect(fieldResultHeading(run, true)).toBe('Модельная активность ЦНС');
  expect(fieldResultDescription(run, true)).toContain('запись E1–REF не рассчитана');
  expect(fieldProxyExplanation(true)).toContain('Запись E1–REF в этом режиме не рассчитывается');
  expect(fieldResultHeading(run, false)).toBe('E1 − REF · клеток: 46');
  expect(fieldResultDescription(run, false)).toContain('запись выбранных клеток');
  expect(fieldProxyExplanation(false)).toContain('Запись E1–REF рассчитана отдельно для выбранных клеток');
});

test('explains excluded direct-field inputs without asserting an absent network response', () => {
  expect(fieldExclusionNotice({ direct_field_exclusions: 3, contact_exclusions: 27 }))
    .toContain('для 30 клеток');
  expect(fieldExclusionNotice({ direct_field_exclusions: 3, contact_exclusions: 27 }))
    .toContain('сетевой ответ может сохраняться');
  expect(fieldExclusionNotice({ direct_field_exclusions: 0, contact_exclusions: 0 })).toBeNull();
  expect(fieldExclusionNotice({ direct_field_exclusions: '3', contact_exclusions: 0 })).toBeNull();
  expect(fieldExclusionNotice(null)).toBeNull();
});

test('reports sensitivity context only with a verified event histogram', () => {
  const run = { configuration: { gain: 1000000 }, result: { preview: { neurons: 100, active_neurons: 70 } } };
  expect(fieldProxyActivityNotice(run, null)).toBeNull();
  expect(fieldProxyActivityNotice(run, [0, 60, 3])).toContain('максимум за 1 мс — 60');
  expect(fieldProxyActivityNotice(run, [0, 60, 3])).toContain('не измеренная физиологическая активность');
  expect(fieldProxyActivityNotice(run, [0, 101])).toBeNull();
  expect(fieldProxyActivityNotice(run, [0, NaN])).toBeNull();
  expect(fieldProxyActivityNotice({ ...run, configuration: {} }, [0, 60])).toBeNull();
});

test('a direct network timeline requires complete, consistent model inputs', () => {
  const run = { configuration: { waveform: [0, 1] }, result: { preview: { duration_ms: 2 } } };
  expect(directFieldTimeline(run)).toEqual({ time_ms: [0, 1, 2],
    stimulus_fraction: [0, 1], stimulus_time_ms: [0.5, 1.5] });
  expect(directFieldTimeline(null)).toBeNull();
  expect(directFieldTimeline({ configuration: {} })).toBeNull();
  expect(directFieldTimeline({ ...run, configuration: { waveform: [0] } })).toBeNull();
  expect(directFieldTimeline({ ...run, configuration: { waveform: [0, NaN] } })).toBeNull();
  expect(directFieldTimeline({ ...run, result: { preview: { duration_ms: 1001 } } })).toBeNull();
});

test('a direct result must match its scene and complete stimulus snapshot', () => {
  const simulation = { source_um: [1, 2, 3], return_um: [4, 5, 6], current_na: -300,
    conductivity_s_m: .3, clearance_um: 1, coordinate_frame: 'native', duration_ms: 10 };
  const field = { state: 'completed', parent_run_id: 'scene', configuration: { ...simulation,
    graph_manifest_sha256: 'graph' }, result: { manifest: { kind: 'experimental-field-proxy' },
    preview: { duration_ms: 10, recording: null } } };
  expect(directFieldMatchesScene(field, simulation, 'scene', 'graph')).toBe(true);
  expect(directFieldMatchesScene(field, null, 'scene', 'graph')).toBe(false);
  expect(directFieldMatchesScene(null, simulation, 'scene', 'graph')).toBe(false);
  expect(directFieldMatchesScene(field, simulation, 'other', 'graph')).toBe(false);
  expect(directFieldMatchesScene(field, simulation, 'scene', 'other')).toBe(false);
  expect(directFieldMatchesScene(field, { ...simulation, current_na: -200 }, 'scene', 'graph')).toBe(false);
  expect(directFieldMatchesScene(field, { ...simulation, source_um: [1, NaN, 3] }, 'scene', 'graph')).toBe(false);
  expect(directFieldMatchesScene({ ...field, result: { ...field.result,
    preview: { duration_ms: 10, recording: {} } } }, simulation, 'scene', 'graph')).toBe(false);
});

test('electrode normals are retained only for an identical four-contact placement', () => {
  const simulation = { source_um: [1, 2, 3], return_um: [4, 5, 6],
    electrode_um: [7, 8, 9], reference_um: [10, 11, 12] };
  const normals = { source_um: [0, 1, 0] }, draft = { simulation, normals };
  expect(contactNormalsForSimulation(draft, simulation)).toBe(normals);
  expect(contactNormalsForSimulation(draft, { ...simulation, reference_um: [10, 11, 13] })).toBeNull();
  expect(contactNormalsForSimulation(draft, { ...simulation, electrode_um: [7, 8, NaN] })).toBeNull();
  expect(contactNormalsForSimulation(null, simulation)).toBeNull();
  expect(contactNormalsForSimulation(draft, null)).toBeNull();
});
