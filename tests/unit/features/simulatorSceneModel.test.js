import { placementIssue, reactionAtTime, comparisonIssue, inputEventsAtTime, responseSeries } from '../../../src/features/simulator/sceneModel';

const contact = (x, y, z) => ({ x_um: x, y_um: y, z_um: z });
const geometry = { starts_um: [[0, 0, -1]], ends_um: [[0, 0, 1]], diameters_um: [2] };

test('placement rejects source intersection, coincident reference and invalid drafts', () => {
  const placement = { electrode: contact(10, 0, 0), reference: contact(20, 0, 0) };
  expect(placementIssue(placement, geometry)).toBe('');
  expect(placementIssue({ ...placement, electrode: contact(0, 0, 0) }, geometry)).toContain('пересекает');
  expect(placementIssue({ ...placement, reference: placement.electrode }, geometry)).toContain('разных');
  expect(placementIssue({ ...placement, electrode: contact('', 0, 0) }, geometry)).toContain('координаты');
});

test('reaction follows recorded neural events, never the stimulus class', () => {
  const preview = { spikes: [{ cell_id: 0, time_ms: 25 }],
    visualization: { reaction: { window_ms: 24, decay_ms: 8, normalization: 3, max_angle_rad: .25 } } };
  expect(reactionAtTime(preview, 24)).toBe(0);
  expect(reactionAtTime(preview, 25)).toBeGreaterThan(0);
  expect(reactionAtTime({ ...preview, stimulus: 'none' }, 25)).toBe(reactionAtTime({ ...preview, stimulus: 'strong' }, 25));
  expect(reactionAtTime(preview, 60)).toBe(0);
  expect(reactionAtTime(null, 25)).toBe(0);
});

test('comparison permits electrode changes but rejects incompatible time grids', () => {
  const configuration = { model_id: 'local', duration_ms: 200, dt_ms: .025 };
  const manifest = { contract_version: '1.0', units: { signal: 'uV' }, versions: { solver: 'v1' }, dynamics_cache: { engine: { source: 'one' } }, operator: { source_sha256: 'operator' } };
  expect(comparisonIssue({ configuration, manifest }, { ...configuration, placement: {} }, manifest)).toBe('');
  expect(comparisonIssue({ configuration }, { ...configuration, duration_ms: 100 })).not.toBe('');
});

test('legacy missing input journal differs from an explicitly zero input', () => {
  const preview = { input_events: [{ cell_id: 0, time_ms: 25, weight_us: 0 }] };
  expect(inputEventsAtTime({}, 25)).toBeNull();
  expect(inputEventsAtTime(preview, 25)).toEqual([]);
  expect(responseSeries({}).inputEvents).toBeNull();
  expect(responseSeries(preview).inputEvents).toEqual(preview.input_events);
});

test('input cue and motion series use recorded events and one model clock', () => {
  const preview = { time_ms: [24, 25, 26, 60], input_events: [{ cell_id: 1, time_ms: 25, weight_us: .004 }],
    spikes: [{ cell_id: 0, time_ms: 26 }], visualization: { reaction: { window_ms: 24, decay_ms: 8, normalization: 3, max_angle_rad: .25 } } };
  expect(inputEventsAtTime(preview, 24)).toEqual([]);
  expect(inputEventsAtTime(preview, 25)).toEqual(preview.input_events);
  expect(inputEventsAtTime(preview, 28)).toEqual([]);
  const series = responseSeries(preview);
  expect(series.motionDegrees[0]).toBe(0);
  expect(series.motionDegrees[1]).toBe(0);
  expect(series.motionDegrees[2]).toBeCloseTo(reactionAtTime(preview, 26) * 180 / Math.PI);
  expect(series.motionDegrees[3]).toBe(0);
  expect(responseSeries({ ...preview, stimulus: 'strong' })).toEqual(responseSeries({ ...preview, stimulus: 'none' }));
});
