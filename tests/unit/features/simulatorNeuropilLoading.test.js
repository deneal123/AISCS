import { act, renderHook, waitFor } from '@testing-library/react';
import useNeuropil from '../../../src/features/simulator/connectome/useNeuropil';
import { loadNeuropil } from '../../../src/features/simulator/connectome/neuropil';

jest.mock('../../../src/features/simulator/connectome/neuropil', () => ({ loadNeuropil: jest.fn() }));

beforeEach(() => jest.resetAllMocks());

test('loads only when enabled and publishes verified batches', async () => {
  loadNeuropil.mockImplementation(async (run, graph, signal, publish) => { publish([{ id: '1' }]); });
  const hook = renderHook(({ enabled }) => useNeuropil('run', 'graph', enabled), { initialProps: { enabled: false } });
  expect(loadNeuropil).not.toHaveBeenCalled();
  hook.rerender({ enabled: true });
  await waitFor(() => expect(hook.result.current).toMatchObject({ loading: false, meshes: [{ id: '1' }] }));
  hook.rerender({ enabled: false });
  expect(hook.result.current.meshes).toEqual([]);
});

test('ignores late responses after changing the run', async () => {
  let publishOld, finishOld;
  loadNeuropil.mockImplementationOnce((run, graph, signal, publish) => {
    publishOld = publish; return new Promise(resolve => { finishOld = resolve; });
  }).mockImplementationOnce(async (run, graph, signal, publish) => { publish([{ id: 'new' }]); });
  const hook = renderHook(({ run }) => useNeuropil(run, 'graph', true), { initialProps: { run: 'old' } });
  hook.rerender({ run: 'new' });
  await waitFor(() => expect(hook.result.current.meshes).toEqual([{ id: 'new' }]));
  await act(async () => { publishOld([{ id: 'old' }]); finishOld(); });
  expect(hook.result.current.meshes).toEqual([{ id: 'new' }]);
});
