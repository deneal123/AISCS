import { stimulusSeries, targetTimeline } from '../../../src/features/simulator/recording/targetTimeline';

test('only overlays a compatible saved source on the same time grid', () => {
  const source = { id: 'source', configuration: { source_ids: [1, 2], graph_manifest_sha256: 'graph' }, result: { preview: { time_ms: [0, 1] } } };
  const preview = { time_ms: [0, 1], neural_uv: [1, 2], source_cells: 2, target_id: 3 };
  const target = { parent_run_id: 'source', state: 'completed', configuration: { target_id: 3, graph_manifest_sha256: 'graph' }, result: { preview } };
  expect(targetTimeline(source, target)).toBe(preview);
  expect(targetTimeline({ ...source, id: 'other' }, target)).toBeNull();
  expect(targetTimeline(source, { ...target, state: 'running' })).toBeNull();
  expect(targetTimeline(source, { ...target, configuration: { ...target.configuration, graph_manifest_sha256: 'other' } })).toBeNull();
  expect(targetTimeline(source, { ...target, result: { preview: { ...preview, time_ms: [0, 2] } } })).toBeNull();
  expect(targetTimeline(source, { ...target, result: { preview: { ...preview, neural_uv: [NaN, 2] } } })).toBeNull();
  const distinctGrid = { ...preview, time_ms: [0, .5, 1], neural_uv: [1, 3, 2] };
  expect(targetTimeline(source, { ...target, result: { preview: distinctGrid } })).toBe(distinctGrid);
  const roundedEndpoint = { ...preview, time_ms: [0, 1 - 5e-9] };
  expect(targetTimeline(source, { ...target, result: { preview: roundedEndpoint } })).toBe(roundedEndpoint);
  const outsideTolerance = { ...preview, time_ms: [0, 1 - 2e-8] };
  expect(targetTimeline(source, { ...target, result: { preview: outsideTolerance } })).toBeNull();
  expect(targetTimeline({ ...source, result: { preview: { time_ms: [0, NaN, 1] } } }, target)).toBeNull();
  expect(targetTimeline({ ...source, result: { preview: { time_ms: [0, .7, .6, 1] } } }, target)).toBeNull();
  expect(stimulusSeries({ time_ms: [0, 1], stimulus_fraction: [0, 1] })).toEqual({ time_ms: [0, 1], values: [0, 1] });
  expect(stimulusSeries({ time_ms: [0, 0], stimulus_fraction: [0, 1] })).toBeNull();
});
