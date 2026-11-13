import { act, renderHook, waitFor } from '@testing-library/react';
import useStateContrast from '../../../src/features/simulator/useStateContrast';
import { simulationApi } from '../../../src/features/simulator/api';
import { verifyFieldProxyState } from '../../../src/features/simulator/field/fieldProxyState';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { artifacts: jest.fn(), readArtifact: jest.fn() } }));
jest.mock('../../../src/features/simulator/field/fieldProxyState', () => ({ verifyFieldProxyState: jest.fn() }));
const files = [{ name: 'state-response.bin', id: 'response', bytes: 100 }, { name: 'metadata.json', id: 'metadata', bytes: 100 }];
const makeRun = id => ({ id, result: { manifest: { kind: 'experimental-field-proxy', files } } });
const graph = {};
beforeEach(() => { jest.clearAllMocks(); simulationApi.artifacts.mockResolvedValue({ items: files });
  simulationApi.readArtifact.mockImplementation((_id, file) => Promise.resolve(file)); });

test('loads verified field state automatically without a separate enable switch', async () => {
  verifyFieldProxyState.mockResolvedValue({ cells: 2 });
  const run = makeRun('one');
  const { result } = renderHook(() => useStateContrast(run, graph));
  await waitFor(() => expect(result.current.data).toEqual({ cells: 2 }));
  expect(verifyFieldProxyState).toHaveBeenCalledTimes(1);
  expect(result.current.error).toBe(false);
});

test('discard a stale download and do not display failed verification', async () => {
  let finish;
  const first = new Promise(resolve => { finish = resolve; });
  simulationApi.artifacts.mockImplementation(id => id === 'old' ? first : Promise.resolve({ items: files }));
  verifyFieldProxyState.mockRejectedValue(new Error('mismatch'));
  const old = makeRun('old'), next = makeRun('next');
  const hook = renderHook(({ run }) => useStateContrast(run, graph), { initialProps: { run: old } });
  await waitFor(() => expect(simulationApi.artifacts).toHaveBeenCalledTimes(1));
  hook.rerender({ run: next });
  await waitFor(() => expect(hook.result.current.error).toBe(true));
  await act(async () => { finish({ items: files }); });
  expect(hook.result.current.data).toBeNull();
  expect(verifyFieldProxyState).toHaveBeenCalledTimes(1);
});
