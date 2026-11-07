import { act, renderHook, waitFor } from '@testing-library/react';
import useWholeNetworkProxy, { EXPERIMENTAL_FIELD_GAIN } from '../../../src/features/simulator/recording/useWholeNetworkProxy';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  fieldProxyRuns: jest.fn(), createFieldProxyFromFragment: jest.fn(), get: jest.fn(), eventsUrl: jest.fn(),
} }));

const source = { id: 'physical', state: 'completed', configuration: { graph_manifest_sha256: 'graph' } };
const completed = { id: 'proxy', parent_run_id: 'physical', state: 'completed',
  configuration: { graph_manifest_sha256: 'graph' }, result: {
    manifest: { kind: 'experimental-field-proxy' }, preview: { recording: null },
  } };

beforeEach(() => {
  sessionStorage.clear(); jest.resetAllMocks();
  global.crypto = { randomUUID: () => 'stable-request' };
  global.WebSocket = class { close() {} };
  simulationApi.eventsUrl.mockReturnValue('ws://localhost/events');
  simulationApi.get.mockResolvedValue(completed);
});

test('creates one network calculation from the completed physical source', async () => {
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [] });
  simulationApi.createFieldProxyFromFragment.mockResolvedValue({ id: 'proxy' });
  const { result } = renderHook(() => useWholeNetworkProxy(source, true, true));
  await waitFor(() => expect(result.current.status).toBe('completed'));
  expect(simulationApi.createFieldProxyFromFragment).toHaveBeenCalledWith('physical', expect.objectContaining({
    request_id: 'stable-request', gain: EXPERIMENTAL_FIELD_GAIN, allow_contact_exclusion: false,
  }), expect.any(AbortSignal));
  expect(result.current.run).toEqual(completed);
});

test('restores an existing run without creating another and rejects a foreign source', async () => {
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'proxy' }] });
  simulationApi.get.mockResolvedValue({ ...completed, parent_run_id: 'other' });
  const { result } = renderHook(() => useWholeNetworkProxy(source, true, false));
  await waitFor(() => expect(result.current.status).toBe('error'));
  expect(result.current.run).toBeNull();
  expect(simulationApi.createFieldProxyFromFragment).not.toHaveBeenCalled();
});

test('forwards bounded model-time progress from the current network run', async () => {
  let socket;
  global.WebSocket = class { constructor() { socket = this; } close() {} };
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'proxy' }] });
  simulationApi.get.mockResolvedValue({ ...completed, state: 'running' });
  const { result } = renderHook(() => useWholeNetworkProxy(source, true, false));
  await waitFor(() => expect(result.current.status).toBe('running'));
  await act(async () => socket.onmessage({ data: JSON.stringify({ event: { run_id: 'proxy',
    progress: { phase: 'network', done: 40, total: 100 } } }) }));
  expect(result.current.progress).toEqual({ phase: 'network', done: 40, total: 100, runId: 'proxy' });
  await act(async () => socket.onmessage({ data: JSON.stringify({ event: { run_id: 'proxy',
    progress: { phase: 'network', done: 40, total: 1001 } } }) }));
  expect(result.current.progress).toEqual({ phase: 'network', done: 40, total: 100, runId: 'proxy' });
});

test('reconnects after a socket constructor failure and reports real-time transport loss', async () => {
  jest.useFakeTimers();
  let attempts = 0;
  const sockets = [];
  global.WebSocket = class {
    constructor() {
      attempts += 1;
      if (attempts === 1) throw new Error('socket unavailable');
      sockets.push(this);
    }
    close() {}
  };
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'proxy' }] });
  simulationApi.get.mockResolvedValue({ ...completed, state: 'running' });
  const { result, unmount } = renderHook(() => useWholeNetworkProxy(source, true, false));
  await waitFor(() => expect(result.current.status).toBe('running'));
  expect(result.current.connectionLost).toBe(true);
  await act(async () => { jest.advanceTimersByTime(2000); });
  expect(sockets).toHaveLength(1);
  act(() => sockets[0].onopen());
  expect(result.current.connectionLost).toBe(false);
  act(() => sockets[0].onclose());
  expect(result.current.connectionLost).toBe(true);
  await act(async () => { jest.advanceTimersByTime(2000); });
  expect(sockets).toHaveLength(2);
  // A successful HTTP poll must not conceal the disconnected event stream.
  expect(result.current.connectionLost).toBe(true);
  act(() => sockets[1].onopen());
  expect(result.current.connectionLost).toBe(false);
  unmount();
  jest.useRealTimers();
});

test('retries only the failed network stage for the same physical source', async () => {
  const requestId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
  global.crypto = { randomUUID: () => requestId };
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'old', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === 'old'
    ? { ...completed, id: 'old', state: 'failed' } : completed);
  simulationApi.createFieldProxyFromFragment.mockResolvedValue({ id: 'proxy' });
  const { result } = renderHook(() => useWholeNetworkProxy(source, true, true));
  await waitFor(() => expect(result.current.status).toBe('failed'));
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.status).toBe('completed'));
  expect(simulationApi.createFieldProxyFromFragment).toHaveBeenCalledTimes(1);
  expect(simulationApi.createFieldProxyFromFragment).toHaveBeenCalledWith('physical',
    expect.objectContaining({ request_id: requestId }), expect.any(AbortSignal));
  expect(sessionStorage.getItem('simulation:field-proxy-retry:physical')).toBeNull();
});

test('after an interrupted retry submission, reload reuses its request identity', async () => {
  const requestId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
  global.crypto = { randomUUID: () => requestId };
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'old', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === 'old'
    ? { ...completed, id: 'old', state: 'failed' } : completed);
  simulationApi.createFieldProxyFromFragment.mockRejectedValueOnce(new Error('connection lost'))
    .mockResolvedValueOnce({ id: 'proxy' });
  const first = renderHook(() => useWholeNetworkProxy(source, true, true));
  await waitFor(() => expect(first.result.current.status).toBe('failed'));
  act(() => first.result.current.retry());
  await waitFor(() => expect(first.result.current.status).toBe('error'));
  first.unmount();
  const second = renderHook(() => useWholeNetworkProxy(source, true, false));
  await waitFor(() => expect(second.result.current.status).toBe('completed'));
  expect(simulationApi.createFieldProxyFromFragment.mock.calls.map(call => call[1].request_id))
    .toEqual([requestId, requestId]);
});

test('a definitive rejection clears its retry receipt before a new attempt', async () => {
  const firstId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e';
  const nextId = 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0f';
  global.crypto = { randomUUID: jest.fn().mockReturnValueOnce(firstId).mockReturnValueOnce(nextId) };
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'old', state: 'failed' }] });
  simulationApi.get.mockImplementation(async id => id === 'old'
    ? { ...completed, id: 'old', state: 'failed' } : completed);
  simulationApi.createFieldProxyFromFragment.mockRejectedValueOnce({ response: { status: 422 } })
    .mockResolvedValueOnce({ id: 'proxy' });
  const { result } = renderHook(() => useWholeNetworkProxy(source, true, true));
  await waitFor(() => expect(result.current.status).toBe('failed'));
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.status).toBe('error'));
  expect(sessionStorage.getItem('simulation:field-proxy-retry:physical')).toBeNull();
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.status).toBe('completed'));
  expect(simulationApi.createFieldProxyFromFragment.mock.calls.map(call => call[1].request_id))
    .toEqual([firstId, nextId]);
});

test('does not resume a retry bound to a different graph', async () => {
  sessionStorage.setItem('simulation:field-proxy-retry:physical', JSON.stringify({ graph: 'other',
    requestId: 'e3ab7f7a-2d15-4fd1-93a3-dc354d6a5c0e' }));
  simulationApi.fieldProxyRuns.mockResolvedValue({ items: [{ id: 'old', state: 'failed' }] });
  simulationApi.get.mockResolvedValue({ ...completed, id: 'old', state: 'failed' });
  const { result } = renderHook(() => useWholeNetworkProxy(source, true, false));
  await waitFor(() => expect(result.current.status).toBe('failed'));
  expect(simulationApi.createFieldProxyFromFragment).not.toHaveBeenCalled();
});
