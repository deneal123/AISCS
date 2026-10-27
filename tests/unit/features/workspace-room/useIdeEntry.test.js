import { act, renderHook, waitFor } from '@testing-library/react';
import { useIdeEntry } from '@features/workspace-room/model/useIdeEntry';
import * as api from '@api/ide';

jest.mock('@api/ide', () => ({ prepareIdeWorkspace: jest.fn() }));
const A = '00000000-0000-0000-0000-000000000001';
const B = '00000000-0000-0000-0000-000000000002';
const prepared = (id = A) => ({ repository: { repository_id: id, name: 'Repo', state: 'registered' },
  runtime: { repository_id: id, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } }, git: { initialized: true, branch: 'main' } });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const options = () => ({ threadId: 'thread', repositoryId: '', active: true, registryReady: true, blocked: false, onAccepted: jest.fn(), onPrepared: jest.fn() });
beforeEach(() => { jest.resetAllMocks(); api.prepareIdeWorkspace.mockResolvedValue(prepared()); });

it('waits for confirmed registry evidence and calls server-owned preparation once', async () => {
  const props = { ...options(), registryReady: false };
  const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  expect(api.prepareIdeWorkspace).not.toHaveBeenCalled();
  hook.rerender({ ...props, registryReady: true });
  await waitFor(() => expect(props.onAccepted).toHaveBeenCalledTimes(1));
  expect(props.onAccepted).toHaveBeenCalledWith({ repository_id: A, name: 'Repo', state: 'registered' });
  hook.rerender({ ...props, registryReady: true, repositoryId: A });
  expect(hook.result.current.waiting).toBe(false);
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(1);
  hook.rerender({ ...props, registryReady: true, repositoryId: A, active: false });
  hook.rerender({ ...props, registryReady: true, repositoryId: A, active: true });
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(1);
});

it('requires explicit recovery after failure, never loops or creates a client intent', async () => {
  api.prepareIdeWorkspace.mockRejectedValueOnce(new Error('PRIVATE'));
  const props = options(); const hook = renderHook(() => useIdeEntry(props));
  await waitFor(() => expect(hook.result.current.error).toBe(true));
  expect(props.onAccepted).not.toHaveBeenCalled();
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(1);
  await act(async () => hook.result.current.retry());
  expect(hook.result.current.error).toBe(false);
  expect(props.onAccepted).toHaveBeenCalledTimes(1);
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(2);
  expect(api.prepareIdeWorkspace.mock.calls[1].slice(0, 2)).toEqual(['thread', '']);
});

it('rejects retired responses and callbacks before another thread can be affected', async () => {
  const old = deferred(); api.prepareIdeWorkspace.mockReturnValueOnce(old.promise).mockResolvedValueOnce(prepared(B));
  const props = options(); const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  const stale = hook.result.current.retry; const signal = api.prepareIdeWorkspace.mock.calls[0][2];
  hook.rerender({ ...props, threadId: 'new', repositoryId: B });
  await waitFor(() => expect(props.onAccepted).toHaveBeenCalledTimes(1));
  expect(signal.aborted).toBe(true);
  await act(async () => { old.resolve(prepared()); await stale(); });
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(2);
  expect(props.onAccepted.mock.calls[0][0].repository_id).toBe(B);
});

it('waits for ongoing work and treats rejected/expired results as observations, not automatic retries', async () => {
  const props = { ...options(), blocked: true };
  api.prepareIdeWorkspace.mockResolvedValue({ ...prepared(), runtime: { repository_id: A, workspace: { state: 'rejected', expires_at: 9999999999, can_retry: true } } });
  const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  expect(api.prepareIdeWorkspace).not.toHaveBeenCalled();
  hook.rerender({ ...props, blocked: false });
  await waitFor(() => expect(props.onAccepted).toHaveBeenCalledTimes(1));
  hook.rerender({ ...props, blocked: false, repositoryId: A });
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(1);
  expect(hook.result.current.waiting).toBe(false);
});

it('rejects a different repository or malformed response without accepting false readiness', async () => {
  api.prepareIdeWorkspace.mockResolvedValue(prepared(B));
  const props = { ...options(), repositoryId: A };
  const hook = renderHook(() => useIdeEntry(props));
  await waitFor(() => expect(hook.result.current.error).toBe(true));
  expect(props.onAccepted).not.toHaveBeenCalled();
  expect(props.onPrepared).not.toHaveBeenCalled();
});

it('resumes pending startup once against the accepted repository, never another default project', async () => {
  api.prepareIdeWorkspace.mockResolvedValueOnce({ ...prepared(), git: null,
    runtime: { repository_id: A, workspace: { state: 'pending', expires_at: 9999999999, can_retry: false } } });
  const completion = deferred();
  api.prepareIdeWorkspace.mockReturnValueOnce(completion.promise);
  const props = options();
  const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  await waitFor(() => expect(props.onAccepted).toHaveBeenCalledTimes(1));
  hook.rerender({ ...props, repositoryId: A });
  expect(hook.result.current.awaitingReady).toBe(true);
  expect(hook.result.current.waiting).toBe(false);
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(1);
  act(() => { hook.result.current.resume(); hook.result.current.resume(); });
  expect(hook.result.current.waiting).toBe(true);
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(2);
  expect(api.prepareIdeWorkspace.mock.calls[1].slice(0, 2)).toEqual(['thread', A]);
  await act(async () => completion.resolve(prepared()));
  expect(hook.result.current.waiting).toBe(false);
  expect(hook.result.current.awaitingReady).toBe(false);
  act(() => hook.result.current.resume());
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(2);
  expect(props.onPrepared).toHaveBeenCalledTimes(2);
});

it('does not loop when the bounded continuation fails or remains pending', async () => {
  const pending = { ...prepared(), git: null,
    runtime: { repository_id: A, workspace: { state: 'pending', expires_at: 9999999999, can_retry: false } } };
  api.prepareIdeWorkspace.mockResolvedValue(pending);
  const props = { ...options(), repositoryId: A };
  const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  await waitFor(() => expect(hook.result.current.awaitingReady).toBe(true));
  await act(async () => hook.result.current.resume());
  expect(hook.result.current.awaitingReady).toBe(false);
  await act(async () => hook.result.current.resume());
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(2);
  api.prepareIdeWorkspace.mockRejectedValueOnce(new Error('PRIVATE'));
  await act(async () => hook.result.current.retry());
  expect(hook.result.current.error).toBe(true);
  hook.rerender({ ...props });
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(3);
  expect(props.onAccepted).toHaveBeenCalledTimes(2);
});

it('never resumes a retired pending project after navigation', async () => {
  api.prepareIdeWorkspace.mockResolvedValueOnce({ ...prepared(), git: null,
    runtime: { repository_id: A, workspace: { state: 'pending', expires_at: 9999999999, can_retry: false } } });
  const props = { ...options(), repositoryId: A };
  const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  await waitFor(() => expect(hook.result.current.awaitingReady).toBe(true));
  const oldResume = hook.result.current.resume;
  hook.rerender({ ...props, active: false });
  act(() => oldResume());
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(1);
  hook.rerender({ ...props, threadId: 'other', repositoryId: B });
  await waitFor(() => expect(hook.result.current.error).toBe(true));
  act(() => oldResume());
  expect(api.prepareIdeWorkspace).toHaveBeenCalledTimes(2);
});

it('retires a cancelled continuation and allows its same-project recovery on return', async () => {
  api.prepareIdeWorkspace.mockResolvedValueOnce({ ...prepared(), git: null,
    runtime: { repository_id: A, workspace: { state: 'pending', expires_at: 9999999999, can_retry: false } } });
  const unfinished = deferred();
  api.prepareIdeWorkspace.mockReturnValueOnce(unfinished.promise);
  const props = { ...options(), repositoryId: A };
  const hook = renderHook(p => useIdeEntry(p), { initialProps: props });
  await waitFor(() => expect(hook.result.current.awaitingReady).toBe(true));
  act(() => hook.result.current.resume());
  expect(hook.result.current.waiting).toBe(true);
  const signal = api.prepareIdeWorkspace.mock.calls[1][2];
  hook.rerender({ ...props, active: false });
  expect(signal.aborted).toBe(true);
  hook.rerender(props);
  expect(hook.result.current.waiting).toBe(false);
  expect(hook.result.current.awaitingReady).toBe(true);
  await act(async () => unfinished.resolve(prepared()));
  expect(props.onAccepted).toHaveBeenCalledTimes(1);
  await act(async () => hook.result.current.resume());
  expect(api.prepareIdeWorkspace.mock.calls[2].slice(0, 2)).toEqual(['thread', A]);
  expect(hook.result.current.awaitingReady).toBe(false);
  expect(hook.result.current.waiting).toBe(false);
});
