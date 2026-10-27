import { act, renderHook, waitFor } from '@testing-library/react';
import { getWorkspaceIssues } from '@api/chat';
import { useWorkIssues } from '@features/workspace-room/model/useWorkIssues';

jest.mock('@api/chat', () => ({
  getWorkspaceIssues: jest.fn(),
}));

describe('useWorkIssues', () => {
  beforeEach(() => getWorkspaceIssues.mockReset());

  it('keeps the last valid issues when a refresh becomes temporarily unavailable', async () => {
    getWorkspaceIssues
      .mockResolvedValueOnce({ issues: [{ issue_id: 'issue-1', title: 'Проверить файл' }] })
      .mockRejectedValueOnce(new Error('temporary'));
    const { result } = renderHook(() => useWorkIssues({
      threadId: 'thread-1',
      workspaceState: 'ready',
    }));

    await waitFor(() => expect(result.current.status).toBe('ready'));
    await act(async () => result.current.load());

    expect(result.current.status).toBe('stale');
    expect(result.current.items).toEqual([{ issue_id: 'issue-1', title: 'Проверить файл' }]);
  });

  it('does not expose issues from the previous thread after navigation', async () => {
    getWorkspaceIssues
      .mockResolvedValueOnce({ issues: [{ issue_id: 'old', title: 'Старый чат' }] })
      .mockResolvedValueOnce({ issues: [{ issue_id: 'new', title: 'Новый чат' }] });
    const { result, rerender } = renderHook(
      ({ threadId }) => useWorkIssues({ threadId, workspaceState: 'ready' }),
      { initialProps: { threadId: 'thread-1' } },
    );
    await waitFor(() => expect(result.current.items[0]?.issue_id).toBe('old'));

    rerender({ threadId: 'thread-2' });
    expect(result.current.items).toEqual([]);
    await waitFor(() => expect(result.current.items[0]?.issue_id).toBe('new'));
  });

  it('retains a confirmed empty list as stale rather than unavailable', async () => {
    getWorkspaceIssues.mockResolvedValueOnce({ issues: [] })
      .mockRejectedValueOnce(new Error('private-response-body'));
    const { result } = renderHook(() => useWorkIssues({
      threadId: 'thread-1', workspaceState: 'ready',
    }));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    await act(async () => result.current.load());
    expect(result.current.status).toBe('stale');
    expect(result.current.items).toEqual([]);
  });

  it('rejects late success after unmount even when the transport ignores abort', async () => {
    let resolve;
    getWorkspaceIssues.mockResolvedValueOnce({ issues: [] })
      .mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const { result, unmount } = renderHook(() => useWorkIssues({
      threadId: 'thread-1', workspaceState: 'ready',
    }));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    let pending;
    act(() => { pending = result.current.load(); });
    await waitFor(() => expect(getWorkspaceIssues).toHaveBeenCalledTimes(2));
    const signal = getWorkspaceIssues.mock.calls[1][1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
    resolve({ issues: [{ issue_id: 'late', title: 'Поздний ответ' }] });
    expect(await pending).toBe(false);
  });

  it.each([
    { threadId: 'thread-old', workspaceState: 'ready' },
    { threadId: 'thread-new', workspaceState: 'absent' },
  ])('ignores a refresh owned by a replaced context: %o', async (previous) => {
    let resolveCurrent;
    getWorkspaceIssues.mockImplementation((threadId) => (
      threadId === 'thread-old'
        ? Promise.resolve({ issues: [] })
        : new Promise((resolve) => { resolveCurrent = resolve; })
    ));
    const { result, rerender } = renderHook((props) => useWorkIssues(props), {
      initialProps: previous,
    });
    if (previous.workspaceState === 'ready') {
      await waitFor(() => expect(result.current.status).toBe('ready'));
    }
    const oldLoad = result.current.load;
    rerender({ threadId: 'thread-new', workspaceState: 'ready' });
    await waitFor(() => expect(resolveCurrent).toBeDefined());
    const currentCall = getWorkspaceIssues.mock.calls.at(-1);
    const callCount = getWorkspaceIssues.mock.calls.length;
    const pendingStatus = result.current.status;
    let accepted;
    await act(async () => { accepted = await oldLoad(); });
    expect(accepted).toBe(false);
    expect(currentCall[1].signal.aborted).toBe(false);
    expect(getWorkspaceIssues).toHaveBeenCalledTimes(callCount);
    expect(result.current.status).toBe(pendingStatus);
    await act(async () => resolveCurrent({ issues: [{ issue_id: 'current' }] }));
    await waitFor(() => expect(result.current.items).toEqual([{ issue_id: 'current' }]));
  });

  it('does not dispatch a held refresh callback after unmount', async () => {
    getWorkspaceIssues.mockResolvedValue({ issues: [] });
    const { result, unmount } = renderHook(() => useWorkIssues({
      threadId: 'thread-1', workspaceState: 'ready',
    }));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const load = result.current.load;
    unmount();
    expect(await load()).toBe(false);
    expect(getWorkspaceIssues).toHaveBeenCalledTimes(1);
  });
});
