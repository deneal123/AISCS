import { act, renderHook, waitFor } from '@testing-library/react';
import useCnsOverview from '../../../src/features/simulator/connectome/useCnsOverview';
import { loadOverview } from '../../../src/features/simulator/connectome/cnsOverview';

jest.mock('../../../src/features/simulator/connectome/cnsOverview', () => ({ loadOverview: jest.fn() }));
beforeEach(() => jest.clearAllMocks());

test('retains verified chunks on failure and retries without duplication', async () => {
  const chunk = { cells: 4 };
  loadOverview.mockImplementationOnce((run, graph, signal, onChunk) => {
    onChunk(chunk);
    return Promise.reject(new Error('bad hash'));
  }).mockImplementationOnce((run, graph, signal, onChunk) => {
    onChunk(chunk);
    return Promise.resolve();
  });
  const hook = renderHook(() => useCnsOverview('run', 'graph'));
  await waitFor(() => expect(hook.result.current.error).toContain('проверить'));
  expect(hook.result.current.cells).toBe(4);
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  expect(hook.result.current.cells).toBe(4);
  expect(hook.result.current.chunks).toHaveLength(1);
  expect(hook.result.current.error).toBe('');
});

test('old graph chunks cannot reappear after switching records', async () => {
  let emitOld, finishOld;
  loadOverview.mockImplementationOnce((run, graph, signal, onChunk) => {
    emitOld = onChunk;
    return new Promise(resolve => { finishOld = resolve; });
  }).mockImplementationOnce((run, graph, signal, onChunk) => {
    onChunk({ cells: 2 });
    return Promise.resolve();
  });
  const hook = renderHook(({ run }) => useCnsOverview(run, 'graph'), { initialProps: { run: 'old' } });
  hook.rerender({ run: 'new' });
  await waitFor(() => expect(hook.result.current.cells).toBe(2));
  await act(async () => { emitOld({ cells: 100 }); finishOld(); });
  expect(hook.result.current.cells).toBe(2);
});

test('an old attempt cannot append chunks after a retry of the same graph', async () => {
  let emitOld, finishOld;
  loadOverview.mockImplementationOnce((run, graph, signal, onChunk) => {
    emitOld = onChunk;
    return new Promise(resolve => { finishOld = resolve; });
  }).mockImplementationOnce((run, graph, signal, onChunk) => {
    onChunk({ cells: 3 });
    return Promise.resolve();
  });
  const hook = renderHook(() => useCnsOverview('run', 'graph'));
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.cells).toBe(3));
  await act(async () => { emitOld({ cells: 100 }); finishOld(); });
  expect(hook.result.current.cells).toBe(3);
  expect(hook.result.current.chunks).toHaveLength(1);
});
