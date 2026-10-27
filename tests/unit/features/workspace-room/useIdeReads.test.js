import { act, renderHook, waitFor } from '@testing-library/react';
import * as api from '@api/ide';
import { useIdeRepositories } from '@features/workspace-room/model/useIdeRepositories';
import { useIdeRepositoryReads } from '@features/workspace-room/model/useIdeRepositoryReads';

jest.mock('@api/ide', () => ({ listIdeRepositories: jest.fn(), getIdeRuntime: jest.fn(), readIdeTree: jest.fn(), readIdeFile: jest.fn() }));
const repoA = '00000000-0000-0000-0000-000000000001';
const repoB = '00000000-0000-0000-0000-000000000002';
const generation = 'a'.repeat(64);
const entries = [{ path: 'main.py', type: 'file', size: 5, incomplete: false }];
const ready = (id) => ({ repository_id: id, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };

it('retargets a moved folder and its open descendants without losing cached content', async () => {
  const tree = ['src/a.py', 'src/nested/b.py', 'other.py'].map(path => ({ path, type: 'file', size: 5, incomplete: false }));
  tree.unshift({ path: 'src', type: 'dir', size: 0, incomplete: false });
  api.readIdeTree.mockImplementation(async () => ({ repository_id: repoA, generation, entries: tree, truncated: false }));
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => { await hook.result.current.open('src/a.py'); });
  await act(async () => { await hook.result.current.open('src/nested/b.py'); });
  act(() => hook.result.current.acceptMove({ generation, moved_from: 'src', path: 'lib/src', size: 0 }));
  expect(hook.result.current.tree.entries.map(item => item.path)).toEqual(['lib/src', 'lib/src/a.py', 'lib/src/nested/b.py', 'other.py']);
  expect(hook.result.current.files.map(file => file.path)).toEqual(['lib/src/a.py', 'lib/src/nested/b.py']);
  expect(hook.result.current.file).toMatchObject({ path: 'lib/src/nested/b.py', content: 'alpha' });
});

beforeEach(() => {
  jest.resetAllMocks();
  api.getIdeRuntime.mockImplementation(async (_thread, id) => ready(id));
  api.readIdeTree.mockImplementation(async (_thread, id) => ({ repository_id: id, generation, entries, truncated: false }));
  api.readIdeFile.mockImplementation(async (_thread, id, path) => ({ repository_id: id, generation, path, kind: 'text', content: id === repoA ? 'alpha' : 'bravo', digest: 'b'.repeat(64), size: 5, truncated: false }));
});

it('makes no reads while inactive and never treats initial loading as an empty registry', async () => {
  const pending = deferred(); api.listIdeRepositories.mockReturnValue(pending.promise);
  const hook = renderHook(({ active }) => useIdeRepositories({ threadId: 'thread', active }), { initialProps: { active: false } });
  expect(api.listIdeRepositories).not.toHaveBeenCalled();
  hook.rerender({ active: true });
  expect(hook.result.current.status).toBe('loading');
  expect(hook.result.current.loading).toBe(true);
  await act(async () => pending.resolve({ items: [], next_offset: null }));
  expect(hook.result.current.status).toBe('ready');
});

it('masks previous-thread registry immediately and rejects late reads and captured actions', async () => {
  const pending = deferred();
  api.listIdeRepositories.mockImplementation((thread) => thread === 'old' ? pending.promise : Promise.resolve({ items: [], next_offset: null }));
  const hook = renderHook(({ threadId }) => useIdeRepositories({ threadId, active: true }), { initialProps: { threadId: 'old' } });
  const oldLoad = hook.result.current.load;
  hook.rerender({ threadId: 'new' });
  await waitFor(() => expect(hook.result.current.status).toBe('ready'));
  await act(async () => { pending.resolve({ items: [{ repository_id: repoA, name: 'PRIVATE_OLD', state: 'registered' }], next_offset: null }); await oldLoad(); });
  expect(hook.result.current.items).toEqual([]);
  expect(api.listIdeRepositories).toHaveBeenCalledTimes(2);
});

it('keeps cached repositories with an explicit error on failed refresh', async () => {
  api.listIdeRepositories.mockResolvedValueOnce({ items: [{ repository_id: repoA, name: 'Repo A', state: 'registered' }], next_offset: null }).mockRejectedValueOnce(new Error('PRIVATE'));
  const hook = renderHook(() => useIdeRepositories({ threadId: 'thread', active: true }));
  await waitFor(() => expect(hook.result.current.selectedId).toBe(repoA));
  await act(async () => hook.result.current.load());
  expect(hook.result.current.items).toHaveLength(1);
  expect(hook.result.current.error).toBe(true);
});

it('retains an off-page selection on refresh and retries the failed page exactly', async () => {
  const item = (id) => ({ repository_id: id, name: id === repoA ? 'A' : 'B', state: 'registered' });
  api.listIdeRepositories.mockResolvedValueOnce({ items: [item(repoA)], next_offset: 30 })
    .mockRejectedValueOnce(new Error('PRIVATE'))
    .mockResolvedValueOnce({ items: [item(repoB)], next_offset: null })
    .mockResolvedValueOnce({ items: [item(repoA)], next_offset: 30 });
  const hook = renderHook(() => useIdeRepositories({ threadId: 'thread', active: true }));
  await waitFor(() => expect(hook.result.current.status).toBe('ready'));
  await act(async () => hook.result.current.load(30));
  expect(hook.result.current.failedOffset).toBe(30);
  await act(async () => hook.result.current.load(hook.result.current.failedOffset));
  act(() => hook.result.current.select(repoB));
  await act(async () => hook.result.current.load());
  expect(hook.result.current.selectedId).toBe(repoB);
  expect(api.listIdeRepositories.mock.calls.map((call) => call[1])).toEqual([0, 30, 30, 0]);
});

it('reads only the selected repository without provisioning or touching the old workspace', async () => {
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.tree?.generation).toBe(generation));
  await act(async () => hook.result.current.open('main.py'));
  expect(hook.result.current.file.content).toBe('alpha');
  expect(api.getIdeRuntime).toHaveBeenCalledWith('thread', repoA, expect.any(AbortSignal));
  expect(api.readIdeFile).toHaveBeenCalledWith('thread', repoA, 'main.py', generation, expect.any(AbortSignal));
});

it('ignores a late A file after B is selected, and captured A actions cannot dispatch', async () => {
  const pending = deferred(); api.readIdeFile.mockReturnValueOnce(pending.promise);
  const hook = renderHook(({ id }) => useIdeRepositoryReads({ threadId: 'thread', repositoryId: id, active: true }), { initialProps: { id: repoA } });
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  const oldOpen = hook.result.current.open;
  act(() => { void oldOpen('main.py'); });
  hook.rerender({ id: repoB });
  expect(hook.result.current.file).toBeNull();
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => { pending.resolve({ repository_id: repoA, generation, path: 'main.py', kind: 'text', content: 'alpha', digest: 'b'.repeat(64), size: 5, truncated: false }); await oldOpen('main.py'); });
  expect(hook.result.current.file).toBeNull();
  expect(api.readIdeFile).toHaveBeenCalledTimes(1);
});

it('does not read tree for an expired/not-created runtime', async () => {
  api.getIdeRuntime.mockResolvedValue({ repository_id: repoA, workspace: { state: 'expired', expires_at: 1, can_retry: false } });
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.runtime?.state).toBe('expired'));
  expect(api.readIdeTree).not.toHaveBeenCalled();
});

it('observes pending startup with reads only and cancels polling on retirement', async () => {
  jest.useFakeTimers();
  try {
    api.getIdeRuntime.mockResolvedValueOnce({ repository_id: repoA, workspace: { state: 'pending', expires_at: 9999999999, can_retry: false } });
    const hook = renderHook(({ active }) => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active }), { initialProps: { active: true } });
    await waitFor(() => expect(hook.result.current.runtime?.state).toBe('pending'));
    expect(api.readIdeTree).not.toHaveBeenCalled();
    await act(async () => jest.advanceTimersByTime(1200));
    await waitFor(() => expect(hook.result.current.runtime?.state).toBe('ready'));
    expect(api.getIdeRuntime).toHaveBeenCalledTimes(2);
    hook.rerender({ active: false });
    await act(async () => jest.advanceTimersByTime(30000));
    expect(api.getIdeRuntime).toHaveBeenCalledTimes(2);
  } finally { jest.useRealTimers(); }
});

it('a cached tree is not a fresh visit confirmation for dependent Git reads', async () => {
  const hook = renderHook(({ active }) => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active }), { initialProps: { active: true } });
  await waitFor(() => expect(hook.result.current.validated).toBe(true));
  hook.rerender({ active: false });
  expect(hook.result.current.validated).toBe(false);
  const next = deferred(); api.getIdeRuntime.mockReturnValueOnce(next.promise);
  hook.rerender({ active: true });
  expect(hook.result.current.tree).not.toBeNull();
  expect(hook.result.current.validated).toBe(false);
  await act(async () => next.resolve({ repository_id: repoA, workspace: { state: 'ready', expires_at: 9999999999, can_retry: false } }));
  await waitFor(() => expect(hook.result.current.validated).toBe(true));
});

it('keeps a valid file on read failure and retires it on a new generation', async () => {
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => hook.result.current.open('main.py'));
  api.readIdeFile.mockRejectedValueOnce(new Error('PRIVATE'));
  await act(async () => hook.result.current.open('main.py', { refresh: true }));
  expect(hook.result.current.file.content).toBe('alpha');
  expect(hook.result.current.fileError).toBe(true);
  api.readIdeTree.mockResolvedValueOnce({ repository_id: repoA, generation: 'c'.repeat(64), entries, truncated: false });
  await act(async () => hook.result.current.load());
  expect(hook.result.current.file).toBeNull();
  expect(hook.result.current.files).toEqual([]);
});

it('switches cached tabs without network and closes to the adjacent file', async () => {
  api.readIdeTree.mockResolvedValue({ repository_id: repoA, generation, entries: [...entries, { ...entries[0], path: 'other.py' }], truncated: false });
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => hook.result.current.open('main.py'));
  await act(async () => hook.result.current.open('other.py'));
  expect(hook.result.current.files.map((file) => file.path)).toEqual(['main.py', 'other.py']);
  await act(async () => hook.result.current.open('main.py'));
  expect(api.readIdeFile).toHaveBeenCalledTimes(2);
  act(() => hook.result.current.close('main.py'));
  expect(hook.result.current.file.path).toBe('other.py');
  act(() => hook.result.current.close('other.py'));
  expect(hook.result.current.file).toBeNull();
  expect(hook.result.current.files).toEqual([]);
});

it('bounds cached tabs, preserves tab order on refresh, and retires removed paths', async () => {
  const files = Array.from({ length: 9 }, (_, index) => ({ ...entries[0], path: `${index}.py` }));
  api.readIdeTree.mockResolvedValue({ repository_id: repoA, generation, entries: files, truncated: false });
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  for (const file of files) await act(async () => hook.result.current.open(file.path));
  expect(hook.result.current.files.map((file) => file.path)).toEqual(files.slice(1).map((file) => file.path));
  await act(async () => hook.result.current.open('1.py', { refresh: true }));
  expect(hook.result.current.files[0].path).toBe('1.py');
  api.readIdeTree.mockResolvedValueOnce({ repository_id: repoA, generation, entries: files.slice(2), truncated: false });
  await act(async () => hook.result.current.load());
  expect(hook.result.current.files).toHaveLength(7);
  expect(hook.result.current.file).toBeNull();
});

it('rejects captured cache actions after a generation change and masks tabs for another repo', async () => {
  const hook = renderHook(({ id }) => useIdeRepositoryReads({ threadId: 'thread', repositoryId: id, active: true }), { initialProps: { id: repoA } });
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => hook.result.current.open('main.py'));
  const oldOpen = hook.result.current.open;
  const oldClose = hook.result.current.close;
  api.readIdeTree.mockResolvedValueOnce({ repository_id: repoA, generation: 'c'.repeat(64), entries, truncated: false });
  await act(async () => hook.result.current.load());
  await act(async () => { expect(await oldOpen('main.py')).toBe(false); oldClose('main.py'); });
  expect(hook.result.current.files).toEqual([]);
  expect(api.readIdeFile).toHaveBeenCalledTimes(1);
  hook.rerender({ id: repoB });
  expect(hook.result.current.files).toEqual([]);
  expect(hook.result.current.file).toBeNull();
  await waitFor(() => expect(hook.result.current.runtime?.state).toBe('ready'));
});

it('cached selection aborts a pending file read and ignores its late result', async () => {
  api.readIdeTree.mockResolvedValue({ repository_id: repoA, generation, entries: [...entries, { ...entries[0], path: 'other.py' }], truncated: false });
  const hook = renderHook(() => useIdeRepositoryReads({ threadId: 'thread', repositoryId: repoA, active: true }));
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => hook.result.current.open('main.py'));
  const pending = deferred();
  api.readIdeFile.mockReturnValueOnce(pending.promise);
  let loading;
  act(() => { loading = hook.result.current.open('other.py'); });
  await act(async () => hook.result.current.open('main.py'));
  expect(hook.result.current.fileLoading).toBe(false);
  await act(async () => {
    pending.resolve({ repository_id: repoA, generation, path: 'other.py', kind: 'text', content: 'late', digest: 'b'.repeat(64), size: 4, truncated: false });
    expect(await loading).toBe(false);
  });
  expect(hook.result.current.file.path).toBe('main.py');
  expect(hook.result.current.files).toHaveLength(1);
});

it('accepts a reviewed source read without fabricating a write receipt and retires captured callbacks', async () => {
  const hook = renderHook(({ id }) => useIdeRepositoryReads({ threadId: 'thread', repositoryId: id, active: true }), { initialProps: { id: repoA } });
  await waitFor(() => expect(hook.result.current.tree).not.toBeNull());
  await act(async () => hook.result.current.open('main.py'));
  const actual = { repository_id: repoA, generation, path: 'main.py', kind: 'text', content: 'reviewed', size: 8, digest: 'c'.repeat(64), truncated: false };
  act(() => expect(hook.result.current.acceptRead(actual)).toBe(true));
  expect(hook.result.current.file.content).toBe('reviewed');
  expect(hook.result.current.files[0].content).toBe('reviewed');
  expect(hook.result.current.tree.entries).toEqual(entries);
  const old = hook.result.current.acceptRead;
  hook.rerender({ id: repoB });
  expect(old(actual)).toBe(false);
  expect(hook.result.current.file).toBeNull();
});
