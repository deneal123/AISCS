import { act, renderHook, waitFor } from '@testing-library/react';
import useSelectedMorphology from '../../../src/features/simulator/connectome/useSelectedMorphology';
import { simulationApi } from '../../../src/features/simulator/api';
import { decodeSelectedMorphology } from '../../../src/features/simulator/connectome/selectedMorphology';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { morphology: jest.fn() } }));
jest.mock('../../../src/features/simulator/connectome/selectedMorphology', () => ({ decodeSelectedMorphology: jest.fn() }));

beforeEach(() => { jest.clearAllMocks(); decodeSelectedMorphology.mockImplementation(record => Promise.resolve(record)); });

test('changing the graph identity clears old morphology and ignores its late response', async () => {
  let finish;
  simulationApi.morphology.mockResolvedValueOnce('old').mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const hook = renderHook(({ manifest }) => useSelectedMorphology('run', '42', manifest), { initialProps: { manifest: 'old' } });
  await waitFor(() => expect(hook.result.current.data).toBe('old'));
  hook.rerender({ manifest: 'new' });
  expect(hook.result.current.data).toBeNull();
  await act(async () => { finish('new'); });
  await waitFor(() => expect(hook.result.current.data).toBe('new'));
  expect(decodeSelectedMorphology).toHaveBeenLastCalledWith('new', '42', 'new');
});

test('late response for a previous neuron cannot replace the current selection', async () => {
  let finish;
  simulationApi.morphology.mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce('current');
  const hook = renderHook(({ id }) => useSelectedMorphology('run', id, 'manifest'), { initialProps: { id: '42' } });
  const signal = simulationApi.morphology.mock.calls[0][2];
  hook.rerender({ id: '43' });
  await waitFor(() => expect(hook.result.current.data).toBe('current'));
  expect(signal.aborted).toBe(true);
  await act(async () => { finish('late'); });
  expect(hook.result.current.data).toBe('current');
});

test('missing source morphology is explicit and can be retried without fabricating geometry', async () => {
  simulationApi.morphology.mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce('verified');
  const hook = renderHook(() => useSelectedMorphology('run', '42', 'manifest'));
  await waitFor(() => expect(hook.result.current.error).toContain('недоступна'));
  expect(hook.result.current.data).toBeNull();
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.data).toBe('verified'));
  expect(hook.result.current.error).toBe('');
});

test('a failed checksum never leaves selected morphology on screen', async () => {
  simulationApi.morphology.mockResolvedValue('tampered');
  decodeSelectedMorphology.mockRejectedValue(new Error('morphology_hash'));
  const hook = renderHook(() => useSelectedMorphology('run', '42', 'manifest'));
  await waitFor(() => expect(hook.result.current.error).toContain('проверить'));
  expect(hook.result.current.data).toBeNull();
});
