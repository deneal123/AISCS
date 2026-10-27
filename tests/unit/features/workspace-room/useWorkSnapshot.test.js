import { act, renderHook, waitFor } from '@testing-library/react';
import { getWorkHub, getAccountWorkLibrary } from '@api/chat';
import { useWorkSnapshot } from '@features/workspace-room/model/useWorkSnapshot';

jest.mock('@api/chat', () => ({ getWorkHub: jest.fn(), getAccountWorkLibrary: jest.fn() }));

const snapshot = (state = 'ready') => ({
  contract_version: 2,
  workspace: { state, revision: state === 'ready' ? 'revision-1' : '', entries: [], history: [] },
  room: { state },
  library: { state: 'ready', items: [{ file_id: 'first-file', name: 'first.txt' }], next_cursor: 'cursor-1' },
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

describe('Work snapshot request ownership', () => {
  let notify;
  beforeEach(() => {
    jest.resetAllMocks();
    getWorkHub.mockResolvedValue(snapshot());
    getAccountWorkLibrary.mockResolvedValue({ state: 'ready', items: [], next_cursor: null });
    notify = jest.fn();
  });
  function renderSnapshot() {
    return renderHook(({ threadId }) => useWorkSnapshot({ threadId, notify }), {
      initialProps: { threadId: 'thread-1' },
    });
  }
  async function loaded(result) {
    await waitFor(() => expect(result.current.hub.workspace.state).toBe('ready'));
  }

  it('retains owned file facts through repeated facet/transport failures and proven expiry', async () => {
    const original = snapshot();
    original.workspace.entries = [{ path: 'documents/a/document.toml', type: 'file' }];
    getWorkHub.mockResolvedValue(original);
    const { result, rerender } = renderSnapshot();
    await loaded(result);
    getWorkHub.mockRejectedValue({ response: { status: 503 } });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await act(async () => result.current.load({ background: true }));
      expect(result.current.hub.workspace.entries).toEqual(original.workspace.entries);
      expect(result.current.hub.workspace.state).toBe('unavailable');
    }
    for (const state of ['unavailable', 'absent', 'expired', 'unavailable', 'absent']) {
      getWorkHub.mockResolvedValue(snapshot(state));
      await act(async () => result.current.load({ background: true }));
      expect(result.current.hub.workspace.entries).toEqual(original.workspace.entries);
      expect(result.current.hub.workspace.stale).toBe(true);
    }
    expect(result.current.hub.workspace.state).toBe('expired');
    getWorkHub.mockResolvedValue(snapshot('absent'));
    rerender({ threadId: 'thread-2' });
    await waitFor(() => expect(result.current.hub.loading).toBe(false));
    expect(result.current.hub.workspace.entries).toEqual([]);
    expect(result.current.hub.workspace.state).toBe('absent');
  });

  it('retires an inaccessible thread without falling back to another account workspace', async () => {
    getWorkHub.mockRejectedValue({ response: { status: 404 } });
    const onThreadUnavailable = jest.fn();
    const { result } = renderHook(() => useWorkSnapshot({ threadId: 'denied', onThreadUnavailable }));
    await waitFor(() => expect(onThreadUnavailable).toHaveBeenCalledWith('denied'));
    expect(getAccountWorkLibrary).not.toHaveBeenCalled();
    expect(result.current.hub.workspace.entries).toEqual([]);
  });

  it('keeps a nonzero mount invalidation unresolved rather than downgrading it to background refresh', async () => {
    const first = deferred(); const second = deferred(); const nextThread = deferred();
    getWorkHub.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise).mockReturnValueOnce(nextThread.promise);
    const { result, rerender } = renderHook((props) => useWorkSnapshot(props), {
      initialProps: { threadId: 'thread-1', invalidationVersion: 4 },
    });
    expect(result.current.hub.loading).toBe(true);
    await waitFor(() => expect(getWorkHub).toHaveBeenCalledTimes(1));
    expect(result.current.hub.loading).toBe(true);
    await act(async () => first.resolve(snapshot()));
    await loaded(result);
    rerender({ threadId: 'thread-1', invalidationVersion: 5 });
    await waitFor(() => expect(getWorkHub).toHaveBeenCalledTimes(2));
    expect(result.current.hub.refreshing).toBe(true);
    expect(result.current.hub.workspace.state).toBe('ready');
    await act(async () => second.resolve(snapshot()));
    rerender({ threadId: 'thread-2', invalidationVersion: 5 });
    expect(result.current.hub.loading).toBe(true);
    await waitFor(() => expect(getWorkHub).toHaveBeenCalledTimes(3));
    expect(result.current.hub.loading).toBe(true);
    await act(async () => nextThread.resolve(snapshot('absent')));
    await waitFor(() => expect(result.current.hub.loading).toBe(false));
    expect(result.current.hub.workspace.state).toBe('absent');
  });

  it('keeps startup and another thread unresolved until the owned snapshot arrives', async () => {
    const first = deferred(); const second = deferred();
    getWorkHub.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderSnapshot();
    expect(result.current.hub.loading).toBe(true);
    await act(async () => first.resolve(snapshot()));
    await loaded(result);
    rerender({ threadId: 'thread-2' });
    expect(result.current.hub.loading).toBe(true);
    expect(result.current.hub.workspace.entries).toEqual([]);
    expect(result.current.hub.library.items).toEqual([]);
    await act(async () => second.resolve(snapshot('absent')));
    await waitFor(() => expect(result.current.hub.loading).toBe(false));
    expect(result.current.hub.workspace.state).toBe('absent');
  });

  it('retains initial loading when a genuine invalidation supersedes an unresolved read', async () => {
    const first = deferred(); const fresh = deferred();
    getWorkHub.mockReturnValueOnce(first.promise).mockReturnValueOnce(fresh.promise);
    const { result, rerender } = renderHook((props) => useWorkSnapshot(props), {
      initialProps: { threadId: 'thread-1', invalidationVersion: 0 },
    });
    await waitFor(() => expect(getWorkHub).toHaveBeenCalledTimes(1));
    const firstSignal = getWorkHub.mock.calls[0][1].signal;
    rerender({ threadId: 'thread-1', invalidationVersion: 1 });
    await waitFor(() => expect(getWorkHub).toHaveBeenCalledTimes(2));
    expect(firstSignal.aborted).toBe(true);
    expect(result.current.hub.loading).toBe(true);
    expect(result.current.hub.refreshing).toBe(false);
    await act(async () => first.resolve(snapshot('absent')));
    expect(result.current.hub.loading).toBe(true);
    await act(async () => fresh.resolve(snapshot()));
    await loaded(result);
    expect(result.current.hub.loading).toBe(false);
    expect(result.current.hub.refreshing).toBe(false);
  });

  it('retains rows and cursor after page failure and clears the error on explicit retry', async () => {
    getAccountWorkLibrary.mockRejectedValueOnce({ status: 503, message: 'private-marker' });
    const { result } = renderSnapshot();
    await loaded(result);
    await act(async () => result.current.loadMoreLibrary());
    expect(result.current.libraryPageError).toBe(true);
    expect(result.current.libraryBusy).toBe(false);
    expect(result.current.hub.library.items).toEqual(snapshot().library.items);
    expect(result.current.hub.library.next_cursor).toBe('cursor-1');
    expect(notify).not.toHaveBeenCalled();
    getAccountWorkLibrary.mockResolvedValueOnce({
      items: [{ file_id: 'first-file' }, { file_id: 'second-file' }], next_cursor: null,
    });
    await act(async () => result.current.loadMoreLibrary());
    expect(result.current.libraryPageError).toBe(false);
    expect(result.current.hub.library.items.map((item) => item.file_id)).toEqual(['first-file', 'second-file']);
    expect(getAccountWorkLibrary.mock.calls.map(([options]) => options.params)).toEqual([
      { cursor: 'cursor-1' }, { cursor: 'cursor-1' },
    ]);
  });

  it('a retained old-thread page callback cannot fetch or append into the new thread', async () => {
    const { result, rerender } = renderSnapshot();
    await loaded(result);
    const previousPage = result.current.loadMoreLibrary;
    getWorkHub.mockResolvedValueOnce({
      ...snapshot(),
      library: { items: [{ file_id: 'new-thread-file' }], next_cursor: 'new-thread-cursor' },
    });
    rerender({ threadId: 'thread-2' });
    await waitFor(() => expect(result.current.hub.library.next_cursor).toBe('new-thread-cursor'));
    getAccountWorkLibrary.mockResolvedValueOnce({ items: [{ file_id: 'wrong-context-page' }] });
    await act(async () => previousPage());
    expect(getAccountWorkLibrary).not.toHaveBeenCalled();
    expect(result.current.hub.library.items.map((item) => item.file_id)).toEqual(['new-thread-file']);
    expect(result.current.libraryBusy).toBe(false);
  });

  it('a retained previous-cursor callback cannot replay an already consumed page', async () => {
    const { result } = renderSnapshot();
    await loaded(result);
    const previousPage = result.current.loadMoreLibrary;
    getAccountWorkLibrary.mockResolvedValueOnce({
      items: [{ file_id: 'second-file' }], next_cursor: 'cursor-2',
    });
    await act(async () => previousPage());
    expect(result.current.hub.library.next_cursor).toBe('cursor-2');
    await act(async () => previousPage());
    expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1);
    expect(result.current.hub.library.next_cursor).toBe('cursor-2');
  });

  it('a retained page callback after unmount cannot start another request', async () => {
    const { result, unmount } = renderSnapshot();
    await loaded(result);
    const previousPage = result.current.loadMoreLibrary;
    unmount();
    await act(async () => previousPage());
    expect(getAccountWorkLibrary).not.toHaveBeenCalled();
  });

  it('does not carry page errors into a new thread', async () => {
    getAccountWorkLibrary.mockRejectedValueOnce({ status: 503 });
    const { result, rerender } = renderSnapshot();
    await loaded(result);
    await act(async () => result.current.loadMoreLibrary());
    expect(result.current.libraryPageError).toBe(true);
    await act(async () => rerender({ threadId: 'thread-2' }));
    await waitFor(() => expect(result.current.libraryPageError).toBe(false));
  });

  it('an old passive GET cannot erase an explicitly accepted activation snapshot', async () => {
    const pending = deferred();
    getWorkHub.mockReturnValueOnce(pending.promise);
    const { result } = renderSnapshot();
    await waitFor(() => expect(getWorkHub).toHaveBeenCalledTimes(1));
    act(() => result.current.applySnapshot(snapshot(), 'thread-1'));
    await act(async () => pending.resolve(snapshot('absent')));
    expect(result.current.hub.workspace.state).toBe('ready');
    expect(getWorkHub.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it('clears cursor busy ownership on background refresh and allows another page load', async () => {
    const pending = deferred();
    getAccountWorkLibrary.mockReturnValueOnce(pending.promise);
    const { result } = renderSnapshot();
    await loaded(result);
    let paging;
    act(() => { paging = result.current.loadMoreLibrary(); });
    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1));
    await act(async () => result.current.load({ background: true }));
    await act(async () => { pending.resolve({ items: [{ file_id: 'obsolete-page' }] }); await paging; });
    expect(result.current.libraryBusy).toBe(false);
    expect(result.current.hub.library.items.map((item) => item.file_id)).toEqual(['first-file']);
    await act(async () => result.current.loadMoreLibrary());
    expect(getAccountWorkLibrary).toHaveBeenCalledTimes(2);
  });

  it('coalesces duplicate page activation before a render', async () => {
    const pending = deferred();
    getAccountWorkLibrary.mockReturnValue(pending.promise);
    const { result } = renderSnapshot();
    await loaded(result);
    let first;
    let second;
    act(() => { first = result.current.loadMoreLibrary(); second = result.current.loadMoreLibrary(); });
    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalled());
    expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve({ items: [] }); await Promise.all([first, second]); });
  });

  it('an obsolete page completion cannot clear the new page busy state', async () => {
    const oldPage = deferred();
    const newPage = deferred();
    getAccountWorkLibrary.mockReturnValueOnce(oldPage.promise).mockReturnValueOnce(newPage.promise);
    const { result } = renderSnapshot();
    await loaded(result);
    let oldRequest;
    act(() => { oldRequest = result.current.loadMoreLibrary(); });
    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1));
    await act(async () => result.current.load({ background: true }));
    expect(getAccountWorkLibrary.mock.calls[0][0].signal.aborted).toBe(true);
    let newRequest;
    act(() => { newRequest = result.current.loadMoreLibrary(); });
    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(2));
    await act(async () => { oldPage.resolve({ items: [] }); await oldRequest; });
    expect(result.current.libraryBusy).toBe(true);
    await act(async () => {
      newPage.resolve({ items: [{ file_id: 'new-page' }], next_cursor: null });
      await newRequest;
    });
    expect(result.current.libraryBusy).toBe(false);
    expect(result.current.hub.library.items.map((item) => item.file_id))
      .toEqual(['first-file', 'new-page']);
  });

  it('unmount aborts pagination and suppresses its late failure', async () => {
    const pending = deferred();
    getAccountWorkLibrary.mockReturnValueOnce(pending.promise);
    const { result, unmount } = renderSnapshot();
    await loaded(result);
    let paging;
    act(() => { paging = result.current.loadMoreLibrary(); });
    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1));
    unmount();
    expect(getAccountWorkLibrary.mock.calls[0][0].signal.aborted).toBe(true);
    await act(async () => { pending.reject({ status: 503 }); await paging; });
    expect(notify).not.toHaveBeenCalled();
  });

  it('a late old-thread page failure neither notifies nor locks the next thread', async () => {
    const pending = deferred();
    getAccountWorkLibrary.mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderSnapshot();
    await loaded(result);
    let paging;
    act(() => { paging = result.current.loadMoreLibrary(); });
    await waitFor(() => expect(getAccountWorkLibrary).toHaveBeenCalledTimes(1));
    rerender({ threadId: 'thread-2' });
    await loaded(result);
    await act(async () => { pending.reject({ status: 503 }); await paging; });
    expect(result.current.libraryBusy).toBe(false);
    expect(notify).not.toHaveBeenCalled();
  });
});
