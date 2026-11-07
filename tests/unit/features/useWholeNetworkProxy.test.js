import { renderHook, waitFor } from '@testing-library/react';
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
