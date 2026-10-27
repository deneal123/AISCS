import { act, renderHook, waitFor } from '@testing-library/react';
import { getWorkspaceDiff, getWorkspaceFile, writeWorkspaceFile } from '@api/chat';
import { useWorkspaceFile } from '@features/workspace-room/model/useWorkspaceFile';
import { useWorkspaceLease } from '@features/workspace-room/model/useWorkspaceLease';

jest.mock('@api/chat', () => ({
  getWorkspaceDiff: jest.fn(),
  getWorkspaceFile: jest.fn(),
  writeWorkspaceFile: jest.fn(),
}));
jest.mock('@features/workspace-room/model/useWorkspaceLease');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

describe('workspace editor asynchronous ownership', () => {
  let lease;
  let notify;
  let refreshSnapshot;

  beforeEach(() => {
    jest.resetAllMocks();
    lease = {
      lease: { path: '' },
      actorSession: 'actor-1',
      acquire: jest.fn(async (path) => ({ path, threadId: 'thread-1', fence: 7, status: 'editing' })),
      release: jest.fn().mockResolvedValue(undefined),
      releaseTarget: jest.fn().mockResolvedValue(undefined),
      reacquire: jest.fn().mockResolvedValue({ fence: 7, status: 'editing' }),
    };
    useWorkspaceLease.mockReturnValue(lease);
    getWorkspaceFile.mockResolvedValue({ content: 'original', revision: 'revision-1' });
    getWorkspaceDiff.mockResolvedValue({ diff: 'safe diff' });
    notify = jest.fn();
    refreshSnapshot = jest.fn().mockResolvedValue(undefined);
  });

  function renderEditor() {
    return renderHook(({ threadId, active = true }) => useWorkspaceFile({
      threadId,
      active,
      workspace: { state: 'ready', revision: 'revision-1' },
      notify,
      refreshSnapshot,
    }), { initialProps: { threadId: 'thread-1' } });
  }

  async function open(result) {
    await act(async () => result.current.openFile('notes.md'));
    act(() => result.current.setFile((old) => ({ ...old, content: 'sent draft' })));
  }

  describe.each(['discard', 'copyDraft'])('local %s ownership', (action) => {
    it.each(['inactive', 'unmounted', 'another-thread', 'roundtrip'])('preserves the draft when %s', async (scope) => {
      const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      const writeText = jest.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
      try {
        const { result, rerender, unmount } = renderEditor();
        await open(result);
        const captured = result.current[action];
        if (scope === 'inactive') rerender({ threadId: 'thread-1', active: false });
        else if (scope === 'unmounted') unmount();
        else {
          rerender({ threadId: 'thread-2' });
          await open(result);
          if (scope === 'roundtrip') {
            rerender({ threadId: 'thread-1' });
            await open(result);
          }
        }
        const current = result.current.file;
        let accepted;
        await act(async () => { accepted = await captured(); });
        if (scope !== 'unmounted') expect(result.current.file).toEqual(current);
        expect(writeText).not.toHaveBeenCalled();
        expect(notify).not.toHaveBeenCalled();
        expect(accepted).toBe(false);
      } finally {
        if (previous) Object.defineProperty(navigator, 'clipboard', previous);
        else delete navigator.clipboard;
      }
    });
  });

  it.each(['another-thread', 'unmounted'])('obsolete navigation cleanup does not release the current lease when %s', async (scope) => {
    const { result, rerender, unmount } = renderEditor();
    await open(result);
    const captured = result.current.abandon;
    if (scope === 'unmounted') unmount();
    else {
      rerender({ threadId: 'thread-2' });
      await open(result);
    }
    lease.release.mockClear();
    const current = result.current.file;
    let accepted;
    await act(async () => { accepted = await captured(); });
    if (scope !== 'unmounted') expect(result.current.file).toEqual(current);
    expect(lease.release).not.toHaveBeenCalled();
    expect(accepted).toBe(false);
  });

  describe.each(['complete', 'fail'])('pending clipboard %s', (outcome) => {
    it.each(['another-thread', 'another-file', 'inactive', 'unmounted'])('cannot notify or change %s', async (scope) => {
      const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      const pending = deferred();
      const writeText = jest.fn().mockReturnValue(pending.promise);
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
      try {
        const { result, rerender, unmount } = renderEditor();
        await open(result);
        let copying;
        act(() => { copying = result.current.copyDraft(); });
        expect(writeText).toHaveBeenCalledWith('sent draft');
        if (scope === 'unmounted') unmount();
        else if (scope === 'inactive') rerender({ threadId: 'thread-1', active: false });
        else if (scope === 'another-file') await act(async () => result.current.openFile('other.md'));
        else {
          rerender({ threadId: 'thread-2' });
          await open(result);
        }
        const current = result.current.file;
        await act(async () => {
          if (outcome === 'complete') pending.resolve();
          else pending.reject(new Error('PRIVATE_CLIPBOARD_BODY'));
          expect(await copying).toBe(false);
        });
        expect(notify).not.toHaveBeenCalled();
        expect(writeText).toHaveBeenCalledTimes(1);
        if (scope !== 'unmounted') expect(result.current.file).toEqual(current);
      } finally {
        if (previous) Object.defineProperty(navigator, 'clipboard', previous);
        else delete navigator.clipboard;
      }
    });
  });

  it('current discard restores only the acknowledged baseline without writing or releasing', async () => {
    const { result } = renderEditor();
    await open(result);
    await act(async () => expect(result.current.discard()).toBe(true));
    expect(result.current.file.content).toBe('original');
    expect(result.current.dirty).toBe(false);
    expect(writeWorkspaceFile).not.toHaveBeenCalled();
    expect(lease.release).not.toHaveBeenCalled();
  });

  it('confirmed navigation can abandon the inactive current resource and release its lease', async () => {
    const { result, rerender } = renderEditor();
    await open(result);
    rerender({ threadId: 'thread-1', active: false });
    await act(async () => expect(await result.current.abandon()).toBe(true));
    expect(result.current.file.content).toBe('original');
    expect(result.current.file.fence).toBe(0);
    expect(lease.release).toHaveBeenCalledTimes(1);
  });

  describe.each(['save', 'reacquire', 'loadActual'])('captured %s admission', (action) => {
    it.each(['inactive', 'unmounted', 'another-thread', 'roundtrip'])('does not dispatch when %s', async (scope) => {
      const { result, rerender, unmount } = renderEditor();
      await open(result);
      act(() => result.current.setConflict({
        path: 'notes.md', actualContent: 'reviewed source', actualRevision: 'revision-2',
      }));
      const captured = result.current[action];
      if (scope === 'inactive') rerender({ threadId: 'thread-1', active: false });
      else if (scope === 'unmounted') unmount();
      else {
        rerender({ threadId: 'thread-2' });
        await open(result);
        if (scope === 'roundtrip') {
          rerender({ threadId: 'thread-1' });
          await open(result);
        }
      }
      lease.acquire.mockClear();
      lease.release.mockClear();
      lease.reacquire.mockClear();
      const current = result.current.file;
      await act(async () => expect(await captured()).toBe(false));
      expect(writeWorkspaceFile).not.toHaveBeenCalled();
      expect(lease.acquire).not.toHaveBeenCalled();
      expect(lease.release).not.toHaveBeenCalled();
      expect(lease.reacquire).not.toHaveBeenCalled();
      expect(notify).not.toHaveBeenCalled();
      if (scope !== 'unmounted') expect(result.current.file).toEqual(current);
    });
  });

  it('a captured old-thread opener cannot replace the current dirty editor', async () => {
    const { result, rerender } = renderEditor();
    const oldOpen = result.current.openFile;
    rerender({ threadId: 'thread-2' });
    await open(result);
    const current = result.current.file;
    lease.acquire.mockClear();
    getWorkspaceFile.mockClear();
    let accepted;
    await act(async () => { accepted = await oldOpen('old-thread.md'); });
    expect(accepted).toBe(false);
    expect(result.current.file).toEqual(current);
    expect(result.current.dirty).toBe(true);
    expect(lease.acquire).not.toHaveBeenCalled();
    expect(getWorkspaceFile).not.toHaveBeenCalled();
  });

  it('a captured old-thread opener cannot invalidate a pending current read', async () => {
    const pending = deferred();
    const { result, rerender } = renderEditor();
    const oldOpen = result.current.openFile;
    rerender({ threadId: 'thread-2' });
    getWorkspaceFile.mockReturnValueOnce(pending.promise);
    let opening;
    act(() => { opening = result.current.openFile('current.md'); });
    await waitFor(() => expect(getWorkspaceFile).toHaveBeenCalledTimes(1));
    await act(async () => expect(await oldOpen('obsolete.md')).toBe(false));
    await act(async () => {
      pending.resolve({ content: 'current source', revision: 'current-revision' });
      expect(await opening).toBe(true);
    });
    expect(result.current.file).toEqual(expect.objectContaining({
      path: 'current.md', content: 'current source', revision: 'current-revision', loading: false,
    }));
    expect(lease.releaseTarget).not.toHaveBeenCalled();
  });

  it.each(['inactive', 'unmounted'])('a captured opener dispatches nothing when %s', async (state) => {
    const { result, rerender, unmount } = renderEditor();
    const oldOpen = result.current.openFile;
    if (state === 'inactive') rerender({ threadId: 'thread-1', active: false });
    else unmount();
    let accepted;
    await act(async () => { accepted = await oldOpen('notes.md'); });
    expect(accepted).toBe(false);
    expect(lease.acquire).not.toHaveBeenCalled();
    expect(getWorkspaceFile).not.toHaveBeenCalled();
  });

  it('a superseded pending acquisition releases its lease without reading the old file', async () => {
    const pending = deferred();
    lease.acquire.mockReturnValueOnce(pending.promise);
    const { result } = renderEditor();
    let oldOpening;
    act(() => { oldOpening = result.current.openFile('old.md'); });
    await act(async () => result.current.openFile('current.md'));
    act(() => result.current.setFile((old) => ({ ...old, content: 'current dirty draft' })));
    await act(async () => {
      pending.resolve({ path: 'old.md', threadId: 'thread-1', fence: 99 });
      expect(await oldOpening).toBe(false);
    });
    expect(getWorkspaceFile.mock.calls.map((call) => call[1])).toEqual(['current.md']);
    expect(lease.releaseTarget).toHaveBeenCalledWith(expect.objectContaining({ path: 'old.md', fence: 99 }));
    expect(result.current.file.content).toBe('current dirty draft');
  });

  it('acknowledges only the submitted text while preserving newer edits as dirty', async () => {
    const write = deferred();
    writeWorkspaceFile.mockReturnValue(write.promise);
    const { result } = renderEditor();
    await open(result);
    let saving;
    act(() => { saving = result.current.save(); });
    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledTimes(1));
    act(() => result.current.setFile((old) => ({ ...old, content: 'newer unsent draft' })));
    await act(async () => { write.resolve({ revision: 'revision-2' }); await saving; });
    expect(result.current.file.content).toBe('newer unsent draft');
    expect(result.current.file.original).toBe('sent draft');
    expect(result.current.dirty).toBe(true);
    expect(result.current.file.revision).toBe('revision-2');
  });

  it('does not reinterpret a successful write as failure when background refresh fails', async () => {
    writeWorkspaceFile.mockResolvedValue({ revision: 'revision-2' });
    refreshSnapshot.mockRejectedValue({ status: 503 });
    const { result } = renderEditor();
    await open(result);
    let saved;
    await act(async () => { saved = await result.current.save(); });
    expect(saved).toBe(true);
    expect(result.current.dirty).toBe(false);
    expect(result.current.conflict).toBeNull();
    expect(getWorkspaceFile).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'success' }));
  });

  it('completes an acknowledged write and permits the next save while snapshot refresh is pending', async () => {
    const write = deferred();
    const refresh = deferred();
    writeWorkspaceFile.mockReturnValueOnce(write.promise)
      .mockResolvedValueOnce({ revision: 'revision-3' });
    refreshSnapshot.mockReturnValueOnce(refresh.promise).mockResolvedValue(undefined);
    const { result } = renderEditor();
    await open(result);
    let firstSave;
    act(() => { firstSave = result.current.save(); });
    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledTimes(1));
    act(() => result.current.setFile((old) => ({ ...old, content: 'newer unsent draft' })));
    try {
      await act(async () => write.resolve({ revision: 'revision-2' }));
      await waitFor(() => expect(result.current.file.original).toBe('sent draft'));
      expect(result.current.saving).toBe(false);
      expect(result.current.dirty).toBe(true);
      expect(result.current.file.content).toBe('newer unsent draft');
      expect(await firstSave).toBe(true);
      await act(async () => expect(await result.current.save()).toBe(true));
      expect(writeWorkspaceFile.mock.calls[1][3]).toBe('revision-2');
      expect(result.current.file.revision).toBe('revision-3');
      expect(result.current.file.original).toBe('newer unsent draft');
      expect(result.current.dirty).toBe(false);
    } finally {
      await act(async () => { refresh.resolve(); await firstSave; });
    }
    expect(result.current.file.revision).toBe('revision-3');
    expect(notify).toHaveBeenCalledTimes(2);
  });

  it.each(['complete', 'fail'])('ignores an old-thread save %s, including same-path editors', async (outcome) => {
    const write = deferred();
    writeWorkspaceFile.mockReturnValue(write.promise);
    const { result, rerender } = renderEditor();
    await open(result);
    let saving;
    act(() => { saving = result.current.save(); });
    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledTimes(1));
    rerender({ threadId: 'thread-2' });
    await open(result);
    act(() => result.current.setFile((old) => ({ ...old, content: 'new thread draft' })));
    await act(async () => {
      if (outcome === 'complete') write.resolve({ revision: 'old-thread-revision' });
      else write.reject({ status: 409 });
      await saving;
    });
    expect(result.current.file.original).toBe('original');
    expect(result.current.file.revision).toBe('revision-1');
    expect(result.current.file.content).toBe('new thread draft');
    expect(result.current.conflict).toBeNull();
    expect(refreshSnapshot).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it('ignores conflict details that arrive after selecting another file', async () => {
    const actual = deferred();
    const { result } = renderEditor();
    await open(result);
    writeWorkspaceFile.mockRejectedValue({ status: 409 });
    getWorkspaceFile.mockReturnValueOnce(actual.promise);
    let saving;
    act(() => { saving = result.current.save(); });
    await waitFor(() => expect(getWorkspaceFile).toHaveBeenCalledTimes(2));
    await act(async () => result.current.openFile('other.md'));
    await act(async () => { actual.resolve({ content: 'old file actual', revision: 'revision-2' }); await saving; });
    expect(result.current.file.path).toBe('other.md');
    expect(result.current.file.stale).toBe(false);
    expect(result.current.conflict).toBeNull();
    expect(notify).not.toHaveBeenCalled();
  });

  it('releases only the old lease when an obsolete read fails', async () => {
    const read = deferred();
    getWorkspaceFile.mockReturnValueOnce(read.promise);
    const { result } = renderEditor();
    let opening;
    act(() => { opening = result.current.openFile('old.md'); });
    await waitFor(() => expect(getWorkspaceFile).toHaveBeenCalledTimes(1));
    await act(async () => result.current.openFile('new.md'));
    await act(async () => { read.reject({ status: 503 }); await opening; });
    expect(lease.release).not.toHaveBeenCalled();
    expect(lease.releaseTarget).toHaveBeenCalledWith(expect.objectContaining({ path: 'old.md', fence: 7 }));
    expect(result.current.file.path).toBe('new.md');
    expect(result.current.file.fence).toBe(7);
  });

  it('coalesces duplicate saves and an obsolete completion cannot unlock the next save', async () => {
    const oldWrite = deferred();
    const newWrite = deferred();
    writeWorkspaceFile.mockReturnValueOnce(oldWrite.promise).mockReturnValueOnce(newWrite.promise);
    const { result, rerender } = renderEditor();
    await open(result);
    let oldSave;
    let duplicate;
    act(() => { oldSave = result.current.save(); duplicate = result.current.save(); });
    expect(await duplicate).toBe(false);
    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledTimes(1));
    rerender({ threadId: 'thread-2' });
    await open(result);
    let newSave;
    act(() => { newSave = result.current.save(); });
    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledTimes(2));
    await act(async () => { oldWrite.resolve({ revision: 'old-revision' }); await oldSave; });
    expect(result.current.saving).toBe(true);
    await act(async () => { newWrite.resolve({ revision: 'new-revision' }); await newSave; });
    expect(result.current.saving).toBe(false);
    expect(result.current.file.revision).toBe('new-revision');
    expect(notify).toHaveBeenCalledTimes(1);
  });

  it('copies the latest local text rather than the draft captured at conflict time', async () => {
    const previousClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    try {
      writeWorkspaceFile.mockRejectedValue({ status: 409 });
      const { result } = renderEditor();
      await open(result);
      await act(async () => result.current.save());
      expect(result.current.conflict).not.toBeNull();
      act(() => result.current.setFile((old) => ({ ...old, content: 'edited after conflict' })));
      await act(async () => result.current.copyDraft());
      expect(writeText).toHaveBeenCalledWith('edited after conflict');
    } finally {
      if (previousClipboard) Object.defineProperty(navigator, 'clipboard', previousClipboard);
      else delete navigator.clipboard;
    }
  });

  it('ignores a reacquire response for a file that is no longer open', async () => {
    const pending = deferred();
    lease.reacquire.mockReturnValueOnce(pending.promise);
    const { result } = renderEditor();
    await open(result);
    let reacquiring;
    act(() => { reacquiring = result.current.reacquire(); });
    await act(async () => result.current.openFile('current.md'));
    await act(async () => { pending.resolve({ path: 'notes.md', fence: 99 }); await reacquiring; });
    expect(result.current.file.path).toBe('current.md');
    expect(result.current.file.fence).toBe(7);
    expect(notify).not.toHaveBeenCalled();
  });

  it.each(['release', 'acquire'])('ignores load-actual when the file changes during %s', async (stage) => {
    const pending = deferred();
    const { result } = renderEditor();
    await open(result);
    act(() => result.current.setConflict({
      path: 'notes.md', actualContent: 'old actual', actualRevision: 'old-revision',
    }));
    if (stage === 'release') lease.release.mockReturnValueOnce(pending.promise);
    else lease.acquire.mockReturnValueOnce(pending.promise);
    let loading;
    act(() => { loading = result.current.loadActual(); });
    if (stage === 'acquire') await waitFor(() => expect(lease.acquire).toHaveBeenCalledTimes(2));
    await act(async () => result.current.openFile('current.md'));
    act(() => result.current.setFile((old) => ({ ...old, content: 'current dirty draft' })));
    await act(async () => { pending.resolve({ path: 'notes.md', fence: 99 }); await loading; });
    expect(result.current.file.path).toBe('current.md');
    expect(result.current.file.content).toBe('current dirty draft');
    expect(result.current.dirty).toBe(true);
    if (stage === 'release') expect(lease.acquire.mock.calls.map((call) => call[0])).toEqual(['notes.md', 'current.md']);
    else expect(lease.releaseTarget).toHaveBeenCalledWith(expect.objectContaining({ path: 'notes.md', fence: 99 }));
  });

  it('preserves text typed while loading the reviewed actual version', async () => {
    const pending = deferred();
    const { result } = renderEditor();
    await open(result);
    act(() => result.current.setConflict({ path: 'notes.md', actualContent: 'actual', actualRevision: 'revision-2' }));
    lease.acquire.mockReturnValueOnce(pending.promise);
    let loading;
    let duplicate;
    act(() => { loading = result.current.loadActual(); duplicate = result.current.loadActual(); });
    expect(await duplicate).toBe(false);
    await waitFor(() => expect(lease.acquire).toHaveBeenCalledTimes(2));
    act(() => result.current.setFile((old) => ({ ...old, content: 'typed after reload action' })));
    await act(async () => { pending.resolve({ path: 'notes.md', fence: 8, status: 'editing' }); await loading; });
    expect(result.current.file.content).toBe('typed after reload action');
    expect(result.current.dirty).toBe(true);
    expect(result.current.conflict).not.toBeNull();
  });

  it('loads a reviewed version only for the current editor and keeps an occupied lease read-only', async () => {
    const { result } = renderEditor();
    await open(result);
    act(() => result.current.setConflict({ path: 'notes.md', actualContent: 'actual', actualRevision: 'revision-2' }));
    lease.acquire.mockResolvedValueOnce({ path: 'notes.md', fence: 0, status: 'readonly', reason: 'occupied' });
    await act(async () => expect(result.current.loadActual()).resolves.toBe(true));
    expect(result.current.file).toEqual(expect.objectContaining({ content: 'actual', original: 'actual', fence: 0, leaseStatus: 'readonly' }));
    expect(result.current.dirty).toBe(false);
    expect(result.current.conflict).toBeNull();
  });
});
