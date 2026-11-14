import { act, renderHook, waitFor } from '@testing-library/react';
import useFullPopulationFeedback from '../../../src/features/simulator/recording/useFullPopulationFeedback';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: {
  createFullFeedback: jest.fn(), cancel: jest.fn(), get: jest.fn(), eventsUrl: jest.fn(),
} }));

beforeEach(() => {
  jest.resetAllMocks();
  sessionStorage.clear();
  global.crypto = { randomUUID: () => 'fba50b24-f408-4d70-bd9b-3f0e18f76412' };
  global.WebSocket = class { close() {} };
  simulationApi.eventsUrl.mockReturnValue('ws://localhost/events');
});

test('restores only an accepted receipt and verifies its result with the backend', async () => {
  sessionStorage.setItem('simulation:full:scene', JSON.stringify({ version: 1, id: 'run',
    signature: 'contacts', graph: 'graph' }));
  const onResume = jest.fn(), complete = jest.fn();
  simulationApi.get.mockResolvedValue({ id: 'run', state: 'completed', result: {
    manifest: { kind: 'experimental-full-population-feedback' }, preview: { status: 'converged' },
  } });
  renderHook(() => useFullPopulationFeedback(complete, 'scene', {
    canResume: receipt => receipt.signature === 'contacts' && receipt.graph === 'graph',
    validateResume: () => true, onResume,
  }));
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  expect(onResume).toHaveBeenCalledWith(expect.objectContaining({ id: 'run' }),
    expect.objectContaining({ id: 'run' }));
  expect(simulationApi.get).toHaveBeenCalledWith('run', expect.anything());
  expect(sessionStorage.getItem('simulation:full:scene')).toBeNull();
});

test('does not restore a run when the scene or contacts no longer match', async () => {
  sessionStorage.setItem('simulation:full:scene', JSON.stringify({ version: 1, id: 'run',
    signature: 'old', graph: 'graph' }));
  const onResume = jest.fn();
  const { result } = renderHook(() => useFullPopulationFeedback(jest.fn(), 'scene', {
    canResume: receipt => receipt.signature === 'new', onResume,
  }));
  expect(result.current.status).toBe('idle');
  expect(onResume).not.toHaveBeenCalled();
  expect(simulationApi.get).not.toHaveBeenCalled();
});

test('rejects a receipt whose backend configuration does not match', async () => {
  sessionStorage.setItem('simulation:full:scene', JSON.stringify({ version: 1, id: 'run',
    signature: 'contacts', graph: 'graph' }));
  simulationApi.get.mockResolvedValue({ id: 'run', state: 'completed', configuration: {
    graph_manifest_sha256: 'other',
  }, result: { manifest: { kind: 'experimental-full-population-feedback' },
    preview: { status: 'converged' } } });
  const complete = jest.fn(), onResume = jest.fn();
  const { result } = renderHook(() => useFullPopulationFeedback(complete, 'scene', {
    canResume: () => true,
    validateResume: (receipt, run) => receipt.graph === run.configuration.graph_manifest_sha256,
    onResume,
  }));
  await waitFor(() => expect(result.current.status).toBe('error'));
  expect(onResume).not.toHaveBeenCalled();
  expect(complete).not.toHaveBeenCalled();
});

test('changing scenes detaches the prior run', async () => {
  simulationApi.createFullFeedback.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockImplementation(() => new Promise(() => {}));
  const { result, rerender } = renderHook(({ scene }) => useFullPopulationFeedback(jest.fn(), scene),
    { initialProps: { scene: 'one' } });
  await act(async () => result.current.start({ graph_manifest_sha256: 'graph' }, { signature: 's' }));
  expect(result.current.run.id).toBe('run');
  rerender({ scene: 'two' });
  expect(result.current.status).toBe('idle');
  expect(result.current.run).toBeNull();
});

test('retries a pending creation with the original request id after reload', async () => {
  const request = { request_id: 'original-request', title: 'test',
    configuration: { graph_manifest_sha256: 'graph' } };
  sessionStorage.setItem('simulation:full:scene', JSON.stringify({ version: 1,
    signature: 'contacts', graph: 'graph', pending: request }));
  simulationApi.createFullFeedback.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', state: 'running' });
  const onResume = jest.fn();
  renderHook(() => useFullPopulationFeedback(jest.fn(), 'scene', {
    canResume: () => true, validateResume: () => true, onResume,
  }));
  await waitFor(() => expect(onResume).toHaveBeenCalled());
  expect(simulationApi.createFullFeedback).toHaveBeenCalledWith(request, expect.anything());
  expect(JSON.parse(sessionStorage.getItem('simulation:full:scene'))).toEqual({
    version: 1, signature: 'contacts', graph: 'graph', id: 'run',
  });
});

test('cancel during creation waits for the run identity and cancels it', async () => {
  let finish;
  simulationApi.createFullFeedback.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  simulationApi.cancel.mockResolvedValue({ state: 'cancelled' });
  const { result } = renderHook(() => useFullPopulationFeedback(jest.fn()));
  let pending;
  act(() => { pending = result.current.start({ graph_manifest_sha256: 'a' }); });
  await act(async () => result.current.cancel());
  await act(async () => { finish({ id: 'run', state: 'queued' }); await pending; });
  expect(simulationApi.cancel).toHaveBeenCalledWith('run');
  expect(result.current.status).toBe('cancelled');
});

test('only the confirmed full calculation invokes completion', async () => {
  const complete = jest.fn();
  simulationApi.createFullFeedback.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', state: 'completed', result: {
    manifest: { kind: 'experimental-full-population-feedback' }, preview: { status: 'converged' },
  } });
  const { result } = renderHook(() => useFullPopulationFeedback(complete));
  await act(async () => result.current.start({ graph_manifest_sha256: 'a' }));
  await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  expect(complete.mock.calls[0][0].id).toBe('run');
});

test('accepts progress only from the current run and validates its bounds', async () => {
  let socket;
  global.WebSocket = class { constructor() { socket = this; } close() {} };
  simulationApi.createFullFeedback.mockResolvedValue({ id: 'run', state: 'queued' });
  simulationApi.get.mockResolvedValue({ id: 'run', state: 'running' });
  const { result } = renderHook(() => useFullPopulationFeedback(jest.fn()));
  await act(async () => result.current.start({ graph_manifest_sha256: 'a' }));
  await waitFor(() => expect(socket?.onmessage).toBeDefined());
  const emit = (id, progress) => act(async () => socket.onmessage({ data: JSON.stringify({
    event: { run_id: id, progress },
  }) }));
  await emit('other', { phase: 'full_active', done: 1, total: 2 });
  expect(result.current.progress).toBeUndefined();
  await emit('run', { phase: 'full_active', done: 3, total: 2 });
  expect(result.current.progress).toBeUndefined();
  await emit('run', { phase: 'full_feedback', iteration: 1, done: 1, total: 2 });
  expect(result.current.progress).toEqual({ phase: 'full_feedback', iteration: 1,
    done: 1, total: 2, runId: 'run' });
  await act(async () => socket.onclose());
  expect(result.current.connectionLost).toBe(true);
  await act(async () => socket.onopen());
  expect(result.current.connectionLost).toBe(false);
});
