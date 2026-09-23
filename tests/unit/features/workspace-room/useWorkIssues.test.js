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
});
