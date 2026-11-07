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
