import { act, renderHook, waitFor } from '@testing-library/react';
import useConnectomeData from '../../../src/features/simulator/connectome/useConnectomeData';
import { simulationApi } from '../../../src/features/simulator/api';
import { verifyConnectome } from '../../../src/features/simulator/connectome/connectomeData';
import { loadMorphologyLandmarks } from '../../../src/features/simulator/connectome/connectomeMorphology';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { artifacts: jest.fn(), readArtifact: jest.fn() } }));
jest.mock('../../../src/features/simulator/connectome/connectomeData', () => ({ verifyConnectome: jest.fn() }));
jest.mock('../../../src/features/simulator/connectome/connectomeMorphology', () => ({
  applyBodyViewCorrection: jest.fn(data => data), loadMorphologyLandmarks: jest.fn(),
}));
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
