import { act, renderHook, waitFor } from '@testing-library/react';
import useConnectomeData from '../../../src/features/simulator/connectome/useConnectomeData';
import { simulationApi } from '../../../src/features/simulator/api';
import { verifyConnectome } from '../../../src/features/simulator/connectome/connectomeData';
import { loadMorphologyLandmarks } from '../../../src/features/simulator/connectome/connectomeMorphology';
import { verifyFieldProxyEvents } from '../../../src/features/simulator/field/fieldProxyEvents';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { artifacts: jest.fn(), readArtifact: jest.fn() } }));
jest.mock('../../../src/features/simulator/connectome/connectomeData', () => ({ verifyConnectome: jest.fn() }));
jest.mock('../../../src/features/simulator/connectome/connectomeMorphology', () => ({
  applyBodyViewCorrection: jest.fn(data => data), loadMorphologyLandmarks: jest.fn(),
}));
jest.mock('../../../src/features/simulator/field/fieldProxyEvents', () => ({ verifyFieldProxyEvents: jest.fn() }));
const description = { neurons: 166700 };
beforeEach(() => { jest.clearAllMocks(); loadMorphologyLandmarks.mockImplementation(data => Promise.resolve(data)); });

test('late whole-network download cannot replace another selected experiment', async () => {
  let finish;
  const old = new Promise(resolve => { finish = resolve; });
  simulationApi.artifacts.mockImplementation(id => Promise.resolve({ items: [{ id: id + '-file', name: 'connectome.bin' }] }));
  simulationApi.readArtifact.mockReturnValueOnce(old).mockResolvedValueOnce('new-buffer');
  verifyConnectome.mockImplementation(buffer => Promise.resolve(buffer));
  const hook = renderHook(({ id }) => useConnectomeData(id, description), { initialProps: { id: 'old' } });
  await waitFor(() => expect(simulationApi.readArtifact).toHaveBeenCalledTimes(1));
  const signal = simulationApi.readArtifact.mock.calls[0][2];
  hook.rerender({ id: 'new' });
  await waitFor(() => expect(hook.result.current.data).toBe('new-buffer'));
  expect(signal.aborted).toBe(true);
  await act(async () => { finish('old-buffer'); });
  expect(hook.result.current.data).toBe('new-buffer');
});

test('unavailable network has read-only retry and does not fabricate a local replacement', async () => {
  simulationApi.artifacts.mockRejectedValueOnce(new Error('private')).mockResolvedValueOnce({ items: [{ id: 'file', name: 'connectome.bin' }] });
  simulationApi.readArtifact.mockResolvedValueOnce('verified'); verifyConnectome.mockResolvedValueOnce('verified');
  const hook = renderHook(() => useConnectomeData('owned', description));
  await waitFor(() => expect(hook.result.current.error).toContain('Не удалось'));
  expect(hook.result.current.data).toBeNull(); expect(hook.result.current.error).not.toContain('private');
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.data).toBe('verified'));
});

test('an already displayed graph is cleared immediately when the selected record changes', async () => {
  let finish;
  simulationApi.artifacts.mockResolvedValue({ items: [{ id: 'file', name: 'connectome.bin' }] });
  simulationApi.readArtifact.mockResolvedValueOnce('old-buffer').mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  verifyConnectome.mockImplementation(buffer => Promise.resolve(buffer));
  const hook = renderHook(({ id }) => useConnectomeData(id, description), { initialProps: { id: 'old' } });
  await waitFor(() => expect(hook.result.current.data).toBe('old-buffer'));
  hook.rerender({ id: 'new' });
  expect(hook.result.current.data).toBeNull();
  await act(async () => { finish('new-buffer'); });
  await waitFor(() => expect(hook.result.current.data).toBe('new-buffer'));
});

test('missing morphology is an explicit recoverable defect, without losing the verified graph', async () => {
  simulationApi.artifacts.mockResolvedValue({ items: [{ id: 'file', name: 'connectome.bin' }] });
  simulationApi.readArtifact.mockResolvedValue('raw'); verifyConnectome.mockResolvedValue('verified');
  loadMorphologyLandmarks.mockRejectedValueOnce(new Error('skeleton checksum')).mockResolvedValueOnce('restored');
  const hook = renderHook(() => useConnectomeData('owned', description));
  await waitFor(() => expect(hook.result.current.morphologyError).toContain('морфологии'));
  expect(hook.result.current.data).toBe('verified');
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.data).toBe('restored'));
  expect(hook.result.current.morphologyError).toBe('');
});

test('changing the response reuses only the verified base and verifies each response independently', async () => {
  const base = { node_ids: [1], scene: 'base' };
  const files = [{ id: 'event', name: 'network-events.bin' },
    { id: 'meta', name: 'metadata.json' }, { id: 'control', name: 'network-control-events.bin' }];
  simulationApi.artifacts.mockImplementation(id => Promise.resolve({ items: id === 'scene'
    ? [{ id: 'base', name: 'connectome.bin' }] : files }));
  simulationApi.readArtifact.mockImplementation((id, file) => Promise.resolve(`${id}-${file}`));
  verifyConnectome.mockResolvedValue(base);
  verifyFieldProxyEvents.mockImplementation((graph, events, artifact, meta, metaFile, run) =>
    Promise.resolve({ ...graph, response: run.id }));
  const response = id => ({ id, result: { manifest: { kind: 'experimental-field-proxy' } } });
  const first = response('first'), second = response('second');
  const hook = renderHook(({ field }) => useConnectomeData('scene', description, field),
    { initialProps: { field: first } });
  await waitFor(() => expect(hook.result.current.data?.response).toBe('first'));
  hook.rerender({ field: second });
  await waitFor(() => expect(hook.result.current.data?.response).toBe('second'));
  expect(verifyConnectome).toHaveBeenCalledTimes(1);
  expect(loadMorphologyLandmarks).toHaveBeenCalledTimes(1);
  expect(verifyFieldProxyEvents).toHaveBeenCalledTimes(2);
  expect(verifyFieldProxyEvents.mock.calls[1][0]).toBe(base);
  expect(simulationApi.artifacts.mock.calls.filter(([id]) => id === 'scene')).toHaveLength(1);
});

test('late response verification cannot replace the newly selected response', async () => {
  let finish;
  simulationApi.artifacts.mockImplementation(id => Promise.resolve({ items: id === 'scene'
    ? [{ id: 'base', name: 'connectome.bin' }]
    : [{ id: 'event', name: 'network-events.bin' }, { id: 'meta', name: 'metadata.json' },
      { id: 'control', name: 'network-control-events.bin' }] }));
  simulationApi.readArtifact.mockResolvedValue('bytes');
  verifyConnectome.mockResolvedValue({ node_ids: [1] });
  verifyFieldProxyEvents.mockImplementation((base, events, file, meta, metaFile, run) =>
    run.id === 'first' ? new Promise(resolve => { finish = resolve; })
      : Promise.resolve({ ...base, response: run.id }));
  const response = id => ({ id, result: { manifest: { kind: 'experimental-field-proxy' } } });
  const hook = renderHook(({ field }) => useConnectomeData('scene', description, field),
    { initialProps: { field: response('first') } });
  await waitFor(() => expect(finish).toBeDefined());
  hook.rerender({ field: response('second') });
  await waitFor(() => expect(hook.result.current.data?.response).toBe('second'));
  await act(async () => { finish({ response: 'first' }); });
  expect(hook.result.current.data.response).toBe('second');
  expect(verifyConnectome).toHaveBeenCalledTimes(1);
});

test('invalid response retains verified anatomy without replaying the base run events', async () => {
  const base = { node_ids: [1, 2], description: { spikes: 1, active_neurons: 1, input_neurons: 1 },
    spike_neurons: Int32Array.of(1), spike_times_ms: Float32Array.of(5),
    input_indices: Int32Array.of(1), counts: Int32Array.of(0, 1) };
  simulationApi.artifacts.mockImplementation(id => Promise.resolve({ items: id === 'scene'
    ? [{ id: 'base', name: 'connectome.bin' }]
    : [{ id: 'event', name: 'network-events.bin' }, { id: 'meta', name: 'metadata.json' },
      { id: 'control', name: 'network-control-events.bin' }] }));
  simulationApi.readArtifact.mockResolvedValue('bytes');
  verifyConnectome.mockResolvedValue(base);
  verifyFieldProxyEvents.mockRejectedValue(new Error('field_proxy_checksum'));
  const field = { id: 'bad-response', result: { manifest: { kind: 'experimental-field-proxy' } } };
  const hook = renderHook(() => useConnectomeData('scene', description, field));
  await waitFor(() => expect(hook.result.current.error).toContain('Показана только структура ЦНС'));
  const displayed = hook.result.current.data;
  expect(displayed.node_ids).toBe(base.node_ids);
  expect(displayed.spike_neurons).toHaveLength(0);
  expect(displayed.spike_times_ms).toHaveLength(0);
  expect(displayed.input_indices).toHaveLength(0);
  expect(Array.from(displayed.counts)).toEqual([0, 0]);
  expect(displayed.description.response_unavailable).toBe(true);
  expect(base.spike_neurons).toHaveLength(1);
});
