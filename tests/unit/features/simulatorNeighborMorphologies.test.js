import { act, renderHook, waitFor } from '@testing-library/react';
import useNeighborMorphologies from '../../../src/features/simulator/connectome/useNeighborMorphologies';
import { simulationApi } from '../../../src/features/simulator/api';
import { decodeSelectedMorphology } from '../../../src/features/simulator/connectome/selectedMorphology';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { morphology: jest.fn() } }));
jest.mock('../../../src/features/simulator/connectome/selectedMorphology', () => ({ decodeSelectedMorphology: jest.fn() }));

beforeEach(() => { jest.clearAllMocks(); decodeSelectedMorphology.mockImplementation(record => Promise.resolve(record)); });

test('loads the current page from verified source geometry and reports unavailable cells', async () => {
  simulationApi.morphology.mockResolvedValueOnce({ vertices: 2, positions: new Float32Array([1, 2, 3, 4, 5, 6]) })
    .mockRejectedValueOnce(new Error('unavailable'));
  const page = { nodeId: '1', items: [{ target_id: '2' }, { target_id: '3' }] };
  const hook = renderHook(() => useNeighborMorphologies('run', page, 'graph'));
  await waitFor(() => expect(hook.result.current.data).not.toBeNull());
  expect(hook.result.current).toMatchObject({ loaded: 1, total: 2, unavailable: 1 });
  expect([...hook.result.current.data.positions]).toEqual([1, 2, 3, 4, 5, 6]);
});

test('late response from an old page cannot be drawn after selection changes', async () => {
  let finish;
  simulationApi.morphology.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce({ vertices: 1, positions: new Float32Array([7, 8, 9]) });
  const old = { nodeId: '1', items: [{ target_id: '2' }] };
  const current = { nodeId: '3', items: [{ target_id: '4' }] };
  const hook = renderHook(({ page }) => useNeighborMorphologies('run', page, 'graph'), { initialProps: { page: old } });
  const signal = simulationApi.morphology.mock.calls[0][2];
  hook.rerender({ page: current });
  await waitFor(() => expect(hook.result.current.loaded).toBe(1));
  expect(signal.aborted).toBe(true);
  await act(async () => { finish({ vertices: 1, positions: new Float32Array([1, 2, 3]) }); });
  expect([...hook.result.current.data.positions]).toEqual([7, 8, 9]);
});

test('rendering budget omissions are distinct from download failures', async () => {
  simulationApi.morphology.mockResolvedValue({ vertices: 300001, positions: new Float32Array(0) });
  const page = { nodeId: '1', items: [{ target_id: '2' }] };
  const hook = renderHook(() => useNeighborMorphologies('run', page, 'graph'));
  await waitFor(() => expect(hook.result.current.data).not.toBeNull());
  expect(hook.result.current).toMatchObject({ loaded: 0, total: 1, unavailable: 0, omitted: 1 });
});

test('verified neighbors appear before a later slow request finishes', async () => {
  let finish;
  const cell = { vertices: 1, positions: new Float32Array([1, 2, 3]) };
  simulationApi.morphology.mockResolvedValueOnce(cell).mockResolvedValueOnce(cell)
    .mockResolvedValueOnce(cell).mockResolvedValueOnce(cell)
    .mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const page = { nodeId: '1', items: ['2', '3', '4', '5', '6'].map(target_id => ({ target_id })) };
  const hook = renderHook(() => useNeighborMorphologies('run', page, 'graph'));
  await waitFor(() => expect(hook.result.current.loaded).toBe(4));
  expect(hook.result.current.loading).toBe(true);
  await act(async () => { finish(cell); });
  await waitFor(() => expect(hook.result.current.loaded).toBe(5));
  expect(hook.result.current.loading).toBe(false);
});

test('batch requests are concurrent and scene budget follows page order, not response timing', async () => {
  const resolve = {};
  simulationApi.morphology.mockImplementation((run, id) => new Promise(done => { resolve[id] = done; }));
  const page = { nodeId: '1', items: ['2', '3', '4', '5'].map(target_id => ({ target_id })) };
  const hook = renderHook(() => useNeighborMorphologies('run', page, 'graph'));
  await waitFor(() => expect(simulationApi.morphology).toHaveBeenCalledTimes(4));
  await act(async () => {
    ['5', '4', '3', '2'].forEach(id => resolve[id]({ vertices: 100000, positions: new Float32Array([Number(id), 0, 0]) }));
  });
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  expect(hook.result.current).toMatchObject({ loaded: 3, omitted: 1, unavailable: 0 });
  expect(hook.result.current.data.ranges.map(range => range.id)).toEqual(['2', '3', '4']);
});
