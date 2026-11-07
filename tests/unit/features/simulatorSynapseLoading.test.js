import { act, renderHook, waitFor } from '@testing-library/react';
import useSynapsePoints from '../../../src/features/simulator/connectome/useSynapsePoints';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { synapses: jest.fn() } }));

const page = id => ({ nodeId: id, direction: 'outgoing', offset: 0, items: [] });
const record = id => ({ body_id: id, direction: 'outgoing', graph_manifest_sha256: 'graph', graph_offset: 0,
  coordinate_frame: 'male-cns-v1.0-native-8nm', source_md5: '58efcf712f8c4d4de5f2ad51e97def76',
  counts_match: true, total: 0, returned: 0, truncated: false, pairs: [], edge_counts: [] });

beforeEach(() => jest.clearAllMocks());

test('late data from the previous selection is discarded', async () => {
  let finish;
  simulationApi.synapses.mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(record('2'));
  const first = page('1'), second = page('2');
  const hook = renderHook(({ selected }) => useSynapsePoints('run', selected, 'graph'), { initialProps: { selected: first } });
  const signal = simulationApi.synapses.mock.calls[0][4];
  hook.rerender({ selected: second });
  await waitFor(() => expect(hook.result.current.data?.total).toBe(0));
  expect(signal.aborted).toBe(true);
  await act(async () => { finish(record('1')); });
  expect(hook.result.current.data?.total).toBe(0);
});

test('unavailable data stays empty and retry reloads it', async () => {
  simulationApi.synapses.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(record('1'));
  const selected = page('1');
  const hook = renderHook(() => useSynapsePoints('run', selected, 'graph'));
  await waitFor(() => expect(hook.result.current.error).toBe(true));
  expect(hook.result.current.data).toBeNull();
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.data?.total).toBe(0));
});
