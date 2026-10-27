import { act, renderHook } from '@testing-library/react';
import { useIdeCloneRecovery } from '@features/workspace-room/model/useIdeCloneRecovery';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ getIdeCloneRecovery: jest.fn(), cloneIdeRepository: jest.fn() }));
const A = '00000000-0000-0000-0000-000000000001';
const B = '00000000-0000-0000-0000-000000000002';
const attempt = (state = 'preparing') => ({ intent_id: '10000000-0000-0000-0000-000000000001', source_repository_id: A,
  repository: { repository_id: B, name: 'Clone', state: 'registered' }, state,
  request: { origin: 'https://github.com/owner/repo.git', branch: 'main' } });
const options = () => ({ threadId: 'thread', repositoryId: B, active: true, onCompleted: jest.fn() });
beforeEach(() => { jest.resetAllMocks(); api.getIdeCloneRecovery.mockResolvedValue({ attempt: attempt() }); });
afterEach(() => jest.useRealTimers());

it('discovers the existing attempt on first entry without allocating, dispatching or selecting a repository', async () => {
  const props = options(); let hook;
  await act(async () => { hook = renderHook(() => useIdeCloneRecovery(props)); });
  expect(hook.result.current.attempt).toEqual(attempt());
  expect(hook.result.current.loading).toBe(false);
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
  expect(props.onCompleted).not.toHaveBeenCalled();
});

it('observes running work with GET and announces completion once', async () => {
  jest.useFakeTimers();
  api.getIdeCloneRecovery.mockResolvedValueOnce({ attempt: attempt('running') }).mockResolvedValue({ attempt: attempt('complete') });
  const props = options(); let hook;
  await act(async () => { hook = renderHook(() => useIdeCloneRecovery(props)); });
  await act(async () => jest.advanceTimersByTime(1500));
  expect(api.getIdeCloneRecovery).toHaveBeenCalledTimes(2);
  expect(props.onCompleted).toHaveBeenCalledTimes(1);
  expect(hook.result.current.completed).toBe(true);
  await act(async () => jest.advanceTimersByTime(100000));
  expect(api.getIdeCloneRecovery).toHaveBeenCalledTimes(2);
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
});

it('retains a bounded explicit read recovery and never substitutes creation for a failed lookup', async () => {
  api.getIdeCloneRecovery.mockRejectedValueOnce(new Error('PRIVATE_DIAGNOSTIC'));
  let hook;
  await act(async () => { hook = renderHook(() => useIdeCloneRecovery(options())); });
  expect(hook.result.current.error).toBe(true);
  expect(JSON.stringify(hook.result.current)).not.toContain('PRIVATE');
  await act(async () => hook.result.current.refresh());
  expect(hook.result.current.error).toBe(false);
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
});

it('does not carry a completion announcement over to a different recovered intent', async () => {
  api.getIdeCloneRecovery.mockResolvedValueOnce({ attempt: attempt('running') });
  const props = options(); let hook;
  await act(async () => { hook = renderHook(() => useIdeCloneRecovery(props)); });
  api.getIdeCloneRecovery.mockResolvedValue({ attempt: attempt('complete') });
  await act(async () => hook.result.current.refresh());
  expect(hook.result.current.completed).toBe(true);
  api.getIdeCloneRecovery.mockResolvedValue({ attempt: { ...attempt('complete'), intent_id: '10000000-0000-0000-0000-000000000002' } });
  await act(async () => hook.result.current.refresh());
  expect(hook.result.current.completed).toBe(false);
  expect(props.onCompleted).toHaveBeenCalledTimes(1);
});

it('treats malformed discovery as an error, not authoritative absence', async () => {
  api.getIdeCloneRecovery.mockResolvedValue({});
  let hook;
  await act(async () => { hook = renderHook(() => useIdeCloneRecovery(options())); });
  expect(hook.result.current.error).toBe(true);
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
});

it('retires stale reads and callbacks before another repository can be affected', async () => {
  let resolve; api.getIdeCloneRecovery.mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue({ attempt: null });
  const props = options(); const hook = renderHook(p => useIdeCloneRecovery(p), { initialProps: props });
  const oldRefresh = hook.result.current.refresh;
  const signal = api.getIdeCloneRecovery.mock.calls[0][2];
  await act(async () => hook.rerender({ ...props, threadId: 'other', repositoryId: A }));
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve({ attempt: attempt() }); await oldRefresh(); });
  expect(hook.result.current.attempt).toBeNull();
  expect(api.getIdeCloneRecovery).toHaveBeenCalledTimes(2);
  expect(props.onCompleted).not.toHaveBeenCalled();
});

it('bounds running observation and leaves manual checking available', async () => {
  jest.useFakeTimers(); api.getIdeCloneRecovery.mockResolvedValue({ attempt: attempt('running') });
  let hook; await act(async () => { hook = renderHook(() => useIdeCloneRecovery(options())); });
  for (let step = 0; step < 60; step += 1) await act(async () => jest.advanceTimersByTime(1500));
  expect(hook.result.current.observationExpired).toBe(true);
  const calls = api.getIdeCloneRecovery.mock.calls.length;
  await act(async () => jest.advanceTimersByTime(30000));
  expect(api.getIdeCloneRecovery).toHaveBeenCalledTimes(calls);
  expect(api.cloneIdeRepository).not.toHaveBeenCalled();
});
