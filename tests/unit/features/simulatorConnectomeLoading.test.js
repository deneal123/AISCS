import { act, renderHook, waitFor } from '@testing-library/react';
import useConnectomeData from '../../../src/features/simulator/useConnectomeData';
import { simulationApi } from '../../../src/features/simulator/api';
import { verifyConnectome } from '../../../src/features/simulator/connectomeData';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { artifacts: jest.fn(), readArtifact: jest.fn() } }));
jest.mock('../../../src/features/simulator/connectomeData', () => ({ verifyConnectome: jest.fn() }));
const description = { neurons: 166700 };
beforeEach(() => jest.clearAllMocks());

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
