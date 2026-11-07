import { act, renderHook, waitFor } from '@testing-library/react';
import useDirectNetworkProxy from '../../../src/features/simulator/recording/useDirectNetworkProxy';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  createFieldProxyDirect: jest.fn(), get: jest.fn(), eventsUrl: jest.fn(), cancel: jest.fn(),
} }));

beforeEach(() => {
  sessionStorage.clear(); jest.resetAllMocks();
  global.WebSocket = class { close() {} };
  simulationApi.eventsUrl.mockReturnValue('ws://localhost/events');
});

test('restores a network-only run and its operator-selected simulation after reload', async () => {
  const simulation = { source_um: [1, 2, 3] }, completed = { id: 'run', parent_run_id: 'scene', state: 'completed' };
  simulationApi.createFieldProxyDirect.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue(completed);
  const callback = jest.fn();
  const hook = renderHook(() => useDirectNetworkProxy(callback, 'scene'));
  await act(async () => { await hook.result.current.start('scene', { simulation }); });
  await waitFor(() => expect(callback).toHaveBeenCalledWith(completed, simulation));
  expect(JSON.parse(sessionStorage.getItem('simulation:direct:scene')).simulation).toEqual(simulation);
  hook.unmount(); callback.mockClear();
  renderHook(() => useDirectNetworkProxy(callback, 'scene'));
  await waitFor(() => expect(callback).toHaveBeenCalledWith(completed, simulation));
  expect(simulationApi.createFieldProxyDirect).toHaveBeenCalledTimes(1);
});

test('rejects a restored run belonging to another scene', async () => {
  sessionStorage.setItem('simulation:direct:scene', JSON.stringify({ id: 'run', simulation: {} }));
  simulationApi.get.mockResolvedValue({ id: 'run', parent_run_id: 'another', state: 'completed' });
  const callback = jest.fn();
  const { result } = renderHook(() => useDirectNetworkProxy(callback, 'scene'));
  await waitFor(() => expect(result.current.status).toBe('error'));
  expect(callback).not.toHaveBeenCalled();
});

test('an idempotent submission returning a completed run is verified and shown automatically', async () => {
  const simulation = { source_um: [1, 2, 3] };
  const completed = { id: 'run', parent_run_id: 'scene', state: 'completed' };
  simulationApi.createFieldProxyDirect.mockResolvedValue(completed);
  simulationApi.get.mockResolvedValue(completed);
  const callback = jest.fn();
  const hook = renderHook(() => useDirectNetworkProxy(callback, 'scene'));
  await act(async () => { await hook.result.current.start('scene', { simulation }); });
  await waitFor(() => expect(callback).toHaveBeenCalledTimes(1));
  expect(simulationApi.get).toHaveBeenCalledWith('run', expect.any(AbortSignal));
  expect(callback).toHaveBeenCalledWith(completed, simulation);
});

test('an immediately completed run from another scene is not shown', async () => {
  simulationApi.createFieldProxyDirect.mockResolvedValue({ id: 'run', state: 'completed' });
  simulationApi.get.mockResolvedValue({ id: 'run', parent_run_id: 'another', state: 'completed' });
  const callback = jest.fn();
  const hook = renderHook(() => useDirectNetworkProxy(callback, 'scene'));
  await act(async () => { await hook.result.current.start('scene', { simulation: {} }); });
  await waitFor(() => expect(hook.result.current.status).toBe('error'));
  expect(callback).not.toHaveBeenCalled();
});

test('reuses the original request after an interrupted submission', async () => {
  const request = { request_id: 'original-id', simulation: { source_um: [1, 2, 3] } };
  simulationApi.createFieldProxyDirect.mockRejectedValueOnce(new Error('connection lost'))
    .mockResolvedValueOnce({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', parent_run_id: 'scene', state: 'completed' });
  const hook = renderHook(() => useDirectNetworkProxy(() => {}, 'scene'));
  await act(async () => { await hook.result.current.start('scene', request); });
  expect(hook.result.current.status).toBe('error');
  expect(JSON.parse(sessionStorage.getItem('simulation:direct:scene')).pending).toEqual(request);
  hook.unmount();
  const callback = jest.fn();
  renderHook(() => useDirectNetworkProxy(callback, 'scene'));
  await waitFor(() => expect(callback).toHaveBeenCalled());
  expect(simulationApi.createFieldProxyDirect).toHaveBeenLastCalledWith('scene', request, expect.any(AbortSignal));
});

test.each(['pending', 'existing'])('does not resume %s work for a fresh or edited scene', async kind => {
  const saved = kind === 'pending'
    ? { pending: { request_id: 'old-request', simulation: { source_um: [1, 2, 3] } } }
    : { id: 'old-run', simulation: { source_um: [1, 2, 3] } };
  sessionStorage.setItem('simulation:direct:scene', JSON.stringify(saved));
  const callback = jest.fn();
  const hook = renderHook(() => useDirectNetworkProxy(callback, 'scene', () => false));
  await act(async () => {});
  expect(hook.result.current.status).toBe('idle');
  expect(simulationApi.createFieldProxyDirect).not.toHaveBeenCalled();
  expect(simulationApi.get).not.toHaveBeenCalled();
  expect(callback).not.toHaveBeenCalled();
  expect(JSON.parse(sessionStorage.getItem('simulation:direct:scene'))).toEqual(saved);
});

test('a deliberate retry may reuse an untouched pending request after automatic recovery was declined', async () => {
  const simulation = { source_um: [1, 2, 3] };
  const saved = { request_id: 'original', simulation };
  sessionStorage.setItem('simulation:direct:scene', JSON.stringify({ pending: saved }));
  simulationApi.createFieldProxyDirect.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', parent_run_id: 'scene', state: 'completed' });
  const callback = jest.fn();
  const hook = renderHook(() => useDirectNetworkProxy(callback, 'scene', () => false));
  await act(async () => { await hook.result.current.start('scene', { request_id: 'new', simulation }); });
  await waitFor(() => expect(callback).toHaveBeenCalledTimes(1));
  expect(simulationApi.createFieldProxyDirect).toHaveBeenCalledWith('scene', saved, expect.any(AbortSignal));
});

test('shows bounded current-run network progress and ignores invalid events', async () => {
  let socket;
  global.WebSocket = class { constructor() { socket = this; } close() {} };
  simulationApi.createFieldProxyDirect.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', parent_run_id: 'scene', state: 'running' });
  const hook = renderHook(() => useDirectNetworkProxy(() => {}, 'scene'));
  await act(async () => { await hook.result.current.start('scene', { simulation: {} }); });
  await waitFor(() => expect(hook.result.current.status).toBe('running'));
  act(() => socket.onmessage({ data: JSON.stringify({ event: { run_id: 'run',
    progress: { phase: 'network', done: 7, total: 10 } } }) }));
  expect(hook.result.current.progress).toEqual({ phase: 'network', done: 7, total: 10, runId: 'run' });
  act(() => socket.onmessage({ data: JSON.stringify({ event: { run_id: 'run',
    progress: { phase: 'network', done: 7, total: 1001 } } }) }));
  expect(hook.result.current.progress).toEqual({ phase: 'network', done: 7, total: 10, runId: 'run' });
});

test('reconnects progress events after a socket closes while HTTP polling continues', async () => {
  const sockets = [];
  global.WebSocket = class { constructor() { sockets.push(this); } close() {} };
  simulationApi.createFieldProxyDirect.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', parent_run_id: 'scene', state: 'running' });
  const hook = renderHook(() => useDirectNetworkProxy(() => {}, 'scene'));
  await act(async () => { await hook.result.current.start('scene', { simulation: {} }); });
  await waitFor(() => expect(hook.result.current.status).toBe('running'));
  const old = sockets.at(-1);
  try {
    act(() => old.onclose());
    expect(hook.result.current.connectionLost).toBe(true);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    const replacement = sockets.at(-1);
    expect(replacement).not.toBe(old);
    act(() => replacement.onopen());
    expect(hook.result.current.connectionLost).toBe(false);
    act(() => replacement.onmessage({ data: JSON.stringify({ event: { run_id: 'run',
      progress: { phase: 'network', done: 8, total: 10 } } }) }));
    expect(hook.result.current.progress).toEqual({ phase: 'network', done: 8, total: 10, runId: 'run' });
  } finally {
    hook.unmount();
  }
});
