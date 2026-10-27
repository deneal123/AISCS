import { act, renderHook, waitFor } from '@testing-library/react';
import useSimulationHistory from '../../../src/features/simulator/useSimulationHistory';
import useSimulationArtifacts from '../../../src/features/simulator/useSimulationArtifacts';
import useSimulationFullscreen from '../../../src/features/simulator/useSimulationFullscreen';
import { simulationApi } from '../../../src/features/simulator/api';

jest.mock('../../../src/features/simulator/api', () => ({ simulationApi: { list: jest.fn(), artifacts: jest.fn() } }));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
beforeEach(() => jest.clearAllMocks());

test('history appends older records without duplicates and retries the failed page', async () => {
  const hook = renderHook(useSimulationHistory);
  act(() => hook.result.current.replace({ items: [{ id: 'a' }], next_offset: 1 }));
  simulationApi.list.mockRejectedValueOnce(new Error('private')).mockResolvedValueOnce({ items: [{ id: 'a' }, { id: 'b' }], next_offset: null });
  await act(async () => { await hook.result.current.more(); });
  expect(hook.result.current.runs).toEqual([{ id: 'a' }]);
  expect(hook.result.current.error).not.toContain('private');
  await act(async () => { await hook.result.current.retry(); });
  expect(simulationApi.list.mock.calls.map(call => call[1])).toEqual([1, 1]);
  expect(hook.result.current.runs).toEqual([{ id: 'a' }, { id: 'b' }]);
  expect(hook.result.current.nextOffset).toBeNull();
});

test('late page cannot append after a fresh history replaces it', async () => {
  const page = deferred(); simulationApi.list.mockReturnValueOnce(page.promise);
  const hook = renderHook(useSimulationHistory);
  act(() => hook.result.current.replace({ items: [{ id: 'old' }], next_offset: 1 }));
  act(() => { hook.result.current.more(); });
  const signal = simulationApi.list.mock.calls[0][0];
  act(() => hook.result.current.replace({ items: [{ id: 'new' }], next_offset: null }));
  expect(signal.aborted).toBe(true);
  await act(async () => { page.resolve({ items: [{ id: 'stale' }], next_offset: 2 }); });
  expect(hook.result.current.runs).toEqual([{ id: 'new' }]);
  expect(hook.result.current.loading).toBe(false);
});

test('failed first-page refresh retries refresh rather than the former next page', async () => {
  const hook = renderHook(useSimulationHistory);
  act(() => hook.result.current.replace({ items: [{ id: 'a' }], next_offset: 30 }));
  simulationApi.list.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ items: [{ id: 'b' }], next_offset: 30 });
  await act(async () => { await hook.result.current.refresh(); });
  await act(async () => { await hook.result.current.retry(); });
  expect(simulationApi.list.mock.calls.map(call => call[1])).toEqual([0, 0]);
  expect(hook.result.current.runs).toEqual([{ id: 'b' }]);
});

test('switching saved records cannot display delayed artifacts from the previous record', async () => {
  const first = deferred(), second = deferred();
  simulationApi.artifacts.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const hook = renderHook(({ id }) => useSimulationArtifacts(id, 'completed', true), { initialProps: { id: 'a' } });
  const signal = simulationApi.artifacts.mock.calls[0][1];
  hook.rerender({ id: 'b' });
  expect(signal.aborted).toBe(true);
  await act(async () => { second.resolve({ items: [{ id: 'b-file' }] }); });
  await act(async () => { first.resolve({ items: [{ id: 'a-file' }] }); });
  expect(hook.result.current.files).toEqual([{ id: 'b-file' }]);
});

test('artifact read failure has an explicit read-only retry and closes on leaving files', async () => {
  simulationApi.artifacts.mockRejectedValueOnce(new Error('private path')).mockResolvedValueOnce({ items: [{ id: 'file' }] });
  const hook = renderHook(({ enabled }) => useSimulationArtifacts('a', 'completed', enabled), { initialProps: { enabled: true } });
  await waitFor(() => expect(hook.result.current.error).toContain('Не удалось'));
  expect(hook.result.current.error).not.toContain('private');
  act(() => hook.result.current.retry());
  await waitFor(() => expect(hook.result.current.files).toEqual([{ id: 'file' }]));
  hook.rerender({ enabled: false });
  expect(hook.result.current.files).toEqual([]);
});

test('unsupported fullscreen preserves the application and reports a bounded error', async () => {
  const onError = jest.fn(), hook = renderHook(() => useSimulationFullscreen(onError));
  hook.result.current.root.current = {};
  await act(async () => { await hook.result.current.toggle(); });
  expect(onError).toHaveBeenCalledWith('Полноэкранный режим недоступен. Симулятор продолжает работать в окне.');
  expect(hook.result.current.active).toBe(false);
});

test('Escape before the scene mounts never calls browser fullscreen APIs', () => {
  const hook = renderHook(() => useSimulationFullscreen(jest.fn()));
  const descriptor = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null });
  const exit = jest.fn(); document.exitFullscreen = exit;
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
  expect(exit).not.toHaveBeenCalled();
  hook.unmount(); delete document.exitFullscreen;
  if (descriptor) Object.defineProperty(document, 'fullscreenElement', descriptor);
  else delete document.fullscreenElement;
});
